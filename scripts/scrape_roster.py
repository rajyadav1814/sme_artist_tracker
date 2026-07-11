#!/usr/bin/env python3
"""
Phase 1 — Roster Scraper
========================
Scrapes the Sony Music Latin artist roster and writes data/roster.json.

Strategy (per skill/references/scraping-strategy.md):
  1. Fetch SML /artists/ and paginated variants directly with curl fallback
  2. If site blocks us (403 / connection hang) → fall back to Wikipedia
  3. For each discovered artist, enrich via their SML detail page for social links
  4. Write data/roster.json in the shape expected by src/data/types.ts

Usage:
    .venv/bin/python scripts/scrape_roster.py [--output data/roster.json] [--delay 2.0]
    .venv/bin/python scripts/scrape_roster.py --skip-detail   # fast, fewer links
    .venv/bin/python scripts/scrape_roster.py --verbose        # debug logging
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Optional

import requests          # used only as curl fallback; primary HTTP is subprocess curl
from bs4 import BeautifulSoup

# ── Constants ─────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "roster.json"

SML_BASE    = "https://www.sonymusiclatin.com"
SML_ARTISTS = f"{SML_BASE}/artists/"
SML_PAGE    = f"{SML_BASE}/artist/page/{{n}}/"   # singular /artist/ per scraping-strategy.md

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Sony_Music_Latin"

# Max bytes to read from any single HTTP response (prevents hanging on large pages)
MAX_RESPONSE_BYTES = 4_000_000   # 4 MB — well above any artist roster page

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SOCIAL_PATTERNS: list[tuple[str, str]] = [
    ("instagram.com",    "instagram"),
    ("tiktok.com",       "tiktok"),
    ("youtube.com",      "youtube"),
    ("youtu.be",         "youtube"),
    ("twitter.com",      "x"),
    ("x.com",            "x"),
    ("open.spotify.com", "spotify"),
    ("music.apple.com",  "apple_music"),
    ("facebook.com",     "facebook"),
]

log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class SocialLinks:
    instagram:   Optional[str] = None
    youtube:     Optional[str] = None
    tiktok:      Optional[str] = None
    x:           Optional[str] = None
    spotify:     Optional[str] = None
    apple_music: Optional[str] = None
    facebook:    Optional[str] = None


@dataclass
class RosterArtist:
    name:             str
    slug:             str
    profile_url:      str
    image_url:        str
    image_local_path: str
    bio_excerpt:      str
    social_links:     SocialLinks = field(default_factory=SocialLinks)

    def to_dict(self) -> dict:
        return asdict(self)   # asdict recurses into nested dataclasses


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url: str, max_time: int = 12) -> bytes | None:
    """
    Fetch url via curl (reliable on macOS/Linux; bypasses Python socket sandbox issues).
    Returns raw bytes capped at MAX_RESPONSE_BYTES, or None on failure.

    Falls back to requests if curl is not available.
    """
    log.debug("GET %s", url)

    # ── Primary: curl ─────────────────────────────────────────────────────────
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-L",
                "--max-time", str(max_time),
                "--compressed",                         # accept gzip
                "-H", f"User-Agent: {HEADERS['User-Agent']}",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", "Accept: text/html,application/xhtml+xml,*/*;q=0.8",
                "--write-out", "\n%%STATUS%%:%{http_code}",
                url,
            ],
            capture_output=True,
            timeout=max_time + 3,
        )
        if result.returncode == 0 and result.stdout:
            raw = result.stdout
            # Strip the status trailer we appended
            if b"\n%STATUS%:" in raw:
                body, trailer = raw.rsplit(b"\n%STATUS%:", 1)
                status_code = int(trailer.strip()) if trailer.strip().isdigit() else 0
            else:
                body, status_code = raw, 200
            if status_code not in (200, 0):
                log.warning("curl HTTP %d for %s", status_code, url)
                return None
            return body[:MAX_RESPONSE_BYTES]
        log.warning("curl exit %d for %s", result.returncode, url)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.info("curl unavailable (%s) — falling back to requests", exc)

    # ── Fallback: requests (non-streaming to avoid iter_content hang) ─────────
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=(6, 12), allow_redirects=True)
        if resp.status_code == 200:
            return resp.content[:MAX_RESPONSE_BYTES]
        log.warning("requests HTTP %d for %s", resp.status_code, url)
    except requests.RequestException as exc:
        log.warning("requests also failed for %s: %s", url, exc)

    return None


def make_soup(raw: bytes) -> BeautifulSoup:
    """Parse HTML bytes with html.parser (stdlib — no lxml dependency)."""
    return BeautifulSoup(raw, "html.parser")


def content_hash(raw: bytes) -> str:
    """Short fingerprint used to detect duplicate pages in pagination."""
    return hashlib.md5(raw[:4096]).hexdigest()


# ── Social-link extraction ────────────────────────────────────────────────────

def extract_social_links(tag_soup: BeautifulSoup) -> SocialLinks:
    links = SocialLinks()
    for anchor in tag_soup.find_all("a", href=True):
        href: str = anchor["href"].strip()
        for domain, field_name in SOCIAL_PATTERNS:
            if domain in href and getattr(links, field_name) is None:
                setattr(links, field_name, href)
                break
    return links


def merge_social(base: SocialLinks, extra: SocialLinks) -> SocialLinks:
    merged = SocialLinks()
    for f in ("instagram", "youtube", "tiktok", "x", "spotify", "apple_music", "facebook"):
        setattr(merged, f, getattr(base, f) or getattr(extra, f))
    return merged


# ── Slug / URL helpers ────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    # Decompose accented chars (é → e + combining accent) then drop the accents
    slug = unicodedata.normalize("NFKD", name.lower())
    slug = "".join(c for c in slug if not unicodedata.combining(c))
    slug = re.sub(r"[''ʼ´`]", "", slug)
    slug = re.sub(r"[^a-z0-9\s-]", " ", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return re.sub(r"-+", "-", slug)


def artist_profile_url(slug: str) -> str:
    return f"{SML_BASE}/artists/{slug}/"


def image_placeholder(slug: str) -> str:
    return f"https://placehold.co/400x400/1A1A1A/999999?text={urllib.parse.quote(slug)}"


# ── Strategy 1 — Direct SML scrape ───────────────────────────────────────────

def _parse_sml_card(card: BeautifulSoup, base_url: str) -> RosterArtist | None:
    """Extract one artist from an SML grid card element."""
    name_tag = card.find(["h2", "h3", "h4"])
    if not name_tag:
        return None
    name = name_tag.get_text(strip=True)
    if not name or len(name) < 2:
        return None

    # Profile URL: first <a> that contains /artist in its href
    profile_url = ""
    for a in card.find_all("a", href=True):
        href: str = a["href"]
        if re.search(r"/artist", href, re.I) and href not in ("/artists/", "/artist/"):
            profile_url = urllib.parse.urljoin(base_url, href)
            break
    if not profile_url:
        profile_url = artist_profile_url(slugify(name))

    slug = profile_url.rstrip("/").split("/")[-1] or slugify(name)

    # Image
    img = card.find("img")
    image_url = ""
    if img and img.get("src") and not str(img["src"]).startswith("data:"):
        image_url = urllib.parse.urljoin(base_url, img["src"])
    if not image_url:
        image_url = image_placeholder(slug)

    # Bio (optional short excerpt)
    bio = ""
    for p in card.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 20:
            bio = text[:300]
            break

    return RosterArtist(
        name=name,
        slug=slug,
        profile_url=profile_url,
        image_url=image_url,
        image_local_path=f"data/images/{slug}.jpg",
        bio_excerpt=bio,
        social_links=extract_social_links(card),
    )


def _cards_from_page(page: BeautifulSoup) -> list[BeautifulSoup]:
    """Return all elements that look like artist grid cards."""
    # SML WordPress themes typically use <article> elements
    articles = page.find_all("article")
    if articles:
        return articles
    # Fallback: divs/lis with artist-related class names
    return (
        page.find_all(class_=re.compile(r"artist", re.I))
        or page.find_all("li", class_=re.compile(r"post", re.I))
    )


def scrape_sml_direct(delay: float) -> list[RosterArtist] | None:
    """
    Strategy 1: crawl the SML paginated roster.
    Returns a list of artists, or None if the site is completely inaccessible.
    """
    log.info("Strategy 1: direct SML scrape")

    raw = fetch(SML_ARTISTS)
    if raw is None:
        raw = fetch(SML_PAGE.format(n=1))
    if raw is None:
        log.warning("SML blocked on both /artists/ and /artist/page/1/ — falling back")
        return None

    all_artists: list[RosterArtist] = []
    seen_slugs: set[str] = set()
    seen_hashes: set[str] = set()
    page_num = 1
    current_raw = raw

    while True:
        page_hash = content_hash(current_raw)
        if page_hash in seen_hashes:
            log.info("  Page %d content matches a previous page — stopping", page_num)
            break
        seen_hashes.add(page_hash)

        page = make_soup(current_raw)
        new_this_page = 0

        for card in _cards_from_page(page):
            artist = _parse_sml_card(card, SML_ARTISTS)
            if artist and artist.slug not in seen_slugs:
                all_artists.append(artist)
                seen_slugs.add(artist.slug)
                new_this_page += 1

        log.info("  Page %d — +%d artists (total %d)", page_num, new_this_page, len(all_artists))

        # Stop if this page added nothing — we've gone past the end
        if new_this_page == 0 and page_num > 1:
            log.info("  No new artists on page %d — pagination complete", page_num)
            break

        # Find next page — prefer rel="next" link, fall back to numbered URL
        next_a = page.find("a", rel="next")
        if next_a and next_a.get("href"):
            next_url = urllib.parse.urljoin(SML_ARTISTS, next_a["href"])
        else:
            page_num += 1
            next_url = SML_PAGE.format(n=page_num)

        time.sleep(delay)
        next_raw = fetch(next_url)
        if next_raw is None:
            log.info("  Page %d returned nothing — stopping", page_num)
            break

        current_raw = next_raw

    if not all_artists:
        log.warning("Direct SML scrape found 0 artists — falling back")
        return None

    return all_artists


# ── Strategy 2 — Wikipedia fallback ──────────────────────────────────────────

# Words that identify record labels / companies, not artists
_LABEL_WORDS = re.compile(
    r"\b(records?|music|entertainment|label|studio|group|media|publishing|"
    r"international|inc\.?|llc|ltd|corp\.?|management|distribution)\b",
    re.I,
)


def _looks_like_label(name: str) -> bool:
    return bool(_LABEL_WORDS.search(name))


def _extract_names_from_section(section_soup: BeautifulSoup, seen: set[str]) -> list[str]:
    """Pull linked artist names from a BeautifulSoup subtree."""
    names: list[str] = []
    for link in section_soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        href: str = link["href"]
        if (
            text
            and len(text) > 1
            and "/wiki/" in href
            and ":" not in href          # skip Wikipedia:/File:/etc.
            and not _looks_like_label(text)
            and text.lower() not in seen
        ):
            names.append(text)
            seen.add(text.lower())
    return names


def scrape_wikipedia(delay: float) -> list[RosterArtist]:
    """Strategy 2: extract current artist names from the Wikipedia Sony Music Latin article."""
    log.info("Strategy 2: Wikipedia — %s", WIKIPEDIA_URL)
    raw = fetch(WIKIPEDIA_URL)
    if raw is None:
        log.warning("Wikipedia also unreachable — using seed list")
        return []

    page = make_soup(raw)
    names: list[str] = []
    seen: set[str] = set()

    # Walk headings and collect only from sections whose title suggests a current roster
    current_section_active = False
    for tag in page.find_all(["h2", "h3", "h4", "ul", "ol", "table"]):
        tag_name = tag.name
        if tag_name in ("h2", "h3", "h4"):
            heading = tag.get_text(strip=True).lower()
            current_section_active = any(
                kw in heading for kw in ("current", "artist", "roster", "act")
            ) and not any(
                kw in heading for kw in ("former", "past", "previous", "reference", "note")
            )
            log.debug("  heading=%r  active=%s", heading, current_section_active)
        elif current_section_active and tag_name in ("ul", "ol"):
            names.extend(_extract_names_from_section(tag, seen))
        elif current_section_active and tag_name == "table":
            names.extend(_extract_names_from_section(tag, seen))

    # If section targeting found nothing useful, fall back to all wikitables
    if len(names) < 10:
        log.info("  Section scan found %d — scanning all wikitables", len(names))
        for table in page.find_all("table", class_="wikitable"):
            names.extend(_extract_names_from_section(table, seen))

    log.info("  Wikipedia: %d candidate names after filtering", len(names))
    time.sleep(delay)

    if not names:
        return []

    artists = []
    for name in names:
        slug = slugify(name)
        artists.append(RosterArtist(
            name=name,
            slug=slug,
            profile_url=artist_profile_url(slug),
            image_url=image_placeholder(slug),
            image_local_path=f"data/images/{slug}.jpg",
            bio_excerpt="",
            social_links=SocialLinks(),
        ))
    return artists


# ── Strategy 3 — Hardcoded seed list ─────────────────────────────────────────

SEED_ROSTER: list[tuple[str, str]] = [
    ("Abraham Mateo",      "abraham-mateo"),
    ("Alejandro Sanz",     "alejandro-sanz"),
    ("Alex Luna",          "alex-luna"),
    ("Alexis & Fido",      "alexis-fido"),
    ("Arthur Hanlon",      "arthur-hanlon"),
    ("Becky G",            "becky-g"),
    ("Bomba Estéreo",      "bomba-estereo"),
    ("Camilo",             "camilo"),
    ("Carlos Vives",       "carlos-vives"),
    ("Chayanne",           "chayanne"),
    ("Christina Aguilera", "christina-aguilera"),
    ("CNCO",               "cnco"),
    ("Daddy Yankee",       "daddy-yankee"),
    ("Don Omar",           "don-omar"),
    ("Draco Rosa",         "draco-rosa"),
    ("Emilia",             "emilia"),
    ("Enrique Iglesias",   "enrique-iglesias"),
    ("Evaluna Montaner",   "evaluna-montaner"),
    ("Farina",             "farina"),
    ("Fonseca",            "fonseca"),
    ("Franco De Vita",     "franco-de-vita"),
    ("Fuerza Regida",      "fuerza-regida"),
    ("Gente de Zona",      "gente-de-zona"),
    ("Gilberto Santa Rosa","gilberto-santa-rosa"),
    ("Gloria Estefan",     "gloria-estefan"),
    ("Ha*Ash",             "ha-ash"),
    ("Il Volo",            "il-volo"),
    ("Jennifer Lopez",     "jennifer-lopez"),
    ("Julio Iglesias",     "julio-iglesias"),
    ("Kany García",        "kany-garcia"),
    ("Lali",               "lali"),
    ("Maluma",             "maluma"),
    ("Manuel Turizo",      "manuel-turizo"),
    ("Marc Anthony",       "marc-anthony"),
    ("Mau y Ricky",        "mau-y-ricky"),
    ("Milo J",             "milo-j"),
    ("Natti Natasha",      "natti-natasha"),
    ("Nicky Jam",          "nicky-jam"),
    ("Ozuna",              "ozuna"),
    ("Prince Royce",       "prince-royce"),
    ("Rauw Alejandro",     "rauw-alejandro"),
    ("Ricky Martin",       "ricky-martin"),
    ("Romeo Santos",       "romeo-santos"),
    ("Rosalía",            "rosalia"),
    ("Sebastián Yatra",    "sebastian-yatra"),
    ("Shakira",            "shakira"),
    ("Tini",               "tini"),
    ("Victor Manuelle",    "victor-manuelle"),
    ("Wisin",              "wisin"),
    ("Wisin & Yandel",     "wisin-yandel"),
    ("Yandel",             "yandel"),
]


def build_from_seed() -> list[RosterArtist]:
    log.info("Strategy 3: hardcoded seed list (%d artists)", len(SEED_ROSTER))
    return [
        RosterArtist(
            name=name, slug=slug,
            profile_url=artist_profile_url(slug),
            image_url=image_placeholder(slug),
            image_local_path=f"data/images/{slug}.jpg",
            bio_excerpt="",
            social_links=SocialLinks(),
        )
        for name, slug in SEED_ROSTER
    ]


# ── Per-artist detail enrichment ─────────────────────────────────────────────

def enrich_from_detail_page(artist: RosterArtist, delay: float) -> None:
    """
    Fetch the artist's SML detail page to fill in social_links, bio_excerpt, and image_url.
    Mutates artist in-place.  Skips silently on failure.
    """
    raw = fetch(artist.profile_url)
    if not raw:
        return

    page = make_soup(raw)

    # Social links — scan the entire page
    artist.social_links = merge_social(artist.social_links, extract_social_links(page))

    # Bio excerpt — first substantial paragraph in the content area
    if not artist.bio_excerpt:
        content = (
            page.find("div", class_=re.compile(r"entry-content|bio|about", re.I))
            or page.find("main")
            or page
        )
        for p in content.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) >= 80:
                artist.bio_excerpt = text[:300]
                break

    # Replace placeholder image with the headshot from the detail page
    if "placehold.co" in artist.image_url:
        img = (
            page.find("img", class_=re.compile(r"avatar|headshot|artist|wp-post-image", re.I))
            or (page.find(class_=re.compile(r"hero|banner|header-image", re.I)) or BeautifulSoup("", "html.parser")).find("img")
        )
        if img and img.get("src") and not str(img["src"]).startswith("data:"):
            artist.image_url = urllib.parse.urljoin(artist.profile_url, img["src"])

    time.sleep(delay)


# ── Deduplication & output ────────────────────────────────────────────────────

def deduplicate(artists: list[RosterArtist]) -> list[RosterArtist]:
    seen: set[str] = set()
    result: list[RosterArtist] = []
    for a in artists:
        if a.slug not in seen:
            result.append(a)
            seen.add(a.slug)
    return result


def write_roster(artists: list[RosterArtist], output: Path, source: str) -> None:
    payload = {
        "roster_date":  date.today().isoformat(),
        "source":       source,
        "artist_count": len(artists),
        "artists":      [a.to_dict() for a in artists],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("Wrote %d artists → %s", len(artists), output)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Sony Music Latin artist roster")
    parser.add_argument("--output",      type=Path,  default=DEFAULT_OUTPUT)
    parser.add_argument("--delay",       type=float, default=2.0,
                        help="Seconds between requests (default 2.0)")
    parser.add_argument("--skip-detail", action="store_true",
                        help="Skip per-artist detail page enrichment")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Discover artists ─────────────────────────────────────────────────────
    artists = scrape_sml_direct(args.delay)
    if artists:
        source = "sonymusiclatin.com — direct fetch"
    else:
        artists = scrape_wikipedia(args.delay)
        if len(artists) >= 10:
            source = "Wikipedia — Sony Music Latin article (SML roster is JS-rendered)"
        else:
            artists = build_from_seed()
            source = "hardcoded seed list (all live sources unavailable)"

    artists = deduplicate(artists)
    log.info("Discovery complete: %d unique artists (source: %s)", len(artists), source)

    # ── Enrich from individual detail pages ──────────────────────────────────
    if not args.skip_detail:
        log.info("Enriching from detail pages — use --skip-detail to bypass")
        for i, artist in enumerate(artists, 1):
            log.info("  [%d/%d] %s", i, len(artists), artist.name)
            enrich_from_detail_page(artist, args.delay)
    else:
        log.info("Skipping detail enrichment (--skip-detail)")

    write_roster(artists, args.output, source)
    print(f"\n✓  {len(artists)} artists → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
