#!/usr/bin/env python3
"""
Fetch artist images and update data/roster.json.

Source priority:
  1. Spotify open-page og:image  — every artist has a Spotify URL in the
     curated YAML, og:image returns a 640×640 official headshot. Reliable.
  2. Deezer Search API           — fallback for artists without Spotify.
  3. Wikipedia REST API thumbnail — last resort for established artists.

For each artist, the CDN URL is written to roster.json as image_url.
Optionally the image is also downloaded to data/images/{slug}.jpg.

Usage:
    .venv/bin/python scripts/fetch_images.py
    .venv/bin/python scripts/fetch_images.py --no-download   # URL only, skip disk save
    .venv/bin/python scripts/fetch_images.py --force         # re-fetch all, even if exists
    .venv/bin/python scripts/fetch_images.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT       = Path(__file__).parent.parent
ROSTER     = ROOT / "data" / "roster.json"
IMAGES_DIR = ROOT / "data" / "images"

DEEZER_SEARCH = "https://api.deezer.com/search/artist"
WIKI_SUMMARY  = "https://en.wikipedia.org/api/rest_v1/page/summary"
USER_AGENT    = "SonyLatinPulse/1.0 (artist-image-fetcher; contact@example.com)"

log = logging.getLogger(__name__)


# ── Image source helpers ───────────────────────────────────────────────────────

def spotify_image(spotify_url: str | None) -> str | None:
    """
    Fetch an artist's Spotify open page and extract the og:image URL — the
    official 640×640 headshot Spotify uses. Most reliable source we have:
    every artist in the curated list has a Spotify URL.
    """
    if not spotify_url or "open.spotify.com/artist/" not in spotify_url:
        return None

    req = urllib.request.Request(spotify_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read(200_000).decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("Spotify fetch failed for %s: %s", spotify_url, exc)
        return None

    # <meta property="og:image" content="https://i.scdn.co/image/...">
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if m:
        url = m.group(1)
        # Avoid Spotify's generic "no image" placeholder
        if "i.scdn.co" in url and "default" not in url.lower():
            return url
    return None


def deezer_image(artist_name: str) -> str | None:
    """
    Query Deezer's public artist-search endpoint.
    Returns the picture_xl URL (1000×1000) for the top hit, or None.
    """
    url = f"{DEEZER_SEARCH}?q={urllib.parse.quote(artist_name)}&limit=3"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for candidate in data.get("data") or []:
            img = candidate.get("picture_xl") or candidate.get("picture_big")
            if img and "default_avatar" not in img:
                return img
    except Exception as exc:
        log.debug("Deezer failed for %r: %s", artist_name, exc)
    return None


def wikipedia_image(artist_name: str) -> str | None:
    """
    Query Wikipedia's REST summary API for the artist's page thumbnail.
    Returns the image URL or None.
    """
    encoded = urllib.parse.quote(artist_name.replace(" ", "_"))
    url     = f"{WIKI_SUMMARY}/{encoded}"
    req     = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        # Prefer originalimage (full res) over thumbnail
        for key in ("originalimage", "thumbnail"):
            img = data.get(key)
            if img and img.get("source"):
                return img["source"]
    except Exception as exc:
        log.debug("Wikipedia failed for %r: %s", artist_name, exc)
    return None


# ── Image downloader ───────────────────────────────────────────────────────────

def download_image(url: str, dest: Path) -> bool:
    """Download an image URL to dest. Returns True on success."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.read())
        return True
    except Exception as exc:
        log.debug("Download failed %s: %s", url, exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch artist images from Deezer/Wikipedia")
    parser.add_argument("--no-download", action="store_true",
                        help="Update image_url in roster.json but skip saving to disk")
    parser.add_argument("--force",   action="store_true",
                        help="Re-fetch images even if a local file already exists")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    roster = json.loads(ROSTER.read_text())
    artists = roster["artists"]
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    updated = skipped = downloaded = failed = 0
    by_source: dict[str, int] = {"spotify": 0, "deezer": 0, "wikipedia": 0}

    for a in artists:
        slug      = a["slug"]
        name      = a.get("name", slug)
        spotify   = (a.get("social_links") or {}).get("spotify")
        dest      = IMAGES_DIR / f"{slug}.jpg"
        has_local = dest.exists() and dest.stat().st_size > 1024

        # Skip if we already have a good local file and aren't forcing a refresh
        if has_local and not args.force:
            log.debug("  %-32s  skip (local file exists)", slug)
            skipped += 1
            continue

        # ── Spotify og:image (primary — every curated artist has a Spotify URL) ─
        img_url: str | None = spotify_image(spotify)
        source  = "spotify"

        # ── Deezer (fallback) ─────────────────────────────────────────────────
        if not img_url:
            img_url = deezer_image(name)
            source  = "deezer"

        # ── Wikipedia (last resort) ───────────────────────────────────────────
        if not img_url:
            img_url = wikipedia_image(name)
            source  = "wikipedia"

        if not img_url:
            log.debug("  %-32s  no image found — keeping placeholder", slug)
            failed += 1
            continue

        by_source[source] += 1

        # Update roster entry
        a["image_url"] = img_url
        updated += 1
        log.debug("  %-32s  %-10s  %s", slug, source, img_url[:60])

        # Download to disk
        if not args.no_download:
            ok = download_image(img_url, dest)
            if ok:
                downloaded += 1
            else:
                log.warning("  %-32s  download failed", slug)

        # Polite delay — Deezer is generous but Wikipedia rate-limits at ~50/min
        time.sleep(0.3)

    # Write updated roster
    ROSTER.write_text(json.dumps(roster, indent=2, ensure_ascii=False))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n✓  Image fetch complete")
    print(f"   {updated:3d}  image URLs updated  "
          f"(Spotify: {by_source['spotify']}, Deezer: {by_source['deezer']}, "
          f"Wikipedia: {by_source['wikipedia']})")
    print(f"   {downloaded:3d}  images downloaded to data/images/")
    print(f"   {skipped:3d}  artists skipped (local file already exists)")
    print(f"   {failed:3d}  no image found (kept placeholder)")
    print(f"   roster.json written")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
