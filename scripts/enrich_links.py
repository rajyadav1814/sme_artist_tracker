#!/usr/bin/env python3
"""
Phase 1b — Social Link Enrichment
===================================
Reads data/roster.json (which may have null social_links from the Wikipedia fallback)
and enriches each artist with verified social media URLs from MusicBrainz.

MusicBrainz is a free, open music encyclopedia with a public REST API that
contains verified external URL relations for most major artists:
  - Spotify artist pages
  - YouTube channels
  - Instagram, Twitter/X, Facebook, TikTok profiles

Rate limit: MusicBrainz allows 1 req/sec without auth. Script adds 1.1s delay.

Usage:
    .venv/bin/python scripts/enrich_links.py
    .venv/bin/python scripts/enrich_links.py --roster data/roster.json
    .venv/bin/python scripts/enrich_links.py --artist shakira
    .venv/bin/python scripts/enrich_links.py --dry-run   # show what would be added
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT           = Path(__file__).parent.parent
DEFAULT_ROSTER = ROOT / "data" / "roster.json"

MB_BASE = "https://musicbrainz.org/ws/2"
UA      = "sme-artistTracker/1.0 (research project)"

log = logging.getLogger(__name__)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> Any:
    """Fetch a JSON endpoint via curl. Returns parsed JSON or None."""
    cmd = [
        "curl", "-s", "-L", "--max-time", "15",
        "--compressed",
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: application/json",
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode != 0 or not r.stdout:
            return None
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as exc:
        log.debug("fetch_json failed for %s: %s", url, exc)
        return None


# ── MusicBrainz helpers ───────────────────────────────────────────────────────

PLATFORM_PATTERNS: list[tuple[str, str]] = [
    (r"open\.spotify\.com/artist/",   "spotify"),
    (r"spotify\.com/artist/",          "spotify"),
    (r"youtube\.com/@",                "youtube"),
    (r"youtube\.com/c/",               "youtube"),
    (r"youtube\.com/channel/",         "youtube"),
    (r"youtube\.com/user/",            "youtube"),
    (r"instagram\.com/",               "instagram"),
    (r"tiktok\.com/@",                 "tiktok"),
    (r"twitter\.com/",                 "x"),
    (r"x\.com/",                       "x"),
    (r"facebook\.com/",                "facebook"),
    (r"music\.apple\.com/",            "apple_music"),
    (r"soundcloud\.com/",              "soundcloud"),
]


def classify_url(url: str) -> str | None:
    """Return the platform key for a URL, or None if unrecognised."""
    for pattern, platform in PLATFORM_PATTERNS:
        if re.search(pattern, url, re.I):
            return platform
    return None


def search_artist_mbid(name: str) -> str | None:
    """
    Search MusicBrainz for an artist by name and return their MBID.
    Uses the first result with score >= 85 to avoid false positives.
    """
    encoded = urllib.parse.quote(name)
    url = f"{MB_BASE}/artist/?query=artist:{encoded}&limit=5&fmt=json"
    log.debug("  MB search: %s", name)

    data = fetch_json(url)
    if not data or "artists" not in data:
        return None

    for artist in data.get("artists", []):
        score = int(artist.get("score", 0))
        mb_name = artist.get("name", "")
        mbid = artist.get("id")

        if score >= 85 and mbid:
            log.debug("    found: %s (score=%d, mbid=%s)", mb_name, score, mbid)
            return mbid

    log.debug("    no high-confidence match for %r", name)
    return None


def fetch_artist_urls(mbid: str) -> dict[str, str]:
    """
    Fetch URL relations for an artist from MusicBrainz.
    Returns { platform: url } for all recognised platforms.
    """
    url = f"{MB_BASE}/artist/{mbid}?inc=url-rels&fmt=json"
    data = fetch_json(url)
    if not data:
        return {}

    links: dict[str, str] = {}
    for rel in data.get("relations", []):
        url_info = rel.get("url", {})
        resource = url_info.get("resource", "")
        if not resource:
            continue
        platform = classify_url(resource)
        if platform and platform not in links:
            links[platform] = resource
            log.debug("    %s → %s", platform, resource)

    return links


def discover_youtube_handle(name: str, slug: str) -> str | None:
    """
    Try common YouTube handle patterns for a given artist.
    Returns the full channel URL if a valid channel is found, else None.
    """
    # Candidates: @Slug, @NameNoSpaces, @NameOfficial, @NameTV
    candidates = [
        f"@{slug.replace('-', '')}",                           # @shakira
        f"@{name.replace(' ', '')}",                           # @Shakira
        f"@{name.replace(' ', '')}Official",                   # @ShakiraOfficial
        f"@{name.replace(' ', '')}VEVO",                       # @ShakiraVEVO
        f"@{slug.replace('-', '').title()}",
    ]
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)

    for handle in unique:
        url = f"https://www.youtube.com/{handle}"
        cmd = [
            "curl", "-s", "-L", "--max-time", "8",
            "--compressed", "--head",           # HEAD request — just check 200
            "-H", f"User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            url,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=12)
            if r.returncode == 0:
                header_text = r.stdout.decode("utf-8", errors="replace")
                # A real channel page returns HTTP/2 200 (redirects resolve via -L)
                if "HTTP/2 200" in header_text or "HTTP/1.1 200" in header_text:
                    log.debug("    YouTube handle found: %s", handle)
                    return url
        except Exception:
            pass
        time.sleep(0.3)

    return None


# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_artist(artist: dict, dry_run: bool = False) -> dict:
    """
    Attempt to fill null social_links entries for a single artist.
    Returns the updated artist dict.
    """
    name  = artist["name"]
    slug  = artist["slug"]
    links = dict(artist.get("social_links") or {})

    # Normalise: ensure all expected keys exist
    for key in ("instagram", "youtube", "tiktok", "x", "spotify",
                "apple_music", "facebook", "soundcloud"):
        links.setdefault(key, None)

    missing = [k for k, v in links.items() if not v]
    if not missing:
        log.info("  %s — all links present, skipping", name)
        artist["social_links"] = links
        return artist

    log.info("  %s — missing: %s", name, ", ".join(missing))

    if dry_run:
        return artist

    # ── Step 1: MusicBrainz ───────────────────────────────────────────────────
    mbid = search_artist_mbid(name)
    time.sleep(1.1)   # MusicBrainz rate limit: 1 req/sec

    mb_links: dict[str, str] = {}
    if mbid:
        mb_links = fetch_artist_urls(mbid)
        time.sleep(1.1)

    # Merge MB links into our link map (don't overwrite existing)
    added: list[str] = []
    for platform, url in mb_links.items():
        if platform in links and not links[platform]:
            links[platform] = url
            added.append(platform)

    if added:
        log.info("    MB added: %s", ", ".join(added))

    # ── Step 2: YouTube handle probe (if still missing) ───────────────────────
    if not links.get("youtube"):
        yt_url = discover_youtube_handle(name, slug)
        if yt_url:
            links["youtube"] = yt_url
            log.info("    YouTube probed: %s", yt_url)

    artist["social_links"] = links
    return artist


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich roster with social links")
    parser.add_argument("--roster",  type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--output",  type=Path, default=None,
                        help="Write enriched roster here (default: overwrites --roster)")
    parser.add_argument("--artist",  type=str, default=None,
                        help="Enrich only this slug")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.roster.exists():
        log.error("Roster not found: %s", args.roster)
        return 1

    roster = json.loads(args.roster.read_text())
    artists: list[dict] = roster["artists"]

    if args.artist:
        target_indices = [i for i, a in enumerate(artists) if a["slug"] == args.artist]
        if not target_indices:
            log.error("Artist slug %r not found", args.artist)
            return 1
        process_indices = target_indices
    else:
        process_indices = list(range(len(artists)))

    log.info("Enriching %d artists…", len(process_indices))

    for idx in process_indices:
        artists[idx] = enrich_artist(artists[idx], dry_run=args.dry_run)

    # ── Coverage summary ─────────────────────────────────────────────────────
    total = len(artists)
    for platform in ("spotify", "youtube", "instagram", "tiktok", "x"):
        count = sum(1 for a in artists if a.get("social_links", {}).get(platform))
        print(f"  {platform:12s}: {count:3d}/{total}")

    if not args.dry_run:
        output_path = args.output or args.roster
        roster["artists"] = artists
        output_path.write_text(json.dumps(roster, indent=2, ensure_ascii=False))
        log.info("Written → %s", output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
