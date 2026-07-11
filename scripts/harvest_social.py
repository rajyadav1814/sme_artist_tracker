#!/usr/bin/env python3
"""
Phase 2 — Social Media Harvest
===============================
For each artist in data/roster.json, attempt to harvest social metrics
from publicly accessible pages and write a timestamped raw-data snapshot to
data/snapshots/{today}.json.

Scraping priority (per skill/references/scraping-strategy.md):
  1. Spotify artist page   — monthly listeners, latest release  (HTML + JSON in <script>)
  2. YouTube channel page  — subscriber count, recent video views
  3. Social Blade          — Instagram/TikTok follower aggregates
  4. DuckDuckGo Lite       — press mention count for past 7 days (KPI 10)
  5. null + fetch_status   — honest placeholder for JS-rendered platforms

HTTP transport: subprocess curl (avoids Python socket issues in some environments).
Encoding: BeautifulSoup html.parser (lxml removed — segfaults on Python 3.13 here).

Output format matches SKILL.md §3.3 and is consumed by compute_kpis.py.

Usage:
    .venv/bin/python scripts/harvest_social.py
    .venv/bin/python scripts/harvest_social.py --roster data/roster.json
    .venv/bin/python scripts/harvest_social.py --artist shakira   # single artist
    .venv/bin/python scripts/harvest_social.py --limit 5          # first 5 for testing
    .venv/bin/python scripts/harvest_social.py --delay 1.5        # polite rate limit
    .venv/bin/python scripts/harvest_social.py --dry-run          # parse roster, no HTTP
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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT            = Path(__file__).parent.parent
DEFAULT_ROSTER  = ROOT / "data" / "roster.json"
FALLBACK_ROSTER = ROOT / "data" / "sample-roster.json"
SNAPSHOTS_DIR   = ROOT / "data" / "snapshots"

TODAY = date.today().isoformat()
NOW   = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

# ── HTTP ──────────────────────────────────────────────────────────────────────

# NOTE: the full "Chrome/..." UA triggers Cloudflare bot detection on Spotify.
# This shorter Safari-like UA is served the real artist page.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
MAX_BYTES = 3_000_000   # cap per response — no artist page needs more than 3 MB

log = logging.getLogger(__name__)


def fetch(url: str, max_time: int = 14, extra_headers: list[str] | None = None) -> bytes | None:
    """
    Fetch url via curl, returning raw bytes (≤ MAX_BYTES).
    Returns None on any error.  Never raises.
    """
    cmd = [
        "curl", "-s", "-L",
        "--max-time", str(max_time),
        "--compressed",
        "-H", f"User-Agent: {UA}",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Accept: text/html,application/xhtml+xml,*/*;q=0.8",
    ]
    if extra_headers:
        for h in extra_headers:
            cmd += ["-H", h]
    cmd.append(url)

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=max_time + 4)
        if r.returncode != 0:
            log.debug("curl exit %d for %s", r.returncode, url)
            return None
        data = r.stdout
        if len(data) > MAX_BYTES:
            log.debug("Truncating %d → %d bytes for %s", len(data), MAX_BYTES, url)
            data = data[:MAX_BYTES]
        return data or None
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.debug("curl failed for %s: %s", url, exc)
        return None


def make_soup(raw: bytes) -> BeautifulSoup:
    return BeautifulSoup(raw, "html.parser")


# ── Handle extraction ─────────────────────────────────────────────────────────

def _last_path(url: str) -> str:
    """Return the last non-empty path segment, stripped of leading @."""
    return url.rstrip("/").rsplit("/", 1)[-1].lstrip("@")


def spotify_id(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", url)
    return m.group(1) if m else None


def youtube_handle(url: str | None) -> str | None:
    """Extract '@handle' or channel ID from a YouTube URL."""
    if not url:
        return None
    # @handle style
    m = re.search(r"youtube\.com/@([^/?&]+)", url)
    if m:
        return "@" + m.group(1)
    # /c/channelname or /channel/ID
    m = re.search(r"youtube\.com/(?:c/|channel/|user/)([^/?&]+)", url)
    return m.group(1) if m else _last_path(url)


def instagram_handle(url: str | None) -> str | None:
    if not url:
        return None
    return _last_path(url)


def tiktok_handle(url: str | None) -> str | None:
    if not url:
        return None
    return _last_path(url)


# ── Number parsers ────────────────────────────────────────────────────────────

def parse_abbrev(s: str) -> int | None:
    """'28.4M' → 28_400_000,  '1.2B' → 1_200_000_000,  '345K' → 345_000."""
    s = s.strip().replace(",", "")
    m = re.match(r"([\d.]+)\s*([KMBkmb]?)", s)
    if not m:
        return None
    val = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    elif suffix == "B":
        val *= 1_000_000_000
    return int(val)


def parse_comma_int(s: str) -> int | None:
    """'52,143,221' → 52143221."""
    digits = re.sub(r"[,\s]", "", s)
    return int(digits) if digits.isdigit() else None


# ── Platform harvesters ───────────────────────────────────────────────────────
# Each returns a dict matching the §3.3 platform schema.
# fetch_status values: "ok" | "blocked" | "no_url" | "js_rendered" | "parse_error" | "error"

def _platform_stub(status: str) -> dict[str, Any]:
    return {
        "data_source":    "unavailable",
        "data_freshness": None,
        "fetch_status":   status,
    }


# ── Spotify ───────────────────────────────────────────────────────────────────

def harvest_spotify(spotify_url: str | None) -> dict[str, Any]:
    """
    Fetch open.spotify.com/artist/{id} and extract:
      - monthly_listeners  (from JSON in <script> tags)
      - latest_release     (title + date from JSON)
      - top_tracks         (titles from JSON)
    """
    sid = spotify_id(spotify_url)
    if not sid:
        return {**_platform_stub("no_url"), "monthly_listeners": None,
                "latest_release": None, "top_tracks": []}

    url = f"https://open.spotify.com/artist/{sid}"
    log.debug("  spotify → %s", url)
    raw = fetch(url)
    if raw is None:
        return {**_platform_stub("error"), "monthly_listeners": None,
                "latest_release": None, "top_tracks": []}

    text = raw.decode("utf-8", errors="replace")

    # ── Monthly listeners ────────────────────────────────────────────────────
    # Spotify renders the count as plain text: "77,915,621 monthly listeners"
    # AND in og/twitter meta: "77.9M monthly listeners"
    monthly_listeners: int | None = None

    # Pattern 1: full integer with comma separators (highest precision)
    m = re.search(r'([\d,]{5,})\s+monthly\s+listener', text, re.I)
    if m:
        monthly_listeners = parse_comma_int(m.group(1))

    # Pattern 2: abbreviated form in meta description ("77.9M monthly listeners")
    if monthly_listeners is None:
        m = re.search(r'([\d.]+[KMBkmb])\s+monthly\s+listener', text, re.I)
        if m:
            monthly_listeners = parse_abbrev(m.group(1))

    # Pattern 3: JSON key (some Spotify pages embed this)
    if monthly_listeners is None:
        m = re.search(r'"monthlyListeners"\s*:\s*(\d+)', text)
        if m:
            monthly_listeners = int(m.group(1))

    # ── Latest release ───────────────────────────────────────────────────────
    # Spotify embeds release info in the page JSON. Try to find a structured
    # "releaseDate" near an album/single name first; fall back to most recent ISO date.
    latest_release: dict | None = None

    # Pattern: "releaseDate":"2024-03-22" near "name":"Title"
    for rm in re.finditer(r'"releaseDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"', text):
        rdate = rm.group(1)
        if "2000" < rdate <= TODAY:
            # Grab surrounding 500 chars for the album title
            window = text[max(0, rm.start() - 300): rm.start() + 200]
            nm = re.search(r'"name"\s*:\s*"([^"]{2,80})"', window)
            title = nm.group(1) if nm else None
            if latest_release is None or rdate > latest_release["date"]:
                latest_release = {"title": title, "date": rdate}

    # Fallback: any ISO date on the page
    if latest_release is None:
        past_dates = sorted(
            {d for d in re.findall(r'\d{4}-\d{2}-\d{2}', text) if "2000" < d <= TODAY},
            reverse=True,
        )
        if past_dates:
            latest_release = {"title": None, "date": past_dates[0]}

    # ── Top tracks ───────────────────────────────────────────────────────────
    # Spotify page embeds track titles in several possible ways.
    top_tracks: list[str] = []

    # Pattern 1: aria-label on play buttons "Play {title} by {artist}"
    for m in re.finditer(r'aria-label="Play\s+([^"]+?)\s+by\s+', text):
        title = m.group(1).strip()
        if title and title not in top_tracks:
            top_tracks.append(title)
        if len(top_tracks) >= 5:
            break

    # Pattern 2: JSON "trackTitle" keys in embedded script data
    if not top_tracks:
        for m in re.finditer(r'"trackTitle"\s*:\s*"([^"]+)"', text):
            title = m.group(1).strip()
            if title and title not in top_tracks:
                top_tracks.append(title)
            if len(top_tracks) >= 5:
                break

    status = "ok" if monthly_listeners is not None else "parse_error"
    return {
        "monthly_listeners": monthly_listeners,
        "top_tracks":        [{"title": t} for t in top_tracks],
        "latest_release":    latest_release,
        "data_source":       "spotify_page",
        "data_freshness":    TODAY,
        "fetch_status":      status,
    }


# ── YouTube ───────────────────────────────────────────────────────────────────

def harvest_youtube(youtube_url: str | None) -> dict[str, Any]:
    """
    Fetch youtube.com/@handle and extract subscriber count + recent video data.
    YouTube embeds ytInitialData JSON in a <script> tag.
    """
    handle = youtube_handle(youtube_url)
    if not handle:
        return {**_platform_stub("no_url"), "subscribers": None, "recent_videos": []}

    # Construct channel URL — fetch /videos tab for reliable videoRenderer blocks
    if handle.startswith("@"):
        url = f"https://www.youtube.com/{handle}/videos"
    elif re.match(r"UC[A-Za-z0-9_-]{22}", handle):
        url = f"https://www.youtube.com/channel/{handle}/videos"
    else:
        url = f"https://www.youtube.com/@{handle}/videos"

    log.debug("  youtube → %s", url)
    raw = fetch(url)
    if raw is None:
        return {**_platform_stub("error"), "subscribers": None, "recent_videos": []}

    text = raw.decode("utf-8", errors="replace")

    # ── Subscriber count ─────────────────────────────────────────────────────
    subscribers: int | None = None

    # Pattern 1: accessibility label "52 million subscribers"
    m = re.search(r'"label"\s*:\s*"([\d.,]+\s*[KMBkmb]?\s+[Ss]ubscriber[s]?)"', text)
    if m:
        subscribers = parse_abbrev(m.group(1).split()[0])

    # Pattern 2: subscriberCountText simpleText
    if subscribers is None:
        m = re.search(r'"subscriberCountText"\s*:\s*\{"simpleText"\s*:\s*"([^"]+)"', text)
        if m:
            subscribers = parse_abbrev(m.group(1).replace("subscribers", "").strip())

    # Pattern 3: "52M subscribers" anywhere in the page
    if subscribers is None:
        m = re.search(r'([\d.,]+[KMBkmb]?)\s+subscribers', text, re.I)
        if m:
            subscribers = parse_abbrev(m.group(1))

    # ── Recent video titles + views ──────────────────────────────────────────
    # YouTube migrated the channel /videos grid to lockupViewModel + richItemRenderer.
    # The legacy videoRenderer/gridVideoRenderer keys are no longer emitted.
    # Each lockupViewModel block contains, in order:
    #   - thumbnail URL  →  /vi/{VIDEO_ID}/hqdefault.jpg
    #   - "content": "Video Title"
    #   - "content": "1.2M views"
    #   - "content": "3 days ago"
    # We anchor on lockupViewModel and extract those fields by position.
    recent_videos: list[dict] = []
    seen_ids: set[str] = set()

    for lv_m in re.finditer(r'"lockupViewModel"\s*:\s*\{', text):
        window = text[lv_m.start(): lv_m.start() + 8000]

        # Video ID from the thumbnail URL — only path our scraper can rely on
        id_m = re.search(r'/vi/([A-Za-z0-9_-]{11})/', window)
        if not id_m:
            continue
        vid_id = id_m.group(1)
        if vid_id in seen_ids:
            continue

        # Pull the first several "content" fields. YouTube serves multiple layout
        # variants — sometimes "149K views" / "6 days ago", sometimes "149K" / "6d ago".
        # We classify each content string by shape rather than position.
        contents = re.findall(r'"content"\s*:\s*"([^"]{1,200})"', window)
        if len(contents) < 1:
            continue

        title = contents[0]
        views = None
        published_age = None

        # Also try to grab a viewCountText accessibility string anywhere in the
        # window — most reliable when present ("149,243 views").
        vc_acc = re.search(r'"accessibilityText"\s*:\s*"([\d.,]+\s+views?)"', window)
        if vc_acc:
            num_m = re.match(r'([\d.,]+)', vc_acc.group(1))
            if num_m:
                raw = num_m.group(1).replace(",", "")
                if raw.isdigit():
                    views = int(raw)

        for c in contents[1:6]:
            if views is None:
                # Long format: "149K views" / "1.2M views" / "1,234,567 views"
                if "view" in c.lower():
                    num_m = re.match(r'([\d.,]+[KMBkmb]?)', c)
                    if num_m:
                        raw = num_m.group(1)
                        views = (parse_comma_int(raw) if raw.replace(",", "").isdigit()
                                 else parse_abbrev(raw))
                # Short format: bare number with optional K/M/B suffix
                elif re.fullmatch(r'[\d.,]+[KMBkmb]?', c.strip()):
                    raw = c.strip()
                    views = (parse_comma_int(raw) if raw.replace(",", "").isdigit()
                             else parse_abbrev(raw))
            if published_age is None and re.search(r'\bago\b', c):
                published_age = c

        seen_ids.add(vid_id)
        recent_videos.append({
            "video_id":       vid_id,
            "title":          title,
            "views":          views,
            "published_date": published_age,   # human-readable; KPI 8 only needs views
        })
        if len(recent_videos) >= 5:   # keep top 5 for richer momentum sample
            break

    # Legacy fallback — older channel layouts still served videoRenderer
    if not recent_videos:
        for vr_m in re.finditer(r'"videoRenderer"\s*:\s*\{', text):
            window = text[vr_m.start(): vr_m.start() + 6000]
            id_m = re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', window)
            if not id_m or id_m.group(1) in seen_ids:
                continue
            t_m  = re.search(r'"title"\s*:\s*\{"runs"\s*:\s*\[\{"text"\s*:\s*"([^"]+)"', window)
            vc_m = re.search(r'"viewCountText"\s*:\s*\{"simpleText"\s*:\s*"([\d,]+)', window) \
                or re.search(r'"shortViewCountText"\s*:\s*\{"simpleText"\s*:\s*"([\d.,]+[KMBkmb]?)', window)
            if not t_m: continue
            views = None
            if vc_m:
                raw = vc_m.group(1)
                views = parse_comma_int(raw) if raw.replace(",", "").isdigit() else parse_abbrev(raw)
            seen_ids.add(id_m.group(1))
            recent_videos.append({"video_id": id_m.group(1), "title": t_m.group(1),
                                   "views": views, "published_date": None})
            if len(recent_videos) >= 5:
                break

    status = "ok" if subscribers is not None else "parse_error"
    return {
        "subscribers":   subscribers,
        "recent_videos": recent_videos,
        "data_source":   "youtube_page",
        "data_freshness": TODAY,
        "fetch_status":  status,
    }


# ── Social Blade (Instagram / TikTok aggregator) ──────────────────────────────

def _parse_socialblade_count(text: str) -> int | None:
    """
    Social Blade renders follower counts as formatted numbers in the page.
    Looks for: <span ...>28,467,420</span> in the top info block.
    """
    # Primary: large formatted number in the stats header
    m = re.search(
        r'<span[^>]*>\s*([\d,]+)\s*</span>',
        text,
    )
    if m:
        val = parse_comma_int(m.group(1))
        if val and val > 1000:   # filter out tiny numbers (ranks, etc.)
            return val

    # Fallback: abbreviated count like "28.4M"
    m = re.search(r'([\d.]+[KMBkmb])\s+(?:Followers|Subscribers|Fans)', text, re.I)
    if m:
        return parse_abbrev(m.group(1))
    return None


def harvest_instagram(instagram_url: str | None) -> dict[str, Any]:
    handle = instagram_handle(instagram_url)
    base = {
        "followers":        None,
        "posts_count":      None,
        "recent_posts":     [],
        "data_freshness":   None,
        "fetch_status":     "js_rendered",
    }
    if not handle:
        return {**base, **_platform_stub("no_url")}

    # Social Blade Instagram
    sb_url = f"https://socialblade.com/instagram/user/{handle}"
    log.debug("  instagram (socialblade) → %s", sb_url)
    raw = fetch(sb_url, extra_headers=["Referer: https://socialblade.com/"])
    if raw is None:
        return {**base, "data_source": "socialblade", "fetch_status": "blocked"}

    text = raw.decode("utf-8", errors="replace")
    if "captcha" in text.lower() or "access denied" in text.lower():
        return {**base, "data_source": "socialblade", "fetch_status": "blocked"}

    followers = _parse_socialblade_count(text)
    return {
        "followers":      followers,
        "posts_count":    None,
        "recent_posts":   [],
        "data_source":    "socialblade",
        "data_freshness": TODAY if followers else None,
        "fetch_status":   "ok" if followers else "parse_error",
    }


def harvest_tiktok(tiktok_url: str | None) -> dict[str, Any]:
    handle = tiktok_handle(tiktok_url)
    base = {"followers": None, "total_likes": None, "recent_videos": [],
            "data_freshness": None, "fetch_status": "js_rendered"}
    if not handle:
        return {**base, **_platform_stub("no_url")}

    sb_url = f"https://socialblade.com/tiktok/user/{handle.lstrip('@')}"
    log.debug("  tiktok (socialblade) → %s", sb_url)
    raw = fetch(sb_url, extra_headers=["Referer: https://socialblade.com/"])
    if raw is None:
        return {**base, "data_source": "socialblade", "fetch_status": "blocked"}

    text = raw.decode("utf-8", errors="replace")
    if "captcha" in text.lower() or "access denied" in text.lower():
        return {**base, "data_source": "socialblade", "fetch_status": "blocked"}

    followers = _parse_socialblade_count(text)
    return {
        "followers":      followers,
        "total_likes":    None,
        "recent_videos":  [],
        "data_source":    "socialblade",
        "data_freshness": TODAY if followers else None,
        "fetch_status":   "ok" if followers else "parse_error",
    }


def harvest_x(x_url: str | None) -> dict[str, Any]:
    """X/Twitter is fully JS-rendered; record link and null data."""
    base = {**_platform_stub("js_rendered"),
            "followers": None, "following": None, "recent_tweets": []}
    if x_url:
        base["profile_url"] = x_url
    return base


def harvest_facebook(fb_url: str | None) -> dict[str, Any]:
    base = {**_platform_stub("js_rendered"), "page_likes": None, "followers": None}
    if fb_url:
        base["profile_url"] = fb_url
    return base


def harvest_apple_music(name: str, am_url: str | None) -> dict[str, Any]:
    """
    Apple Music data via the iTunes Search API (free public JSON endpoint).
    The Apple Music web pages are JS-rendered and previously returned no
    usable data; iTunes Search is the project's authoritative Apple source.

    Returns the dict shape produced by harvest_itunes.harvest_itunes(),
    augmented with profile_url for downstream display.
    """
    from harvest_itunes import harvest_itunes
    result = harvest_itunes(name, apple_music_url=am_url)
    if am_url:
        result["profile_url"] = am_url
    return result


# ── Press mentions via DuckDuckGo Lite ────────────────────────────────────────

def harvest_press_mentions(artist_name: str) -> dict[str, Any]:
    """
    Proxy for KPI 10 (News & Press Mentions in past 7 days).
    Uses Google News RSS (plain XML, no authentication, no bot challenge).
    Returns count of articles found (capped at ~100 by Google).
    """
    query   = f'"{artist_name}" music'
    encoded = urllib.parse.quote(query)
    # tbs=qdr:w = past week
    url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=en-US&gl=US&ceid=US:en&tbs=qdr:w"
    )
    log.debug("  press → Google News RSS: %s", query)

    raw = fetch(url, max_time=12)
    if raw is None:
        return {"count": None, "source": "google_news_rss", "freshness": TODAY,
                "fetch_status": "error"}

    text = raw.decode("utf-8", errors="replace")

    # Each news item is wrapped in <item>...</item>
    count = len(re.findall(r"<item>", text))

    if count == 0 and "<channel>" not in text:
        return {"count": None, "source": "google_news_rss", "freshness": TODAY,
                "fetch_status": "blocked"}

    # Extract up to 5 headlines for context
    headlines = re.findall(r"<title><!\[CDATA\[([^\]]+)\]\]></title>", text)[1:6]  # skip channel title
    if not headlines:
        headlines = re.findall(r"<title>([^<]{10,100})</title>", text)[1:6]

    return {
        "count":        count,
        "headlines":    headlines,
        "source":       "google_news_rss",
        "freshness":    TODAY,
        "fetch_status": "ok",
    }


# ── Per-artist orchestrator ───────────────────────────────────────────────────

def harvest_artist(
    artist: dict,
    delay: float = 1.5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run all platform harvests for one artist.
    Returns the §3.3-shaped dict.
    """
    slug   = artist["slug"]
    name   = artist["name"]
    links  = artist.get("social_links", {})

    log.info("  [harvest] %s", name)

    if dry_run:
        return {
            "artist_slug":  slug,
            "artist_name":  name,
            "harvest_date": TODAY,
            "platforms":    {p: _platform_stub("dry_run") for p in
                             ("instagram", "youtube", "tiktok", "x",
                              "spotify", "apple_music", "facebook")},
            "press_mentions": {"count": None, "source": "dry_run",
                               "freshness": TODAY, "fetch_status": "dry_run"},
        }

    def _get(k: str) -> str | None:
        v = links.get(k)
        return v if isinstance(v, str) else None

    # Harvest each platform with per-request delay
    spotify_data = harvest_spotify(_get("spotify"))
    time.sleep(delay)

    youtube_data = harvest_youtube(_get("youtube"))
    time.sleep(delay)

    ig_data  = harvest_instagram(_get("instagram"))
    time.sleep(delay)

    tt_data  = harvest_tiktok(_get("tiktok"))
    time.sleep(delay)

    x_data   = harvest_x(_get("x"))
    fb_data  = harvest_facebook(_get("facebook"))
    am_data  = harvest_apple_music(name, _get("apple_music"))

    # kworb.net adds Spotify per-track stream totals + catalog stream count.
    # Merged into the existing spotify block so downstream consumers don't
    # need to know about a separate platform.
    from harvest_kworb import harvest_kworb_spotify
    kworb = harvest_kworb_spotify(_get("spotify"))
    if kworb.get("fetch_status") == "ok":
        spotify_data["kworb_top_tracks"]   = kworb["top_tracks"]
        spotify_data["kworb_total_streams"] = kworb["total_streams"]
    time.sleep(delay)

    press    = harvest_press_mentions(name)
    time.sleep(delay)

    return {
        "artist_slug":  slug,
        "artist_name":  name,
        "harvest_date": TODAY,
        "platforms": {
            "spotify":     spotify_data,
            "instagram":   ig_data,
            "youtube":     youtube_data,
            "tiktok":      tt_data,
            "x":           x_data,
            "facebook":    fb_data,
            "apple_music": am_data,
        },
        "press_mentions": press,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 — Social media harvest")
    parser.add_argument("--roster",  type=Path, default=None,
                        help="Path to roster JSON (default: data/roster.json)")
    parser.add_argument("--output",  type=Path, default=None,
                        help="Output path (default: data/snapshots/{today}.json)")
    parser.add_argument("--artist",  type=str, default=None,
                        help="Harvest only this artist slug")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Process only first N artists (for testing)")
    parser.add_argument("--delay",   type=float, default=1.5,
                        help="Seconds between requests per artist (default: 1.5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse roster but make no HTTP requests")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Load roster ──────────────────────────────────────────────────────────
    roster_path = args.roster
    if roster_path is None:
        roster_path = DEFAULT_ROSTER if DEFAULT_ROSTER.exists() else FALLBACK_ROSTER
    if not roster_path.exists():
        log.error("Roster not found: %s", roster_path)
        return 1

    roster = json.loads(roster_path.read_text())
    artists: list[dict] = roster["artists"]
    log.info("Loaded %d artists from %s", len(artists), roster_path)

    # ── Filter / limit ───────────────────────────────────────────────────────
    if args.artist:
        artists = [a for a in artists if a["slug"] == args.artist]
        if not artists:
            log.error("Artist slug %r not found in roster", args.artist)
            return 1
        log.info("Harvesting single artist: %s", args.artist)

    if args.limit:
        artists = artists[: args.limit]
        log.info("Limiting to first %d artists", args.limit)

    # ── Harvest ──────────────────────────────────────────────────────────────
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (SNAPSHOTS_DIR / f"{TODAY}.json")

    results: list[dict] = []
    total = len(artists)

    for i, artist in enumerate(artists, 1):
        log.info("[%d/%d] %s", i, total, artist["name"])
        try:
            result = harvest_artist(artist, delay=args.delay, dry_run=args.dry_run)
            results.append(result)
        except Exception as exc:
            log.warning("  Failed to harvest %s: %s", artist["slug"], exc)
            results.append({
                "artist_slug":    artist["slug"],
                "artist_name":    artist["name"],
                "harvest_date":   TODAY,
                "platforms":      {},
                "press_mentions": {},
                "harvest_error":  str(exc),
            })

        # Checkpoint after every 10 artists so a long run can be resumed
        if i % 10 == 0 or i == total:
            snapshot = {
                "harvest_date":    TODAY,
                "generated_at":    NOW,
                "roster_source":   str(roster_path),
                "artist_count":    len(results),
                "artists":         results,
            }
            output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
            log.info("  Checkpoint saved → %s (%d/%d artists)", output_path, i, total)

    print(f"\n✓  {len(results)} artists harvested → {output_path}")

    # Print a quick coverage summary
    ok_spotify  = sum(1 for r in results
                      if r.get("platforms", {}).get("spotify", {}).get("fetch_status") == "ok")
    ok_youtube  = sum(1 for r in results
                      if r.get("platforms", {}).get("youtube", {}).get("fetch_status") == "ok")
    ok_press    = sum(1 for r in results
                      if r.get("press_mentions", {}).get("fetch_status") == "ok")
    print(f"   Spotify monthly listeners: {ok_spotify}/{len(results)} artists")
    print(f"   YouTube subscriber count:  {ok_youtube}/{len(results)} artists")
    print(f"   Press mentions (DDG):      {ok_press}/{len(results)} artists")

    return 0


if __name__ == "__main__":
    sys.exit(main())
