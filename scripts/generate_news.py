#!/usr/bin/env python3
"""
Phase 4 — News Desk
====================
Reads the KPI snapshot produced by compute_kpis.py, scores every detected change
against the newsworthiness rubric in skill/references/news-scoring.md, selects the
Top 15 items, and writes editorial headlines + blurbs via the Anthropic API.

Signal types and base scores (from news-scoring.md):
  milestone                 10  (×1.5 if round number: 10M/50M/100M)
  new_release                9
  chart_movement             9  (not auto-detected — requires external feed)
  rapid_follower_surge       7  (×1.1 per % point above 2% threshold)
  engagement_anomaly         7
  pr_event / press_buzz      7  (×1.3 if mainstream press)
  platform_silence           5  (×1.3 if previously high-frequency poster)
  platform_silence_breaking  5
  declining_metrics          5  (×1.1 per consecutive snapshot of decline)
  viral_spike / video_spike  8  (log-scaled on absolute or delta views)
  spotify_surge              8
  spotify_decline            5  (treated as declining_metrics variant)

Outputs:
  data/news/{today}.json        — dated archive
  data/news.json                — latest (consumed by React frontend)

Usage:
    .venv/bin/python scripts/generate_news.py
    .venv/bin/python scripts/generate_news.py --kpis data/snapshots/2026-04-05-kpis.json
    .venv/bin/python scripts/generate_news.py --no-ai
    .venv/bin/python scripts/generate_news.py --top 15
    .venv/bin/python scripts/generate_news.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from datetime import date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT          = Path(__file__).parent.parent
SNAPSHOTS_DIR = ROOT / "data" / "snapshots"
NEWS_DIR      = ROOT / "data" / "news"
TODAY         = date.today().isoformat()

log = logging.getLogger(__name__)


# ── Formatters ─────────────────────────────────────────────────────────────────

def _fmt_n(n: float | int) -> str:
    if n >= 1_000_000_000: return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:     return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:         return f"{n / 1_000:.0f}K"
    return str(int(n))


# ── KPI helpers ────────────────────────────────────────────────────────────────

def _kpi(kpis: list[dict], kpi_id: int) -> dict:
    """Return a KPI entry by id, or an empty dict if absent."""
    return next((k for k in kpis if k["kpi_id"] == kpi_id), {})


def _kpi_impact_entry(kpi: dict) -> dict:
    """Build a kpi_impact record from a KPI entry (matches NewsKpiImpact type)."""
    trend = kpi.get("trend", "unknown")
    direction: str
    if trend in ("up", "down", "flat"):
        direction = trend
    else:
        d = kpi.get("delta_absolute")
        direction = "up" if (d and d > 0) else ("down" if (d and d < 0) else "flat")
    return {
        "kpi_id":         kpi.get("kpi_id"),
        "kpi_name":       kpi.get("kpi_name", ""),
        "current_value":  kpi.get("current_value"),
        "benchmark_tier": kpi.get("benchmark_tier"),
        "delta_absolute": kpi.get("delta_absolute"),
        "delta_percent":  kpi.get("delta_percent"),
        "direction":      direction,
    }


# ── Signal detectors ──────────────────────────────────────────────────────────
# Every detector returns a list of raw signal dicts with these required fields:
#   signal_type, base_score, artist_slug, artist_name, kpi_ids, description, data
#
# Optional metadata added later: tier_rank, total_reach, image_url

MILESTONE_THRESHOLDS = [
    100_000_000, 75_000_000, 50_000_000, 25_000_000,
    20_000_000,  15_000_000, 10_000_000,  5_000_000,
    1_000_000,
]
_ROUND_MILESTONES = {10_000_000, 25_000_000, 50_000_000, 100_000_000}


def detect_milestones(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPIs 1 & 4: value just crossed a threshold (requires previous snapshot)."""
    signals: list[dict] = []
    for kpi_id in (1, 4):
        kpi = _kpi(kpis, kpi_id)
        curr = kpi.get("current_value")
        prev = kpi.get("previous_value")
        if curr is None or prev is None:
            continue
        for threshold in MILESTONE_THRESHOLDS:
            if prev < threshold <= curr:
                mult = 1.5 if threshold in _ROUND_MILESTONES else 1.0
                signals.append({
                    "signal_type":  "milestone",
                    "base_score":   10 * mult,
                    "artist_slug":  slug,
                    "artist_name":  name,
                    "kpi_ids":      [kpi_id],
                    "description":  (
                        f"{name} crossed {_fmt_n(threshold)} "
                        f"{'total social reach' if kpi_id == 1 else 'Spotify monthly listeners'}"
                    ),
                    "data": {
                        "kpi_id":    kpi_id,
                        "kpi_name":  kpi.get("kpi_name"),
                        "threshold": threshold,
                        "current":   curr,
                        "previous":  prev,
                        "delta":     kpi.get("delta_absolute"),
                    },
                })
    return signals


