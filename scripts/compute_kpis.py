#!/usr/bin/env python3
"""
Phase 3 — KPI Engine
=====================
Reads today's harvest snapshot and the most recent previous snapshot,
computes all 10 KPIs per artist with deltas, and writes:

  data/snapshots/{date}-kpis.json  — full KPI record (consumed by generate_news.py)
  data/snapshot.json               — compact form matched to src/data/types.ts (frontend)
  data/dashboard.json              — same artists + news slot for run_pipeline.py

KPI formulas are implemented exactly per skill/references/kpi-formulas.md.

Usage:
    .venv/bin/python scripts/compute_kpis.py
    .venv/bin/python scripts/compute_kpis.py --snapshot data/snapshots/2026-04-05.json
    .venv/bin/python scripts/compute_kpis.py --snapshot data/snapshots/2026-04-05.json \
                                              --prev     data/snapshots/2026-04-04.json
    .venv/bin/python scripts/compute_kpis.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT          = Path(__file__).parent.parent
SNAPSHOTS_DIR = ROOT / "data" / "snapshots"
TODAY         = date.today().isoformat()

log = logging.getLogger(__name__)


# ── KPI metadata ──────────────────────────────────────────────────────────────

KPI_META: dict[int, dict] = {
    1:  {"name": "Total Social Reach",         "unit": "followers",   "higher_is_better": True},
    2:  {"name": "Social Reach Velocity",      "unit": "%",           "higher_is_better": True},
    3:  {"name": "Engagement Rate",            "unit": "%",           "higher_is_better": True},
    4:  {"name": "Spotify Monthly Listeners",  "unit": "listeners",   "higher_is_better": True},
    5:  {"name": "Spotify Listener Trend",     "unit": "%",           "higher_is_better": True},
    6:  {"name": "Content Velocity",           "unit": "posts/wk",    "higher_is_better": True},
    7:  {"name": "Platform Diversity Score",   "unit": "ratio",       "higher_is_better": True},
    8:  {"name": "YouTube Weekly Velocity",    "unit": "views/wk",    "higher_is_better": True},
    9:  {"name": "Latest Release Recency",     "unit": "days",        "higher_is_better": False},
    10: {"name": "News & Press Mentions",      "unit": "articles",    "higher_is_better": True},
    11: {"name": "Apple Music Catalog Activity","unit": "releases/90d","higher_is_better": True},
}

# ── Benchmark look-ups (spec §kpi-formulas.md) ────────────────────────────────

def _reach_tier(n: float | None) -> str | None:
    """KPI 1 tier: Mega / Major / Rising / Emerging."""
    if n is None:
        return None
    if n > 50_000_000:  return "mega"
    if n >= 10_000_000: return "major"
    if n >= 1_000_000:  return "rising"
    return "emerging"


def _spotify_tier(n: float | None) -> str | None:
    """KPI 4 tier: Global Star / Regional Power / Strong / Growing / Niche."""
    if n is None:
        return None
    if n > 50_000_000:  return "Global Star"
    if n >= 20_000_000: return "Regional Power"
    if n >= 5_000_000:  return "Strong"
    if n >= 1_000_000:  return "Growing"
    return "Niche"


def _engagement_tier(r: float | None) -> str | None:
    """KPI 3 tier: Excellent / Good / Average / Low."""
    if r is None:
        return None
    if r > 3.5: return "Excellent"
    if r >= 1.5: return "Good"
    if r >= 0.5: return "Average"
    return "Low"


def _content_tier(v: float | None) -> str | None:
    """KPI 6 benchmark: Hyperactive / Active / Moderate / Low / Silent."""
    if v is None:
        return None
    if v > 14: return "Hyperactive"
    if v >= 7: return "Active"
    if v >= 3: return "Moderate"
    if v >= 1: return "Low"
    return "Silent"


def _diversity_tier(r: float | None) -> str | None:
    """KPI 7 risk tier."""
    if r is None:
        return None
    if r >= 1.0:  return "Fully diversified"
    if r >= 0.7:  return "Healthy"
    if r >= 0.5:  return "Some gaps"
    return "Platform dependency risk"


def _recency_flag(days: float | None) -> str | None:
    """KPI 9 flag: Fresh / Recent / Aging / Overdue / Dark."""
    if days is None:
        return None
    if days <= 14:  return "fresh"
    if days <= 60:  return "recent"
    if days <= 120: return "aging"
    if days <= 180: return "overdue"
    return "dark"


def _apple_music_tier(n: float | None) -> str | None:
    """KPI 11 tier: Apple Music Catalog Activity (releases in last 90 days)."""
    if n is None:
        return None
    if n >= 5: return "Hyperactive"
    if n >= 3: return "Active"
    if n >= 1: return "Moderate"
    return "Dormant"


def _press_tier(n: float | None) -> str | None:
    """KPI 10 benchmark: Trending / Visible / Moderate / Quiet / Off-radar."""
    if n is None:
        return None
    if n > 20:  return "Trending"
    if n >= 10: return "Visible"
    if n >= 5:  return "Moderate"
    if n >= 1:  return "Quiet"
    return "Off-radar"


def _velocity_alert(pct: float | None) -> str | None:
    """
    KPI 2 & 5 alert based on the VELOCITY VALUE itself (not its own delta).
    ±1% is 'steady' — no alert.
    """
    if pct is None:
        return None
    if pct > 5:    return "breakout"
    if pct > 2:    return "strong"
    if pct >= -1:  return None    # steady
    if pct > -5:   return "declining"
    return "freefall"


def _recency_alert(flag: str | None) -> str | None:
    """KPI 9 alert for dark or overdue releases."""
    if flag in ("dark", "overdue"):
        return flag
    return None


# ── Delta helpers ─────────────────────────────────────────────────────────────

def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


def trend_label(delta_pct: float | None) -> str:
    """Spec: up = >1%, down = <-1%, flat = between."""
    if delta_pct is None:   return "unknown"
    if delta_pct > 1:       return "up"
    if delta_pct < -1:      return "down"
    return "flat"


# ── KPI constructor ───────────────────────────────────────────────────────────

def make_kpi(
    kpi_id:    int,
    current:   float | None,
    previous:  float | None = None,
    *,
    alert_override: str | None = None,   # caller-supplied alert (KPIs 2, 5, 9)
    benchmark_tier: str | None = None,
    extra:     dict | None = None,
) -> dict[str, Any]:
    meta  = KPI_META[kpi_id]
    d_abs = (current - previous) if (current is not None and previous is not None) else None
    d_pct = pct_change(current, previous)
    t     = trend_label(d_pct)

    result: dict[str, Any] = {
        "kpi_id":          kpi_id,
        "kpi_name":        meta["name"],
        "unit":            meta["unit"],
        "higher_is_better": meta["higher_is_better"],
        "current_value":   current,
        "previous_value":  previous,
        "delta_absolute":  round(d_abs, 2) if d_abs is not None else None,
        "delta_percent":   d_pct,
        "trend":           t,
        "alert":           alert_override,
        "benchmark_tier":  benchmark_tier,
    }
    if extra:
        result.update(extra)
    return result


# ── Reach computation helper (reused for current + previous) ──────────────────

def _total_reach(ig_f, yt_s, tt_f, x_f, fb_l, sp_l) -> float | None:
    """
    KPI 1 formula: sum all non-null platform counts.
    Returns None only if every component is None.
    """
    parts = [ig_f, yt_s, tt_f, x_f, fb_l, sp_l]
    available = [v for v in parts if v is not None]
    return float(sum(available)) if available else None


def _video_momentum(videos: list[dict]) -> float | None:
    """KPI 8: average views across up to 3 recent videos."""
    views = [v.get("views") for v in videos if v.get("views") is not None]
    return round(sum(views) / len(views)) if views else None


# ── Per-artist KPI computation ────────────────────────────────────────────────

def compute_artist_kpis(
    artist_data:  dict[str, Any],
    prev_artist:  dict[str, Any] | None,
    today_str:    str,
    roster_entry: dict | None = None,
) -> list[dict]:
    """
    Compute all 10 KPIs for one artist.
    prev_artist — yesterday's HARVEST snapshot for this artist (may be None on baseline run).
    roster_entry — from roster.json, used for KPI 7 account count.
    """
    p = artist_data.get("platforms", {})

    def plat(key: str) -> dict:
        return p.get(key) or {}

    sp    = plat("spotify")
    yt    = plat("youtube")
    ig    = plat("instagram")
    tt    = plat("tiktok")
    fb    = plat("facebook")
    x     = plat("x")
    am    = plat("apple_music")
    press = artist_data.get("press_mentions") or {}

    # ── Previous platform data ────────────────────────────────────────────────
    def prev_plat(key: str) -> dict:
        if not prev_artist:
            return {}
        return prev_artist.get("platforms", {}).get(key) or {}

    prev_sp = prev_plat("spotify")
    prev_yt = prev_plat("youtube")
    prev_ig = prev_plat("instagram")
    prev_tt = prev_plat("tiktok")
    prev_x  = prev_plat("x")
    prev_fb = prev_plat("facebook")
    prev_pr = (prev_artist or {}).get("press_mentions") or {}

    # ── Raw platform values ───────────────────────────────────────────────────
    ig_followers  = ig.get("followers")
    yt_subs       = yt.get("subscribers")
    tt_followers  = tt.get("followers")
    x_followers   = x.get("followers")
    fb_likes      = fb.get("page_likes") or fb.get("followers")
    sp_listeners  = sp.get("monthly_listeners")

    ig_posts  = ig.get("recent_posts", []) or []
    yt_videos = yt.get("recent_videos", []) or []
    tt_videos = tt.get("recent_videos", []) or []

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 1: Total Social Reach
    #   formula: ig.followers + yt.subscribers + tt.followers + x.followers
    #            + fb.page_likes + spotify.monthly_listeners
    # ─────────────────────────────────────────────────────────────────────────
    total_reach = _total_reach(ig_followers, yt_subs, tt_followers,
                               x_followers, fb_likes, sp_listeners)

    # Previous reach — use same formula over previous platform data
    prev_reach = _total_reach(
        prev_ig.get("followers"),
        prev_yt.get("subscribers"),
        prev_tt.get("followers"),
        prev_x.get("followers"),
        prev_fb.get("page_likes") or prev_fb.get("followers"),
        prev_sp.get("monthly_listeners"),
    )

    tier = _reach_tier(total_reach)
    kpi1 = make_kpi(1, total_reach, prev_reach,
                    benchmark_tier=tier,
                    extra={
                        "components": {
                            "instagram":          ig_followers,
                            "youtube":            yt_subs,
                            "tiktok":             tt_followers,
                            "x":                  x_followers,
                            "facebook":           fb_likes,
                            "spotify_listeners":  sp_listeners,
                        },
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 2: Social Reach Velocity
    #   formula: ((current_reach - previous_reach) / previous_reach) * 100
    #   alert: based on the VELOCITY VALUE, not its own delta
    # ─────────────────────────────────────────────────────────────────────────
    velocity_pct = pct_change(total_reach, prev_reach)

    kpi2 = make_kpi(2, velocity_pct, None,    # no "previous velocity" on daily run
                    alert_override=_velocity_alert(velocity_pct),
                    benchmark_tier=None,
                    extra={"reach_current": total_reach, "reach_previous": prev_reach})

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 3: Engagement Rate
    #   formula: (sum likes+comments across last 10 posts) / total_reach * 100
    #   denominator: all social followers (same as KPI 1)
    #   numerator priority: ig likes+comments, then yt/tt views as fallback
    # ─────────────────────────────────────────────────────────────────────────
    ig_eng = sum((p.get("likes") or 0) + (p.get("comments") or 0) for p in ig_posts)
    yt_eng = sum(v.get("views") or 0 for v in yt_videos)
    tt_eng = sum(v.get("views") or 0 for v in tt_videos)

    # Use ig likes+comments when available; fall back to video views
    if ig_eng > 0:
        total_engagement = ig_eng
        eng_source = "ig_likes_comments"
    elif yt_eng + tt_eng > 0:
        # Views are impressions, not pure engagement — mark as proxy
        total_engagement = yt_eng + tt_eng
        eng_source = "yt_tt_views_proxy"
    else:
        total_engagement = 0
        eng_source = "no_data"

    engagement_rate: float | None = None
    if total_reach and total_reach > 0 and total_engagement > 0:
        engagement_rate = round((total_engagement / total_reach) * 100, 4)

    eng_tier = _engagement_tier(engagement_rate)
    kpi3 = make_kpi(3, engagement_rate, None,
                    benchmark_tier=eng_tier,
                    extra={
                        "total_engagement_sampled": total_engagement or None,
                        "engagement_source":        eng_source,
                        "ig_likes_comments":        ig_eng or None,
                        "yt_tt_views":              (yt_eng + tt_eng) or None,
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 4: Spotify Monthly Listeners
    #   direct value; benchmark tiers from spec
    # ─────────────────────────────────────────────────────────────────────────
    sp_current  = sp.get("monthly_listeners")
    sp_previous = prev_sp.get("monthly_listeners")

    kpi4 = make_kpi(4, sp_current, sp_previous,
                    benchmark_tier=_spotify_tier(sp_current))

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 5: Spotify Listener Trend
    #   formula: ((current - previous) / previous) * 100
    #   current_value IS the trend pct; alert based on that value
    # ─────────────────────────────────────────────────────────────────────────
    sp_trend_pct = pct_change(sp_current, sp_previous)

    kpi5 = make_kpi(5, sp_trend_pct, None,
                    alert_override=_velocity_alert(sp_trend_pct),
                    extra={
                        "spotify_current":  sp_current,
                        "spotify_previous": sp_previous,
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 6: Content Velocity
    #   formula: count(posts published in last 7 days across all platforms)
    #   Note: harvest captures recent_posts / recent_videos (~last 7 days)
    # ─────────────────────────────────────────────────────────────────────────
    ig_recent   = len(ig_posts)
    yt_recent   = len(yt_videos)
    tt_recent   = len(tt_videos)
    cv_current  = float(ig_recent + yt_recent + tt_recent) if (ig_recent + yt_recent + tt_recent) > 0 else None

    # Previous content velocity from prev harvest
    prev_cv = None
    if prev_artist:
        prev_ig_posts  = len((prev_ig.get("recent_posts") or []))
        prev_yt_videos = len((prev_yt.get("recent_videos") or []))
        prev_tt_videos = len((prev_tt.get("recent_videos") or []))
        prev_cv_val    = prev_ig_posts + prev_yt_videos + prev_tt_videos
        prev_cv = float(prev_cv_val) if prev_cv_val > 0 else None

    cv_tier = _content_tier(cv_current)
    kpi6 = make_kpi(6, cv_current, prev_cv,
                    benchmark_tier=cv_tier,
                    extra={
                        "ig_posts":    ig_recent,
                        "yt_videos":   yt_recent,
                        "tt_videos":   tt_recent,
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 7: Platform Diversity Score
    #   formula: active_platforms / total_platforms
    #   total_platforms: count of platforms with a non-null URL in roster
    #   active_platforms: platforms where harvest returned fetch_status == "ok"
    # ─────────────────────────────────────────────────────────────────────────
    SOCIAL_PLATFORMS = ("instagram", "youtube", "tiktok", "x", "spotify",
                        "facebook", "apple_music")

    # "has account" = non-null URL in roster social_links
    roster_links = (roster_entry or {}).get("social_links") or {}
    total_platforms = sum(
        1 for k in SOCIAL_PLATFORMS
        if roster_links.get(k)
    )
    # Fallback: use harvest presence if roster data missing
    if total_platforms == 0:
        total_platforms = sum(
            1 for k in SOCIAL_PLATFORMS
            if p.get(k, {}).get("fetch_status") not in (None, "no_url")
        )

    # "active" = harvest returned ok status (successfully fetched real data)
    active_platforms = sum(
        1 for k in SOCIAL_PLATFORMS
        if p.get(k, {}).get("fetch_status") == "ok"
    )

    diversity = round(active_platforms / total_platforms, 3) if total_platforms > 0 else None

    kpi7 = make_kpi(7, diversity, None,
                    benchmark_tier=_diversity_tier(diversity),
                    extra={
                        "active_platforms": active_platforms,
                        "total_platforms":  total_platforms,
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 8: YouTube Weekly Velocity
    #   formula: average views across the 5 most recent YouTube videos
    #   (renamed from "Video View Momentum"; previously also pulled TikTok)
    # ─────────────────────────────────────────────────────────────────────────
    yt_only_curr = _video_momentum(yt_videos[:5])
    yt_only_prev = None
    if prev_artist:
        yt_only_prev = _video_momentum((prev_yt.get("recent_videos") or [])[:5])

    # Fallback to TikTok views if no YouTube data exists for the artist.
    if yt_only_curr is None and tt_videos:
        yt_only_curr = _video_momentum(tt_videos[:5])
    if yt_only_prev is None and prev_artist:
        yt_only_prev = _video_momentum((prev_tt.get("recent_videos") or [])[:5])

    kpi8 = make_kpi(8, float(yt_only_curr) if yt_only_curr else None,
                    float(yt_only_prev) if yt_only_prev else None,
                    extra={
                        "videos_sampled": len([v for v in yt_videos[:5] if v.get("views")]),
                        "source": "youtube" if yt_only_curr is not None and yt_videos else "tiktok",
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 9: Latest Release Recency
    #   formula: today - max(spotify_release_date, apple_music_release_date)
    #   alerts: "dark" (>180 days), "overdue" (121-180 days)
    # ─────────────────────────────────────────────────────────────────────────
    # Cross-check Spotify and Apple Music — use whichever has the more recent
    # release date. Apple's iTunes Search often surfaces singles/remixes a few
    # days before they appear in Spotify's exposed metadata.
    release_date_str: str | None = None
    release_title: str | None = None
    release_source: str | None = None

    candidates: list[tuple[str, str | None, str]] = []
    sp_release = sp.get("latest_release") or {}
    if sp_release.get("date"):
        candidates.append((sp_release["date"], sp_release.get("title"), "spotify"))
    am_release = am.get("latest_release") or {}
    if am_release.get("date"):
        candidates.append((am_release["date"], am_release.get("title"), "apple_music"))

    if candidates:
        # Pick the most recent date (descending lexical sort works for ISO YYYY-MM-DD)
        candidates.sort(key=lambda c: c[0], reverse=True)
        release_date_str, release_title, release_source = candidates[0]

    recency_days: float | None = None
    if release_date_str:
        try:
            rd      = date.fromisoformat(release_date_str[:10])
            today_d = date.fromisoformat(today_str[:10])
            recency_days = float(max(0, (today_d - rd).days))
        except ValueError:
            pass

    rec_flag  = _recency_flag(recency_days)
    rec_alert = _recency_alert(rec_flag)

    # Previous recency: one day older than today's value (if value exists)
    prev_recency = float(recency_days + 1) if recency_days is not None else None

    kpi9 = make_kpi(9, recency_days, prev_recency,
                    alert_override=rec_alert,
                    benchmark_tier=rec_flag,
                    extra={
                        "release_title":  release_title,
                        "release_date":   release_date_str,
                        "release_source": release_source,
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 10: News & Press Mentions
    #   formula: count(unique articles in past 7 days)
    # ─────────────────────────────────────────────────────────────────────────
    mention_count    = press.get("count")
    prev_mention_count = float(prev_pr.get("count")) if prev_pr.get("count") is not None else None

    press_tier = _press_tier(mention_count)
    kpi10 = make_kpi(10,
                     float(mention_count) if mention_count is not None else None,
                     prev_mention_count,
                     benchmark_tier=press_tier,
                     extra={"headlines": press.get("headlines", [])})

    # ─────────────────────────────────────────────────────────────────────────
    # KPI 11: Apple Music Catalog Activity
    #   formula: count of releases (album/EP/single) on iTunes in past 90 days
    #   tiers:   Hyperactive 5+, Active 3-4, Moderate 1-2, Dormant 0
    # ─────────────────────────────────────────────────────────────────────────
    am_recent      = am.get("recent_releases_90d")
    prev_am        = prev_plat("apple_music")
    prev_am_recent = prev_am.get("recent_releases_90d")

    kpi11_curr = float(am_recent)      if am_recent      is not None else None
    kpi11_prev = float(prev_am_recent) if prev_am_recent is not None else None

    kpi11 = make_kpi(11, kpi11_curr, kpi11_prev,
                     benchmark_tier=_apple_music_tier(am_recent),
                     extra={
                         "total_albums":   am.get("total_albums"),
                         "primary_genre": am.get("primary_genre"),
                         "latest_release": am.get("latest_release"),
                         "top_songs":      am.get("top_songs", [])[:5],
                     })

    kpis = [kpi1, kpi2, kpi3, kpi4, kpi5, kpi6, kpi7, kpi8, kpi9, kpi10, kpi11]

    # ── Status-aware gating ──────────────────────────────────────────────────
    # Legacy estates (e.g., Vicente Fernández) have no live activity to track —
    # blank out velocity/engagement/content/diversity KPIs so the dashboard
    # doesn't show misleading "freefall" alerts. Catalog KPIs (1, 4, 5, 8, 9, 10)
    # remain meaningful: posthumous releases, Spotify catalog momentum, etc.
    if (roster_entry or {}).get("status") == "legacy_estate":
        for k in kpis:
            if k["kpi_id"] in {2, 3, 6, 7}:
                k["current_value"]  = None
                k["previous_value"] = None
                k["delta_absolute"] = None
                k["delta_percent"]  = None
                k["trend"]          = "unknown"
                k["alert"]          = "legacy_estate"

    return kpis


# ── Roster lookup ─────────────────────────────────────────────────────────────

def load_roster(roster_path: Path) -> dict[str, dict]:
    """Return {slug: artist_dict} from roster.json."""
    if not roster_path.exists():
        return {}
    data = json.loads(roster_path.read_text())
    return {a["slug"]: a for a in data.get("artists", [])}


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 — KPI computation")
    parser.add_argument("--snapshot",      type=Path, default=None,
                        help="Harvest snapshot to process (default: today's)")
    parser.add_argument("--prev",          type=Path, default=None,
                        help="Previous harvest snapshot for delta computation")
    parser.add_argument("--roster",        type=Path,
                        default=ROOT / "data" / "roster.json")
    parser.add_argument("--output",        type=Path, default=None,
                        help="KPI output path (default: snapshots/{today}-kpis.json)")
    parser.add_argument("--dashboard-out", type=Path,
                        default=ROOT / "data" / "dashboard.json")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Locate today's harvest snapshot ──────────────────────────────────────
    snapshot_path = args.snapshot or SNAPSHOTS_DIR / f"{TODAY}.json"
    if not snapshot_path.exists():
        log.error("Harvest snapshot not found: %s", snapshot_path)
        log.error("  Run: python scripts/harvest_social.py first")
        return 1

    snapshot      = json.loads(snapshot_path.read_text())
    snapshot_date = snapshot.get("harvest_date", TODAY)
    log.info("Snapshot: %s  (%d artists)", snapshot_path, len(snapshot["artists"]))

    # ── Locate previous harvest snapshot ─────────────────────────────────────
    prev_path: Path | None = None
    if args.prev:
        prev_path = args.prev
    else:
        # Auto-detect: sorted glob of YYYY-MM-DD.json, exclude today's and kpi files
        candidates = sorted(
            p for p in SNAPSHOTS_DIR.glob("????-??-??.json")
            if "kpis" not in p.name and p != snapshot_path
        )
        prev_path = candidates[-1] if candidates else None

    prev_by_slug: dict[str, dict] = {}
    prev_date: str | None = None
    if prev_path and prev_path.exists():
        prev_snap    = json.loads(prev_path.read_text())
        prev_by_slug = {a["artist_slug"]: a for a in prev_snap.get("artists", [])}
        prev_date    = prev_snap.get("harvest_date", prev_path.stem)
        log.info("Previous:  %s  (%d artists)  [delta baseline]", prev_path, len(prev_by_slug))
    else:
        log.info("No previous snapshot found — baseline run (no deltas)")

    # ── Load roster for KPI 7 account-existence check ────────────────────────
    roster = load_roster(args.roster)

    # ── Compute KPIs ─────────────────────────────────────────────────────────
    kpi_results: list[dict] = []

    for artist_data in snapshot["artists"]:
        slug = artist_data["artist_slug"]
        name = artist_data["artist_name"]
        prev = prev_by_slug.get(slug)

        log.debug("  KPIs: %s", name)
        kpis = compute_artist_kpis(
            artist_data,
            prev,
            snapshot_date,
            roster_entry=roster.get(slug),
        )

        # Top-level tier from KPI 1 benchmark (lowercase for frontend)
        kpi1 = next(k for k in kpis if k["kpi_id"] == 1)
        tier = (kpi1.get("benchmark_tier") or "emerging").lower()

        roster_entry = roster.get(slug, {})
        kpi_results.append({
            "artist_slug":   slug,
            "artist_name":   name,
            "tier":          tier,
            "image_url":     roster_entry.get("image_url"),
            "image_local":   roster_entry.get("image_local_path"),
            "profile_url":   roster_entry.get("profile_url"),
            "social_links":  roster_entry.get("social_links", {}),
            # Curated metadata — passed through so the news engine and
            # frontend can branch on label/status without re-reading roster.json.
            "country":       roster_entry.get("country"),
            "label_status":  roster_entry.get("label_status"),
            "status":        roster_entry.get("status"),
            "priority":      roster_entry.get("priority"),
            "genre_tags":    roster_entry.get("genre_tags"),
            "snapshot_date": snapshot_date,
            "kpis":          kpis,
        })

    # ── Write KPI snapshot ───────────────────────────────────────────────────
    output_path = args.output or (SNAPSHOTS_DIR / f"{snapshot_date}-kpis.json")
    kpi_snapshot = {
        "snapshot_date":          snapshot_date,
        "previous_snapshot_date": prev_date,
        "generated_at":           datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "artist_count":           len(kpi_results),
        "artists":                kpi_results,
    }
    output_path.write_text(json.dumps(kpi_snapshot, indent=2, ensure_ascii=False))
    log.info("KPI snapshot → %s", output_path)

    # ── Write dashboard.json (rich format for generate_news.py) ──────────────
    dashboard = {
        "snapshot_date":          snapshot_date,
        "previous_snapshot_date": prev_date,
        "generated_at":           datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "artist_count":           len(kpi_results),
        "artists":                kpi_results,
    }
    args.dashboard_out.parent.mkdir(parents=True, exist_ok=True)
    args.dashboard_out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
    log.info("Dashboard  → %s", args.dashboard_out)

    # ── Write snapshot.json (compact form for React frontend) ────────────────
    frontend_snapshot = {
        "snapshot_date":          snapshot_date,
        "previous_snapshot_date": prev_date or snapshot_date,
        "artists": [
            {
                "artist_slug":  r["artist_slug"],
                "artist_name":  r["artist_name"],
                "tier":         r["tier"],
                # Curated metadata — drives frontend filtering, badges, country pills
                "country":      r.get("country"),
                "label_status": r.get("label_status"),
                "status":       r.get("status"),
                "priority":     r.get("priority"),
                "genre_tags":   r.get("genre_tags"),
                "kpis":         r["kpis"],
            }
            for r in kpi_results
        ],
    }
    snapshot_out = ROOT / "data" / "snapshot.json"
    snapshot_out.write_text(json.dumps(frontend_snapshot, indent=2, ensure_ascii=False))
    log.info("Frontend   → %s", snapshot_out)

    # ── Summary ──────────────────────────────────────────────────────────────
    def _count(kpi_id: int) -> int:
        return sum(1 for r in kpi_results
                   if r["kpis"][kpi_id - 1]["current_value"] is not None)

    def _with_deltas(kpi_id: int) -> int:
        return sum(1 for r in kpi_results
                   if r["kpis"][kpi_id - 1]["delta_percent"] is not None)

    n = len(kpi_results)
    print(f"\n✓  {n} artists  →  {output_path}")
    print(f"   {'KPI':<35s}  {'populated':>9s}  {'with delta':>10s}")
    print(f"   {'─'*35}  {'─'*9}  {'─'*10}")
    for kid, meta in KPI_META.items():
        print(f"   {meta['name']:<35s}  {_count(kid):>5d}/{n:<3d}  {_with_deltas(kid):>5d}/{n:<3d}")

    if prev_date:
        print(f"\n   Deltas vs {prev_date}")
    else:
        print(f"\n   Baseline run — no deltas (run again tomorrow for day-over-day)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
