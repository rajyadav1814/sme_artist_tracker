#!/usr/bin/env python3
"""
kworb.net harvester
===================
kworb maintains static (no-JS) pages with rich Spotify per-artist data:
  - kworb.net/spotify/artist/{spotify_id}.html        — top 100 tracks with stream totals
  - kworb.net/spotify/artist/{spotify_id}_songs.html  — full catalog with stream totals

This module exposes ``harvest_kworb_spotify(spotify_url) -> dict`` which returns:
  {
    "top_tracks":   [{"title": str, "streams": int, "peak_date": str}, ...],
    "total_streams": int | None,    # sum across the visible tracks
    "data_source":  "kworb",
    "data_freshness": "YYYY-MM-DD",
    "fetch_status": "ok" | "no_url" | "404" | "error",
  }

kworb's per-artist YouTube pages do not exist (404) — YouTube data continues
to come from harvest_social.harvest_youtube which parses the channel page
directly via lockupViewModel. This module is Spotify-only by design.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import date
from typing import Any

KWORB_BASE = "https://kworb.net/spotify/artist"
TODAY      = date.today().isoformat()

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

log = logging.getLogger(__name__)


# ── HTTP helper ──────────────────────────────────────────────────────────────

def _fetch(url: str, max_time: int = 12) -> tuple[int, bytes | None]:
    """Curl wrapper. Returns (status_code, body) — both None on transport error."""
    cmd = [
        "curl", "-s", "-L",
        "--max-time", str(max_time),
        "--compressed",
        "-H", f"User-Agent: {UA}",
        "-w", "\n%STATUS%:%{http_code}",
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=max_time + 4)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.debug("curl error %s: %s", url, exc)
        return 0, None

    if r.returncode != 0:
        return 0, None
    raw = r.stdout
    # Trailer we appended via -w: "...\n%STATUS%:200"
    status = 200
    if b"\n%STATUS%:" in raw:
        body, trailer = raw.rsplit(b"\n%STATUS%:", 1)
        if trailer.strip().isdigit():
            status = int(trailer.strip())
    else:
        body = raw
    return status, body


def _spotify_id(spotify_url: str | None) -> str | None:
    """Extract the Spotify artist ID from a profile URL."""
    if not spotify_url:
        return None
    m = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]{22})", spotify_url)
    return m.group(1) if m else None


# ── Parser ───────────────────────────────────────────────────────────────────

def _parse_kworb_table(html: str, max_tracks: int = 10) -> list[dict[str, Any]]:
    """
    kworb's track table rows look like:
       <tr><td>2023/03/04</td><td>...<a>TQG</a></td><td>1,051,003,425</td>...</tr>

    Returns a list of dicts with title, streams, peak_date.
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    tracks: list[dict[str, Any]] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 3:
            continue
        # Strip HTML tags from cells; first three are peak_date / title / streams
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells[:3]]
        peak_date, title, streams_str = clean

        # Peak date should look like YYYY/MM/DD or YYYY-MM-DD (skip header rows)
        if not re.match(r"^\d{4}[/-]\d{2}[/-]\d{2}$", peak_date):
            continue

        # Title may be prefixed with "* " (currently in top 200) — strip
        title = title.lstrip("* ").strip()
        if not title:
            continue

        streams_clean = streams_str.replace(",", "")
        if not streams_clean.isdigit():
            continue
        streams = int(streams_clean)

        tracks.append({
            "title":      title,
            "streams":    streams,
            "peak_date":  peak_date.replace("/", "-"),
        })
        if len(tracks) >= max_tracks:
            break
    return tracks


# ── Public entrypoint ────────────────────────────────────────────────────────

def harvest_kworb_spotify(spotify_url: str | None) -> dict[str, Any]:
    """
    Fetch kworb's per-artist Spotify page and return top tracks + total streams.
    Always returns a dict with at least ``fetch_status`` and ``data_freshness``.
    """
    artist_id = _spotify_id(spotify_url)
    if not artist_id:
        return {
            "top_tracks":     [],
            "total_streams":  None,
            "data_source":    "kworb",
            "data_freshness": TODAY,
            "fetch_status":   "no_url",
        }

    url = f"{KWORB_BASE}/{artist_id}.html"
    log.debug("  kworb → %s", url)
    status, body = _fetch(url)

    if body is None or status >= 400:
        return {
            "top_tracks":     [],
            "total_streams":  None,
            "data_source":    "kworb",
            "data_freshness": TODAY,
            "fetch_status":   f"{status}" if status else "error",
        }

    html = body.decode("utf-8", errors="replace")
    top_tracks = _parse_kworb_table(html, max_tracks=10)

    total_streams = sum(t["streams"] for t in top_tracks) if top_tracks else None

    return {
        "top_tracks":     top_tracks,
        "total_streams":  total_streams,
        "data_source":    "kworb",
        "data_freshness": TODAY,
        "fetch_status":   "ok" if top_tracks else "parse_empty",
    }


# ── CLI smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    test_url = sys.argv[1] if len(sys.argv) > 1 \
        else "https://open.spotify.com/artist/0EmeFodog0BfCgMzAIvKQp"
    out = harvest_kworb_spotify(test_url)
    print(f"\nstatus={out['fetch_status']}  total_streams={out['total_streams']}")
    print(f"top_tracks: {len(out['top_tracks'])}")
    for t in out["top_tracks"][:5]:
        print(f"  {t['streams']:>13,}  {t['title'][:60]}  (peak {t['peak_date']})")