def detect_follower_surge(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 2: social reach velocity > 2% — rapid_follower_surge.
    Score: 7 base × 1.1^(velocity - 2) per rubric.

    Velocity values above 1000% indicate a data discontinuity (e.g. yesterday's
    snapshot had a null/zero baseline because we lacked a social URL, and today's
    has real data after the URL was added). Reporting these as "surges" would
    mislead — skip the signal in that case.

    The 1.1^(vel-2) term also overflows Python floats for very large velocities,
    so we clamp the exponent regardless as a safety net.
    """
    kpi2 = _kpi(kpis, 2)
    vel  = kpi2.get("current_value")
    if vel is None or vel <= 2.0:
        return []
    if vel > 1000.0:
        # Data discontinuity, not news
        return []
    # 1.1^98 ≈ 12.5K (×7 ≈ 87K, capped to 15 below) — well below float overflow.
    score = 7.0 * (1.1 ** min(vel - 2.0, 100.0))
    return [{
        "signal_type":  "rapid_follower_surge",
        "base_score":   round(min(score, 15.0), 2),
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [2],
        "description":  f"{name} grew total social reach by {vel:.1f}% since last snapshot",
        "data": {
            "velocity_pct":  vel,
            "reach_current": kpi2.get("reach_current"),
            "delta_absolute":_kpi(kpis, 1).get("delta_absolute"),
        },
    }]


def detect_spotify_movement(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 5 (Spotify listener trend) and KPI 4 (Spotify monthly listeners).
    Surge: trend ≥ +10% → score 8 (viral_spike category).
    Decline: trend ≤ -10% → score 5 (declining_metrics category)."""
    kpi5 = _kpi(kpis, 5)
    kpi4 = _kpi(kpis, 4)
    trend_pct = kpi5.get("current_value")
    if trend_pct is None or abs(trend_pct) < 10.0:
        return []
    curr_listeners = kpi4.get("current_value")
    prev_listeners = kpi4.get("previous_value")
    delta = (curr_listeners - prev_listeners
             if curr_listeners is not None and prev_listeners is not None
             else None)
    is_surge = trend_pct > 0
    return [{
        "signal_type":  "spotify_surge" if is_surge else "declining_metrics",
        "base_score":   8.0 if is_surge else 5.0,
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [5, 4],
        "description":  (
            f"{name} Spotify listeners "
            f"{'surged' if is_surge else 'dropped'} {abs(trend_pct):.1f}%"
            + (f" — now {_fmt_n(curr_listeners)}" if curr_listeners else "")
        ),
        "data": {
            "trend_pct":     trend_pct,
            "current":       curr_listeners,
            "previous":      prev_listeners,
            "delta":         delta,
        },
    }]


def detect_fresh_release(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 9: latest release within 14 days — new_release, score 9."""
    kpi9    = _kpi(kpis, 9)
    days    = kpi9.get("current_value")
    title   = kpi9.get("release_title")
    rel_date= kpi9.get("release_date")
    if days is None or days > 14:
        return []
    desc = f"{name} released"
    if title:
        desc += f' "{title}"'
    desc += f" {int(days)} day(s) ago"
    return [{
        "signal_type":  "new_release",
        "base_score":   9.0,
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [9],
        "description":  desc,
        "data": {
            "days_since_release": int(days),
            "release_title":      title,
            "release_date":       rel_date,
        },
    }]


def detect_video_spike(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 8: Video View Momentum.

    Two modes:
      - With prev data: score based on how much current exceeds previous.
      - Baseline (no prev): log-scaled score on absolute average view count.
        Only fires if avg ≥ 500K to avoid low-reach noise.

    Maps to 'viral_spike' (base 8) when >> baseline, else 'video_momentum' (max 7.9).
    """
    kpi8 = _kpi(kpis, 8)
    curr = kpi8.get("current_value")
    prev = kpi8.get("previous_value")
    if curr is None or curr < 500_000:
        return []

    video_count = kpi8.get("video_count_sampled", 3)

    if prev is not None and prev > 0:
        ratio = curr / prev
        if ratio >= 5.0:
            # Viral spike: 5× or more above own baseline
            score = 8.0 * (1.2 ** math.log10(ratio))
            signal_type = "viral_spike"
        elif ratio >= 1.5:
            score = 5.0 + 3.0 * math.log10(ratio)
            signal_type = "video_momentum"
        else:
            return []  # not newsworthy if barely changed
    else:
        # Baseline run: score on absolute magnitude
        score       = min(7.9, 4.0 + math.log10(curr / 100_000))
        signal_type = "video_momentum"

    return [{
        "signal_type":  signal_type,
        "base_score":   round(score, 2),
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [8],
        "description":  (
            f"{name} averaging {_fmt_n(int(curr))} views "
            f"per recent video (n={video_count})"
            + (f" — up {(curr/prev - 1)*100:.0f}% from prior period" if prev else "")
        ),
        "data": {
            "avg_views":     curr,
            "prev_avg_views":prev,
            "video_count":   video_count,
        },
    }]


def detect_press_buzz(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 10: News & Press Mentions.

    Threshold: ≥ 20 articles triggers a pr_event signal.
    Score: 3.5 + log10(count), capped at 7.0 per rubric.
    Multiplier ×1.3 if headlines suggest mainstream press (Billboard, NYT, etc.)."""
    kpi10     = _kpi(kpis, 10)
    count     = kpi10.get("current_value")
    headlines = kpi10.get("headlines") or []
    if count is None or count < 20:
        return []

    score = min(7.0, 3.5 + math.log10(count))

    # ×1.3 multiplier for mainstream press mentions
    mainstream_outlets = {"billboard", "rolling stone", "nyt", "new york times",
                          "variety", "pitchfork", "the guardian", "npr", "bbc",
                          "forbes", "time", "people", "usa today", "ap ", "reuters",
                          "associated press"}
    headlines_lower = " ".join(headlines).lower()
    if any(o in headlines_lower for o in mainstream_outlets):
        score = min(7.0, score * 1.3)

    return [{
        "signal_type":  "pr_event",
        "base_score":   round(score, 2),
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [10],
        "description":  f"{name} generated {int(count)} press mentions this week",
        "data": {
            "count":     int(count),
            "prev":      kpi10.get("previous_value"),
            "headlines": headlines[:5],
        },
    }]


def detect_platform_silence(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 6: content velocity = 0 → platform_silence (score 5).
    Multiplier ×1.3 if the artist was previously active (prev > 3 posts/wk)."""
    kpi6 = _kpi(kpis, 6)
    curr = kpi6.get("current_value")
    prev = kpi6.get("previous_value")
    if curr is None or curr > 0:
        return []
    was_active = prev is not None and prev >= 3
    score      = 5.0 * (1.3 if was_active else 1.0)
    return [{
        "signal_type":  "platform_silence",
        "base_score":   round(score, 2),
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [6, 7],
        "description":  (
            f"{name} posted nothing in the past week"
            + (f" — previously averaging {prev:.0f} posts/wk" if was_active else "")
        ),
        "data": {
            "prev_velocity": prev,
            "diversity":     _kpi(kpis, 7).get("current_value"),
        },
    }]


def detect_silence_breaking(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 6: content velocity was 0, now > 0 → platform_silence_breaking (score 5)."""
    kpi6 = _kpi(kpis, 6)
    curr = kpi6.get("current_value")
    prev = kpi6.get("previous_value")
    if curr is None or curr == 0 or prev is None or prev > 0:
        return []
    return [{
        "signal_type":  "platform_silence_breaking",
        "base_score":   5.0,
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [6],
        "description":  (
            f"{name} returned to posting after a silent period — "
            f"{curr:.0f} posts/wk this snapshot"
        ),
        "data": {"curr_velocity": curr},
    }]


def detect_engagement_anomaly(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPI 3: engagement rate delta > 50% in either direction (score 7)."""
    kpi3     = _kpi(kpis, 3)
    d_pct    = kpi3.get("delta_percent")
    curr_eng = kpi3.get("current_value")
    if d_pct is None or abs(d_pct) < 50.0:
        return []
    is_up  = d_pct > 0
    return [{
        "signal_type":  "engagement_anomaly",
        "base_score":   7.0,
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [3],
        "description":  (
            f"{name} engagement rate "
            f"{'jumped' if is_up else 'dropped'} {abs(d_pct):.1f}%"
            + (f" — now {curr_eng:.2f}%" if curr_eng is not None else "")
        ),
        "data": {
            "delta_pct":     d_pct,
            "curr_rate":     curr_eng,
            "prev_rate":     kpi3.get("previous_value"),
            "benchmark":     kpi3.get("benchmark_tier"),
        },
    }]


def detect_declining_metrics(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """KPIs 1 & 4: sustained decline (trend='down') with delta < -1%.
    Score: 5 × 1.1^(days_declining) — we only have 1 day so base 5 + scaling."""
    signals: list[dict] = []
    for kpi_id, label in ((1, "total social reach"), (4, "Spotify monthly listeners")):
        kpi   = _kpi(kpis, kpi_id)
        d_pct = kpi.get("delta_percent")
        curr  = kpi.get("current_value")
        if d_pct is None or d_pct >= -1.0:
            continue
        # Only flag if decline > 2% (noise filtering)
        if abs(d_pct) < 2.0:
            continue
        score = 5.0 * (1.1 ** (abs(d_pct) - 2.0))
        signals.append({
            "signal_type":  "declining_metrics",
            "base_score":   round(min(score, 8.0), 2),
            "artist_slug":  slug,
            "artist_name":  name,
            "kpi_ids":      [kpi_id],
            "description":  (
                f"{name} {label} dropped {abs(d_pct):.1f}%"
                + (f" — now {_fmt_n(curr)}" if curr else "")
            ),
            "data": {
                "kpi_id":   kpi_id,
                "kpi_name": kpi.get("kpi_name"),
                "d_pct":    d_pct,
                "curr":     curr,
                "prev":     kpi.get("previous_value"),
                "delta":    kpi.get("delta_absolute"),
            },
        })
    return signals


def detect_apple_music_surge(slug: str, name: str, kpis: list[dict]) -> list[dict]:
    """
    KPI 11: Apple Music Catalog Activity surge. Fires when an artist's
    90-day release count jumped meaningfully (delta_absolute ≥ 2 or
    delta_percent ≥ 100% from a non-trivial base). Score 7 — softer than a
    single fresh release but flags an active Apple Music push.
    """
    kpi11 = _kpi(kpis, 11)
    curr  = kpi11.get("current_value")
    delta = kpi11.get("delta_absolute")
    pct   = kpi11.get("delta_percent")
    if curr is None or delta is None:
        return []
    if curr < 2:
        return []
    if not (delta >= 2 or (pct is not None and pct >= 100)):
        return []

    latest = kpi11.get("latest_release") or {}
    desc = f"{name}'s Apple Music output ramped up — {int(curr)} releases in the last 90 days"
    if delta:
        desc += f" (+{int(delta)} vs prior snapshot)"
    if latest.get("title"):
        desc += f'. Most recent: "{latest["title"]}"'
        if latest.get("date"):
            desc += f" ({latest['date']})"
    return [{
        "signal_type":  "apple_music_surge",
        "base_score":   7.0,
        "artist_slug":  slug,
        "artist_name":  name,
        "kpi_ids":      [11],
        "description":  desc,
        "data": {
            "releases_90d": int(curr),
            "delta":        int(delta),
            "delta_pct":    pct,
            "latest_release": latest,
        },
    }]


# ── Score all artists ──────────────────────────────────────────────────────────

def score_artist(entry: dict) -> list[dict]:
    slug  = entry["artist_slug"]
    name  = entry["artist_name"]
    kpis  = entry.get("kpis", [])

    kpi1      = _kpi(kpis, 1)
    reach     = kpi1.get("current_value") or 0
    tier_rank = {"mega": 4, "major": 3, "rising": 2, "emerging": 1}.get(
        entry.get("tier", "emerging"), 1)

    signals: list[dict] = []
    signals += detect_milestones(slug, name, kpis)
    signals += detect_spotify_movement(slug, name, kpis)
    signals += detect_fresh_release(slug, name, kpis)
    signals += detect_apple_music_surge(slug, name, kpis)
    signals += detect_press_buzz(slug, name, kpis)

    # ── Live-activity signals: suppressed for legacy estates ─────────────────
    # An artist marked status=legacy_estate (e.g., Vicente Fernández, deceased)
    # has no live posting activity. Reporting "no posts in 1500 days" or
    # "engagement collapsed" would be journalistically false. Catalog signals
    # (milestones, Spotify trend, new release, press) still fire — those track
    # estate/posthumous activity, which IS newsworthy.
    if entry.get("status") != "legacy_estate":
        signals += detect_follower_surge(slug, name, kpis)
        signals += detect_video_spike(slug, name, kpis)
        signals += detect_platform_silence(slug, name, kpis)
        signals += detect_silence_breaking(slug, name, kpis)
        signals += detect_engagement_anomaly(slug, name, kpis)
        signals += detect_declining_metrics(slug, name, kpis)

    for s in signals:
        s["tier_rank"]   = tier_rank
        s["total_reach"] = reach
        s["image_url"]   = entry.get("image_url")
        # Attach full KPI entries for kpi_impact building later
        s["_kpis"]       = kpis

    return signals


# ── Headline templates (fallback + AI hint) ────────────────────────────────────

def _template_headline(s: dict) -> str:
    st   = s["signal_type"]
    name = s["artist_name"]
    d    = s.get("data", {})

    if st == "milestone":
        threshold = d.get("threshold", 0)
        kpi_label = "total social reach" if d.get("kpi_id") == 1 else "Spotify listeners"
        return f"{name} crosses {_fmt_n(threshold)} {kpi_label}"

    if st == "rapid_follower_surge":
        vel = d.get("velocity_pct", 0)
        return f"{name} surges {vel:.1f}% in total social reach"

    if st == "spotify_surge":
        pct = abs(d.get("trend_pct", 0))
        curr = d.get("current")
        curr_str = f" — now at {_fmt_n(curr)}" if curr else ""
        return f"{name} Spotify listeners climb {pct:.1f}%{curr_str}"

    if st == "declining_metrics":
        pct  = abs(d.get("d_pct", d.get("trend_pct", 0)))
        label = "Spotify listeners" if d.get("kpi_id") == 4 else "social reach"
        return f"{name} {label} decline {pct:.1f}%"

    if st == "new_release":
        days  = d.get("days_since_release", "?")
        title = d.get("release_title")
        if title:
            return f'{name} drops "{title}"'
        return f"{name} drops new music ({days}d ago)"

    if st == "viral_spike":
        views = d.get("avg_views", 0)
        ratio = (views / d["prev_avg_views"]) if d.get("prev_avg_views") else None
        if ratio:
            return f"{name} video performance up {ratio:.0f}× — {_fmt_n(int(views))} avg views"
        return f"{name} videos going viral — {_fmt_n(int(views))} avg views"

    if st == "video_momentum":
        views = d.get("avg_views", 0)
        return f"{name} averaging {_fmt_n(int(views))} views per recent video"

    if st == "pr_event":
        count = d.get("count", 0)
        return f"{name} generates {count} press mentions this week"

    if st == "platform_silence":
        return f"{name} goes dark — zero posts in the past week"

    if st == "platform_silence_breaking":
        vel = d.get("curr_velocity", 0)
        return f"{name} breaks silence — {vel:.0f} posts this week"

    if st == "engagement_anomaly":
        d_pct = d.get("delta_pct", 0)
        direction = "spikes" if d_pct > 0 else "drops"
        return f"{name} engagement rate {direction} {abs(d_pct):.1f}%"

    return s.get("description", name)


def _template_blurb(s: dict) -> str:
    st   = s["signal_type"]
    name = s["artist_name"]
    d    = s.get("data", {})

    if st == "milestone":
        threshold = d.get("threshold", 0)
        kpi_label = ("total social reach" if d.get("kpi_id") == 1
                     else "Spotify monthly listeners")
        delta_str = (f", adding {_fmt_n(abs(int(d['delta'])))} in the past snapshot period"
                     if d.get("delta") else "")
        return (f"{name} has crossed {_fmt_n(threshold)} {kpi_label}{delta_str}. "
                f"This milestone reinforces the artist's standing as one of the roster's "
                f"most-followed acts.")

    if st == "rapid_follower_surge":
        vel   = d.get("velocity_pct", 0)
        reach = d.get("reach_current")
        reach_str = f" Their combined following now stands at {_fmt_n(reach)}." if reach else ""
        return (f"{name}'s combined social following grew {vel:.1f}% since the last snapshot, "
                f"the kind of acceleration that typically signals a viral moment or coordinated "
                f"press push.{reach_str}")

    if st == "spotify_surge":
        pct  = abs(d.get("trend_pct", 0))
        curr = d.get("current")
        delta = d.get("delta")
        curr_str  = f" Their monthly listener count now stands at {_fmt_n(curr)}." if curr else ""
        delta_str = f" That translates to {_fmt_n(abs(int(delta)))} additional listeners." if delta else ""
        return (f"{name}'s Spotify monthly listeners climbed {pct:.1f}% since the prior snapshot.{delta_str}"
                f"{curr_str} The surge is consistent with a release window or playlist placement driving "
                f"new listener acquisition.")

    if st == "declining_metrics":
        pct   = abs(d.get("d_pct", d.get("trend_pct", 0)))
        label = "Spotify monthly listeners" if d.get("kpi_id") == 4 else "total social reach"
        curr  = d.get("curr") or d.get("current")
        delta = d.get("delta")
        curr_str  = f" {_fmt_n(curr)} now." if curr else ""
        delta_str = (f" A loss of {_fmt_n(abs(int(delta)))} on this KPI."
                     if delta and abs(delta) > 0 else "")
        return (f"{name}'s {label} fell {pct:.1f}% in the latest snapshot.{delta_str}{curr_str} "
                f"The team should assess whether this is post-release normalization "
                f"or the beginning of a sustained trend.")

    if st == "new_release":
        days  = d.get("days_since_release", "?")
        title = d.get("release_title")
        title_str = f' "{title}"' if title else " new music"
        return (f"{name} dropped{title_str} {days} day(s) ago. "
                f"Early streaming data over the next 48–72 hours will indicate whether the "
                f"release is gaining meaningful traction on Spotify and YouTube.")

    if st in ("viral_spike", "video_momentum"):
        views = d.get("avg_views", 0)
        prev  = d.get("prev_avg_views")
        prev_str = (f" up from a prior average of {_fmt_n(int(prev))}"
                    if prev and prev > 0 else "")
        return (f"{name}'s recent videos are averaging {_fmt_n(int(views))} views{prev_str}. "
                f"Sustained video performance at this level typically correlates with "
                f"elevated streaming numbers and follower growth within the same window.")

    if st == "pr_event":
        count    = d.get("count", 0)
        headlines = [h for h in (d.get("headlines") or []) if h != "Google News"]
        sample   = f' Recent coverage includes: "{headlines[0]}".' if headlines else ""
        return (f"{name} generated {count} press articles in the past seven days.{sample} "
                f"This level of media activity pushes cultural visibility well beyond "
                f"the artist's owned social channels.")

    if st == "platform_silence":
        prev = d.get("prev_velocity")
        prev_str = (f" previously averaging {prev:.0f} posts per week" if prev else "")
        return (f"{name} did not post on any tracked platform this week{prev_str}. "
                f"For an artist with an active audience, a sudden posting gap can cause "
                f"measurable drops in algorithmic reach.")

    if st == "platform_silence_breaking":
        vel = d.get("curr_velocity", 0)
        return (f"{name} returned to social media with {vel:.0f} posts this week after "
                f"a period of silence. Re-engagement typically triggers a short-term "
                f"boost in platform algorithmic distribution.")

    if st == "engagement_anomaly":
        d_pct = d.get("delta_pct", 0)
        curr_rate = d.get("curr_rate")
        prev_rate = d.get("prev_rate")
        direction = "jumped" if d_pct > 0 else "dropped"
        rates_str = (f" from {prev_rate:.2f}% to {curr_rate:.2f}%"
                     if curr_rate is not None and prev_rate is not None else "")
        return (f"{name}'s engagement rate {direction} {abs(d_pct):.1f}%{rates_str}. "
                f"{'A spike of this size often precedes or accompanies a viral post or release event.' if d_pct > 0 else 'A sustained decline in engagement rate can signal audience fatigue or reduced content quality.'}")

    return s.get("description", "")


# ── AI blurb generation ────────────────────────────────────────────────────────

def _build_ai_prompt(top_signals: list[dict]) -> str:
    """Build the system+user prompt for the Anthropic API call."""
    system = (
        "You are a senior music journalist covering Sony Music Entertainment's regional "
        "Latin and Lusophone roster — spanning Sony Music Latin, Sony Music Brasil, "
        "Sony Music Spain, plus select non-Sony artists of strategic interest — for an "
        "internal executive intelligence dashboard. Write with the precision of Billboard, "
        "the directness of a Reuters wire, and the cultural awareness of Rolling Stone. "
        "Never use hype language. Lead with the most interesting specific fact. "
        "Cite numbers exactly. Compare to context when available (e.g., 'fastest growth "
        "on the roster this week', 'first time below X since August'). "
        "Keep each blurb to 2-3 sentences."
    )

    signal_payloads: list[str] = []
    for i, s in enumerate(top_signals, 1):
        payload = {
            "rank":           i,
            "signal_type":    s["signal_type"],
            "artist":         s["artist_name"],
            "artist_tier":    {4: "mega", 3: "major", 2: "rising", 1: "emerging"}.get(
                                  s.get("tier_rank", 1), "emerging"),
            "kpi":            [_kpi(s["_kpis"], kid).get("kpi_name")
                               for kid in s.get("kpi_ids", [])],
            "description":    s["description"],
            "suggested_headline": _template_headline(s),
            "data":           {k: v for k, v in s.get("data", {}).items()
                               if not isinstance(v, (list, dict)) or k == "headlines"},
        }
        signal_payloads.append(json.dumps(payload, ensure_ascii=False))

    user = (
        "Generate editorial news items for the Sony Latin Pulse daily briefing.\n\n"
        "For each signal below, produce:\n"
        "  - 'headline': a punchy, journalist-style headline under 12 words\n"
        "  - 'summary': 2-3 sentence editorial blurb (factual, specific, no hype)\n\n"
        "Return ONLY a JSON array of objects with keys 'headline' and 'summary'. "
        "Array must have exactly " + str(len(top_signals)) + " elements in the same order.\n\n"
        "Signals:\n" + "\n".join(signal_payloads)
    )
    return system, user


def generate_ai_content(
    top_signals: list[dict],
    api_key:     str,
) -> list[tuple[str, str]]:
    """
    Call Anthropic Messages API directly via urllib (no SDK dependency).
    Returns list of (headline, summary) tuples in same order as top_signals.
    Falls back to template content on any error.
    """
    import urllib.request
    import urllib.error

    system_prompt, user_prompt = _build_ai_prompt(top_signals)

    body = json.dumps({
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 5000,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        text = data["content"][0]["text"].strip()
        log.debug("AI raw response (%d chars): %s…", len(text), text[:200])

        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            if isinstance(parsed, list) and len(parsed) == len(top_signals):
                result = [(item.get("headline", ""), item.get("summary", ""))
                          for item in parsed]
                log.info("AI generated %d headline/summary pairs", len(result))
                return result
        log.warning("AI response was not a valid array of length %d — falling back",
                    len(top_signals))
    except urllib.error.HTTPError as exc:
        log.warning("Anthropic API HTTP %d: %s — using templates", exc.code, exc.reason)
    except Exception as exc:
        log.warning("AI content generation failed: %s — using templates", exc)

    return [(_template_headline(s), _template_blurb(s)) for s in top_signals]


# ── Assemble news item ─────────────────────────────────────────────────────────

def _confidence(signal_type: str, has_delta: bool) -> str:
    """Derive data_confidence indicator string from signal type."""
    # Direct platform fetches → 5 dots
    if signal_type in ("video_momentum", "viral_spike"):
        return "●●●●●"
    # Google News RSS → very recent but not direct verification
    if signal_type == "pr_event":
        return "●●●●○"
    # Milestone and delta-based signals → verified via delta
    if has_delta and signal_type in ("milestone", "rapid_follower_surge",
                                     "spotify_surge", "declining_metrics",
                                     "engagement_anomaly"):
        return "●●●●●"
    # Baseline values from social aggregators
    if signal_type in ("milestone", "rapid_follower_surge", "spotify_surge"):
        return "●●●○○"
    # Inferred from content audit
    if signal_type in ("platform_silence", "platform_silence_breaking"):
        return "●●●○○"
    # Engagement proxy (YT/TT views used as proxy for engagement rate)
    if signal_type == "engagement_anomaly":
        return "●●○○○"
    return "●●●○○"


_SOURCE_MAP: dict[str, str] = {
    "milestone":                "Social platform aggregators; Spotify direct",
    "rapid_follower_surge":     "Social platform aggregators",
    "spotify_surge":            "Spotify artist page (direct fetch)",
    "declining_metrics":        "Social platform aggregators; Spotify direct",
    "new_release":              "Spotify artist page (direct fetch)",
    "viral_spike":              "YouTube channel page (direct fetch)",
    "video_momentum":           "YouTube channel page (direct fetch)",
    "pr_event":                 "Google News RSS (past 7 days)",
    "platform_silence":         "Content velocity audit across all platforms",
    "platform_silence_breaking":"Content velocity audit across all platforms",
    "engagement_anomaly":       "Engagement metrics (Instagram / YouTube proxy)",
}


def build_news_item(
    rank:    int,
    signal:  dict,
    headline: str,
    summary:  str,
    artist_tiers: dict[str, str],
) -> dict:
    slug  = signal["artist_slug"]
    kpis  = signal.get("_kpis", [])
    kpi_ids = signal.get("kpi_ids", [])

    # Build kpi_impact list from actual KPI entries (up to 3)
    kpi_impact: list[dict] = [
        _kpi_impact_entry(_kpi(kpis, kid))
        for kid in kpi_ids
        if _kpi(kpis, kid)
    ]
    # Remove placeholder entries where kpi_id is None
    kpi_impact = [k for k in kpi_impact if k.get("kpi_id") is not None]

    has_delta = any(k.get("delta_absolute") is not None for k in kpi_impact)
    return {
        "priority":        rank,
        "score":           signal["base_score"],
        "signal_type":     signal["signal_type"],
        "headline":        headline,
        "artist_name":     signal["artist_name"],
        "artist_slug":     slug,
        "artist_tier":     artist_tiers.get(slug, "emerging"),
        "image_url":       signal.get("image_url"),
        "kpi_impact":      kpi_impact,
        "summary":         summary,
        "source":          _SOURCE_MAP.get(signal["signal_type"], "Multiple sources"),
        "data_confidence": _confidence(signal["signal_type"], has_delta),
        "timestamp":       f"{TODAY}T00:00:00Z",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4 — News Desk")
    parser.add_argument("--kpis",    type=Path, default=None,
                        help="KPI snapshot (default: data/snapshots/{today}-kpis.json)")
    parser.add_argument("--output",  type=Path, default=None,
                        help="Output path (default: data/news/{today}.json)")
    parser.add_argument("--top",     type=int, default=15,
                        help="Number of items to output (default: 15)")
    parser.add_argument("--no-ai",   action="store_true",
                        help="Skip Anthropic API, use template headlines/blurbs")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Load KPI snapshot ─────────────────────────────────────────────────────
    kpi_path = args.kpis or (SNAPSHOTS_DIR / f"{TODAY}-kpis.json")
    if not kpi_path.exists():
        log.error("KPI snapshot not found: %s", kpi_path)
        log.error("  Run: .venv/bin/python scripts/compute_kpis.py  first")
        return 1

    kpi_snap = json.loads(kpi_path.read_text())
    artists  = kpi_snap["artists"]
    log.info("Loaded %d artists from %s", len(artists), kpi_path)

    # ── Detect and score all signals ──────────────────────────────────────────
    all_signals: list[dict] = []
    for entry in artists:
        all_signals += score_artist(entry)

    log.info("Detected %d signals across %d artists", len(all_signals), len(artists))

    # Sort: score DESC → tier_rank DESC → total_reach DESC → artist name
    all_signals.sort(key=lambda s: (
        -s["base_score"],
        -s["tier_rank"],
        -s.get("total_reach", 0),
        s["artist_name"],
    ))

    # Diversity cap: no single signal_type fills more than 1/3 of the briefing.
    # This prevents 48 artists tying on pr_event from monopolizing the top 15.
    # Two passes:
    #   Pass 1 — enforce cap, collect preferred items
    #   Pass 2 — fill remaining slots from overflow (score order restored after)
    max_per_type = max(3, args.top // 3)
    type_counts: dict[str, int] = {}
    top_n: list[dict] = []
    for sig in all_signals:
        st = sig["signal_type"]
        if type_counts.get(st, 0) >= max_per_type:
            continue
        type_counts[st] = type_counts.get(st, 0) + 1
        top_n.append(sig)
        if len(top_n) >= args.top:
            break

    log.debug("Diversity cap selected %d/%d signals (max %d per type)",
              len(top_n), args.top, max_per_type)


    if not top_n:
        log.warning("No signals detected — check KPI data completeness")
        return 0

    # ── Generate headlines + blurbs ───────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.no_ai or not api_key:
        if not api_key and not args.no_ai:
            log.info("ANTHROPIC_API_KEY not set — using template content")
        pairs = [(_template_headline(s), _template_blurb(s)) for s in top_n]
    else:
        log.info("Calling Anthropic API for %d signals…", len(top_n))
        pairs = generate_ai_content(top_n, api_key)

    # ── Build artist tier lookup ──────────────────────────────────────────────
    artist_tiers = {a["artist_slug"]: a.get("tier", "emerging") for a in artists}

    # ── Assemble news items ───────────────────────────────────────────────────
    news_items: list[dict] = []
    for rank, (signal, (headline, summary)) in enumerate(zip(top_n, pairs), 1):
        news_items.append(build_news_item(rank, signal, headline, summary, artist_tiers))

    # ── Write output ──────────────────────────────────────────────────────────
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (NEWS_DIR / f"{TODAY}.json")

    payload = {
        "news_date":              TODAY,
        "source_snapshot":        str(kpi_path),
        "total_signals_detected": len(all_signals),
        "items":                  news_items,
    }

    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Fixed path consumed by the React frontend
    fixed = ROOT / "data" / "news.json"
    fixed.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("Frontend news → %s", fixed)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n✓  {len(news_items)} news items → {output_path}")
    print(f"   {len(all_signals)} signals scored across {len(artists)} artists\n")
    for item in news_items:
        print(f"  #{item['priority']:2d}  score={item['score']:.1f}  "
              f"[{item['signal_type']:<20}]  "
              f"{item['artist_name']}: {item['headline']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
