#!/usr/bin/env python3
"""
iTunes Search API harvester
===========================
Apple Music's web pages are JS-rendered and resist scraping (every prior
request returned ``data_source: "unavailable"``). The iTunes Search API,
however, is a free public JSON endpoint that returns structured data
without auth. This harvester is the project's primary Apple Music source.

Public entrypoint::

    harvest_itunes(name, *, country="us", apple_music_url=None) -> dict

The returned dict is shaped to drop directly into the ``apple_music`` slot of
each artist's harvest record::

    {
      "artist_id":      889327,
      "primary_genre":  "Pop",
      "latest_release": {"title": "...", "date": "YYYY-MM-DD",
                          "type": "album"|"single"|"ep"},
      "recent_releases_90d": int,                    # → KPI 11 input
      "total_albums":  int,                          # catalog depth
      "top_songs":     [{"title", "album", "release_date"}],
      "data_source":   "itunes_search_api",
      "data_freshness": "YYYY-MM-DD",
      "fetch_status":  "ok" | "no_match" | "error",
    }

KPI 11 (Apple Music Catalog Activity) reads ``recent_releases_90d``.
KPI 9 (Latest Release Recency) cross-checks ``latest_release.date`` against
the Spotify-derived release date and uses the more recent of the two.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any

ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
TODAY         = date.today().isoformat()

log = logging.getLogger(__name__)


# ── HTTP helper ──────────────────────────────────────────────────────────────

def _get_json(url: str, max_time: int = 12) -> dict | None:
    cmd = ["curl", "-s", "-L", "--max-time", str(max_time), "--compressed", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=max_time + 4)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.debug("itunes curl error %s: %s", url, exc)
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


# ── ID resolution ────────────────────────────────────────────────────────────

def _resolve_artist_id(
    name: str,
    apple_music_url: str | None,
    country: str,
) -> int | None:
    """
    Resolve to an Apple Music artist ID. Prefer the ID embedded in
    apple_music_url when present; fall back to /search?term=.
    """
    if apple_music_url:
        # Pattern: music.apple.com/{country}/artist/{slug}/{id}
        m = re.search(r"/artist/[^/]+/(\d+)", apple_music_url)
        if m:
            return int(m.group(1))

    encoded = urllib.parse.quote(name)
    url = f"{ITUNES_SEARCH}?term={encoded}&entity=musicArtist&limit=5&country={country}"
    data = _get_json(url)
    if not data or not data.get("results"):
        return None

    # Prefer an exact (case-insensitive) name match — protects against
    # "Shakira" vs "Shakira Martínez" collisions.
    norm = name.strip().lower()
    for r in data["results"]:
        if (r.get("artistName") or "").strip().lower() == norm:
            return r.get("artistId")
    return data["results"][0].get("artistId")


# ── Album lookup ─────────────────────────────────────────────────────────────

def _release_type(c: dict) -> str:
    """Best-effort classification: album / ep / single."""
    name = (c.get("collectionName") or "").lower()
    if " - single" in name or name.endswith("- single"):
        return "single"
    if " - ep" in name or name.endswith("- ep"):
        return "ep"
    if c.get("trackCount") and c["trackCount"] <= 3:
        return "single"
    return "album"


def _fetch_recent_releases(artist_id: int, country: str, limit: int = 30) -> list[dict]:
    """Return albums/singles sorted by release date descending."""
    url = (
        f"{ITUNES_LOOKUP}?id={artist_id}"
        f"&entity=album&limit={limit}&sort=recent&country={country}"
    )
    data = _get_json(url)
    if not data:
        return []

    releases: list[dict] = []
    for c in data.get("results", []):
        if c.get("wrapperType") != "collection":
            continue
        rd = c.get("releaseDate")
        if not rd:
            continue
        releases.append({
            "title":        c.get("collectionName"),
            "date":         rd[:10],
            "type":         _release_type(c),
            "artwork":      c.get("artworkUrl100"),
            "track_count":  c.get("trackCount"),
        })
    releases.sort(key=lambda r: r["date"], reverse=True)
    return releases


def _fetch_top_songs(artist_id: int, country: str, limit: int = 8) -> list[dict]:
    """Top tracks (sorted by Apple's relevance signal — primarily popularity)."""
    url = (
        f"{ITUNES_LOOKUP}?id={artist_id}"
        f"&entity=song&limit={limit}&sort=popular&country={country}"
    )
    data = _get_json(url)
    if not data:
        return []

    songs: list[dict] = []
    for r in data.get("results", []):
        if r.get("wrapperType") != "track" or r.get("kind") != "song":
            continue
        songs.append({
            "title":         r.get("trackName"),
            "album":         r.get("collectionName"),
            "release_date":  (r.get("releaseDate") or "")[:10],
        })
        if len(songs) >= limit:
            break
    return songs


# ── Public entrypoint ────────────────────────────────────────────────────────

def harvest_itunes(
    name:            str,
    *,
    country:         str = "us",
    apple_music_url: str | None = None,
) -> dict[str, Any]:
    """Run all iTunes lookups for one artist; safe to call without any URL."""
    artist_id = _resolve_artist_id(name, apple_music_url, country)
    base = {
        "artist_id":            None,
        "primary_genre":        None,
        "latest_release":       None,
        "recent_releases_90d":  None,
        "total_albums":         None,
        "top_songs":            [],
        "data_source":          "itunes_search_api",
        "data_freshness":       TODAY,
    }

    if artist_id is None:
        return {**base, "fetch_status": "no_match"}

    base["artist_id"] = artist_id

    releases = _fetch_recent_releases(artist_id, country)
    if not releases:
        # Artist exists in iTunes but has no album catalog returned —
        # rare, usually a featured-only artist. Treat as best-effort ok.
        return {**base, "fetch_status": "ok"}

    cutoff_90d = (date.today() - timedelta(days=90)).isoformat()
    recent_count = sum(1 for r in releases if r["date"] >= cutoff_90d)

    base["latest_release"]      = {
        "title": releases[0]["title"],
        "date":  releases[0]["date"],
        "type":  releases[0]["type"],
    }
    base["recent_releases_90d"] = recent_count
    base["total_albums"]        = sum(1 for r in releases if r["type"] == "album")

    base["top_songs"]   = _fetch_top_songs(artist_id, country)

    # Use the first release's primary_genre via a light artist lookup
    artist_data = _get_json(f"{ITUNES_LOOKUP}?id={artist_id}&country={country}")
    if artist_data and artist_data.get("results"):
        base["primary_genre"] = artist_data["results"][0].get("primaryGenreName")

    return {**base, "fetch_status": "ok"}


# ── CLI smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    test_name = sys.argv[1] if len(sys.argv) > 1 else "Shakira"
    out = harvest_itunes(test_name)
    print(f"\nstatus={out['fetch_status']}  artist_id={out['artist_id']}")
    print(f"primary_genre: {out['primary_genre']}")
    print(f"recent_releases_90d: {out['recent_releases_90d']}")
    print(f"total_albums: {out['total_albums']}")
    print(f"latest_release: {out['latest_release']}")
    print(f"top_songs: {len(out['top_songs'])}")
    for s in out["top_songs"][:5]:
        print(f"  • {s['title'][:50]}  ({s['album'][:40] if s['album'] else ''})")
