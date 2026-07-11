#!/usr/bin/env python3
"""
Generate data/sample-snapshot.json with realistic KPI data for every artist
in data/sample-roster.json.  All 10 KPIs are populated with current value,
previous value, and computed deltas.  Uses a fixed random seed so the file
is reproducible.

Usage:
    python scripts/generate_sample_snapshot.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).parent.parent
SEED = 42
random.seed(SEED)

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

REACH_TIERS: dict[str, tuple[int, int]] = {
    "mega":     (50_000_000,  350_000_000),
    "major":    (10_000_000,   50_000_000),
    "rising":    (1_000_000,   10_000_000),
    "emerging":     (50_000,      999_999),
}

SPOTIFY_RANGES: dict[str, tuple[int, int]] = {
    "mega":     (15_000_000,  85_000_000),
    "major":     (3_000_000,  25_000_000),
    "rising":      (500_000,   8_000_000),
    "emerging":     (30_000,     700_000),
}

VIDEO_VIEW_RANGES: dict[str, tuple[int, int]] = {
    "mega":     (5_000_000,  80_000_000),
    "major":      (500_000,  10_000_000),
    "rising":      (50_000,   2_000_000),
    "emerging":     (3_000,     150_000),
}

CONTENT_VEL_RANGES: dict[str, tuple[int, int]] = {
    "mega":     (4,  18),
    "major":    (3,  15),
    "rising":   (1,  10),
    "emerging": (0,   7),
}

MENTION_RANGES: dict[str, tuple[int, int]] = {
    "mega":     (5,  50),
    "major":    (2,  25),
    "rising":   (0,  12),
    "emerging": (0,   4),
}

# ---------------------------------------------------------------------------
# Artist → tier mapping
# ---------------------------------------------------------------------------

ARTIST_TIERS: dict[str, str] = {
    # ── Mega (>50 M total reach) ──
    "shakira":          "mega",
    "jennifer-lopez":   "mega",
    "daddy-yankee":     "mega",
    "maluma":           "mega",
    "enrique-iglesias": "mega",
    "ricky-martin":     "mega",
    "ozuna":            "mega",
    "nicky-jam":        "mega",
    "rauw-alejandro":   "mega",
    "becky-g":          "mega",
    "romeo-santos":     "mega",
    # ── Major (10–50 M) ──
    "camilo":           "major",
    "alejandro-sanz":   "major",
    "marc-anthony":     "major",
    "carlos-vives":     "major",
    "sebastian-yatra":  "major",
    "tini":             "major",
    "lali":             "major",
    "thalia":           "major",
    "rosalia":          "major",
    "manuel-turizo":    "major",
    "natti-natasha":    "major",
    "prince-royce":     "major",
    "fuerza-regida":    "major",
    "chayanne":         "major",
    "gloria-estefan":   "major",
    "julio-iglesias":   "major",
    "farruko":          "major",
    "pitbull":          "major",
    "anuel-aa":         "major",
    "ha-ash":           "major",
    "christina-aguilera":"major",
    "young-miko":       "major",
    "milo-j":           "major",
    "emilia":           "major",
    # ── Rising (1–10 M) ──
    "nicki-nicole":     "rising",
    "reik":             "rising",
    "c-tangana":        "rising",
    "calle-13":         "rising",
    "chencho-corleone": "rising",
    "aventura":         "rising",
    "kany-garcia":      "rising",
    "bomba-estereo":    "rising",
    "gente-de-zona":    "rising",
    "paloma-mami":      "rising",
    "saiko":            "rising",
    "trueno":           "rising",
    "wisin":            "rising",
    "yandel":           "rising",
    "evaluna-montaner": "rising",
    "mau-y-ricky":      "rising",
    "pedro-capo":       "rising",
    "polima-westcoast": "rising",
    "silvestre-dangond":"rising",
    "kapo":             "rising",
    "leslie-grace":     "rising",
    "darell":           "rising",
    "cauty":            "rising",
    "rvssian":          "rising",
    "noriel":           "rising",
    "il-volo":          "rising",
    "mon-laferte":      "rising",
    "natalia-jimenez":  "rising",
    "ricardo-montaner": "rising",
    "cnco":             "rising",
    "yendry":           "rising",
    "ile":              "rising",
    "draco-rosa":       "rising",
    "zion-lennox":      "rising",
    "chocquibtown":     "rising",
    "rio-roma":         "rising",
    "victor-manuelle":  "rising",
    "charlie-zaa":      "rising",
    "gilberto-santa-rosa":"rising",
    "fonseca":          "rising",
    "franco-de-vita":   "rising",
    "plan-b":           "rising",
    "diego-torres":     "rising",
    "farina":           "rising",
    "lila-downs":       "rising",
    "luis-coronel":     "rising",
    "joss-favela":      "rising",
    "ana-gabriel":      "rising",
    "arcangel":         "rising",
    "cristian-castro":  "rising",
    # ── Emerging (<1 M) ──
    "abraham-mateo":    "emerging",
    "alex-luna":        "emerging",
    "alexis-fido":      "emerging",
    "almighty":         "emerging",
    "arthur-hanlon":    "emerging",
    "dyland-lenny":     "emerging",
    "ednita-nazario":   "emerging",
    "luis-figueroa":    "emerging",
    "lupita-infante":   "emerging",
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _trend(delta_pct: float) -> str:
    if delta_pct > 1.0:
        return "up"
    if delta_pct < -1.0:
        return "down"
    return "flat"


def _reach_tier(v: int) -> str:
    if v > 50_000_000:  return "Mega"
    if v > 10_000_000:  return "Major"
    if v > 1_000_000:   return "Rising"
    return "Emerging"


def _spotify_tier(v: int) -> str:
    if v > 50_000_000:  return "Global Star"
    if v > 20_000_000:  return "Regional Power"
    if v > 5_000_000:   return "Strong"
    if v > 1_000_000:   return "Growing"
    return "Niche"


def _velocity_tier(pct: float) -> str:
    if pct > 5.0:   return "Breakout"
    if pct > 2.0:   return "Strong"
    if pct >= -1.0: return "Steady"
    if pct >= -5.0: return "Declining"
    return "Freefall"


def _engagement_tier(r: float) -> str:
    if r > 3.5: return "Excellent"
    if r > 1.5: return "Good"
    if r > 0.5: return "Average"
    return "Low"


def _content_tier(v: int) -> str:
    if v > 14: return "Hyperactive"
    if v >= 7: return "Active"
    if v >= 3: return "Moderate"
    if v >= 1: return "Low"
    return "Silent"


def _diversity_tier(v: float) -> str:
    if v >= 1.0:  return "Fully Diversified"
    if v >= 0.7:  return "Healthy"
    if v >= 0.5:  return "Some Gaps"
    return "Platform Dependency Risk"


def _recency_tier(days: int) -> str:
    if days <= 14:  return "Fresh"
    if days <= 60:  return "Recent"
    if days <= 120: return "Aging"
    if days <= 180: return "Overdue"
    return "Dark"


def _mention_tier(v: int) -> str:
    if v > 20: return "Trending"
    if v > 10: return "Visible"
    if v > 5:  return "Moderate"
    if v > 0:  return "Quiet"
    return "Off-radar"


def _r(v: float, dp: int = 2) -> float:
    return round(v, dp)


def _pct_delta(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return _r((curr - prev) / prev * 100)


def _rand_pct(lo: float, hi: float) -> float:
    return _r(random.uniform(lo, hi))


def _prev_from_pct(curr: int | float, pct: float) -> int | float:
    """Back-calculate previous value given current value and % change."""
    if isinstance(curr, int):
        return int(curr / (1 + pct / 100))
    return _r(curr / (1 + pct / 100))


# ---------------------------------------------------------------------------
# KPI builders
# ---------------------------------------------------------------------------

def kpi1_total_reach(tier: str) -> dict:
    lo, hi = REACH_TIERS[tier]
    curr = random.randint(lo, hi)
    delta_pct = _rand_pct(-3.0, 6.5)
    prev = _prev_from_pct(curr, delta_pct)
    delta_abs = curr - prev
    return {
        "kpi_id": 1,
        "kpi_name": "Total Social Reach",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": _r(delta_pct),
        "trend": _trend(delta_pct),
        "benchmark_tier": _reach_tier(curr),
        "alert": None,
    }


def kpi2_reach_velocity(kpi1: dict) -> dict:
    curr_vel = kpi1["delta_percent"]          # velocity IS the % change in reach
    prev_vel = _rand_pct(-2.5, 5.0)
    delta_abs = _r(curr_vel - prev_vel)
    delta_pct = _pct_delta(curr_vel, prev_vel) if prev_vel != 0 else 0.0
    tier = _velocity_tier(curr_vel)
    alert = tier if tier in ("Breakout", "Declining", "Freefall") else None
    return {
        "kpi_id": 2,
        "kpi_name": "Social Reach Velocity",
        "current_value": curr_vel,
        "previous_value": prev_vel,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_abs * 10),      # directional on velocity itself
        "benchmark_tier": tier,
        "alert": alert,
    }


def kpi3_engagement_rate(tier: str) -> dict:
    ranges = {
        "mega":     (0.3, 2.8),
        "major":    (0.8, 4.2),
        "rising":   (1.5, 6.5),
        "emerging": (2.0, 9.0),
    }
    lo, hi = ranges[tier]
    curr = _r(random.uniform(lo, hi))
    prev = _r(max(0.05, curr + random.uniform(-0.6, 0.6)))
    delta_abs = _r(curr - prev)
    delta_pct = _pct_delta(curr, prev)
    return {
        "kpi_id": 3,
        "kpi_name": "Engagement Rate",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_pct),
        "benchmark_tier": _engagement_tier(curr),
        "alert": None,
    }


def kpi4_spotify_listeners(tier: str) -> dict:
    lo, hi = SPOTIFY_RANGES[tier]
    curr = random.randint(lo, hi)
    delta_pct = _rand_pct(-5.0, 8.0)
    prev = _prev_from_pct(curr, delta_pct)
    delta_abs = curr - prev
    return {
        "kpi_id": 4,
        "kpi_name": "Spotify Monthly Listeners",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": _r(delta_pct),
        "trend": _trend(delta_pct),
        "benchmark_tier": _spotify_tier(curr),
        "alert": None,
    }


def kpi5_spotify_trend(kpi4: dict) -> dict:
    curr_trend = kpi4["delta_percent"]        # trend IS the % change in listeners
    prev_trend = _rand_pct(-4.5, 7.0)
    delta_abs = _r(curr_trend - prev_trend)
    delta_pct = _pct_delta(curr_trend, prev_trend) if prev_trend != 0 else 0.0
    alert = "New Release Spike" if curr_trend > 20 else None
    return {
        "kpi_id": 5,
        "kpi_name": "Spotify Listener Trend",
        "current_value": curr_trend,
        "previous_value": prev_trend,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_abs * 10),
        "benchmark_tier": _velocity_tier(curr_trend),
        "alert": alert,
    }


def kpi6_content_velocity(tier: str) -> dict:
    lo, hi = CONTENT_VEL_RANGES[tier]
    curr = random.randint(lo, hi)
    prev = max(0, curr + random.randint(-3, 3))
    delta_abs = curr - prev
    delta_pct = _pct_delta(curr, prev)
    return {
        "kpi_id": 6,
        "kpi_name": "Content Velocity",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_pct),
        "benchmark_tier": _content_tier(curr),
        "alert": "Platform Silence Risk" if curr == 0 else None,
    }


def kpi7_platform_diversity() -> dict:
    total = random.randint(4, 7)
    active_curr = random.randint(max(1, total - 2), total)
    active_prev = max(1, active_curr + random.randint(-1, 1))
    active_prev = min(active_prev, total)
    curr = _r(active_curr / total)
    prev = _r(active_prev / total)
    delta_abs = _r(curr - prev)
    delta_pct = _pct_delta(curr, prev)
    alert = "Platform Dependency Risk" if curr < 0.5 else None
    return {
        "kpi_id": 7,
        "kpi_name": "Platform Diversity Score",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_pct),
        "benchmark_tier": _diversity_tier(curr),
        "alert": alert,
    }


def kpi8_video_view_momentum(tier: str) -> dict:
    lo, hi = VIDEO_VIEW_RANGES[tier]
    curr = random.randint(lo, hi)
    delta_pct = _rand_pct(-12.0, 18.0)
    prev = _prev_from_pct(curr, delta_pct)
    delta_abs = curr - prev
    if delta_pct > 100:
        bench = "Viral"
        alert: str | None = "Viral Spike"
    elif delta_pct > 20:
        bench, alert = "Strong", None
    elif delta_pct >= -10:
        bench, alert = "Steady", None
    else:
        bench, alert = "Declining", None
    return {
        "kpi_id": 8,
        "kpi_name": "Video View Momentum",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": _r(delta_pct),
        "trend": _trend(delta_pct),
        "benchmark_tier": bench,
        "alert": alert,
    }


def kpi9_release_recency() -> dict:
    # ~15 % chance artist has a fresh release (0–14 days)
    if random.random() < 0.15:
        curr = random.randint(0, 14)
        prev = random.randint(curr + 20, curr + 90)   # big drop = new release
    else:
        curr = random.randint(15, 300)
        prev = curr + 1                                 # normal daily aging
    delta_abs = curr - prev
    delta_pct = _pct_delta(curr, prev)
    alert = "Dark — Flag to A&R" if curr > 180 else None
    return {
        "kpi_id": 9,
        "kpi_name": "Latest Release Recency",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_pct),
        "benchmark_tier": _recency_tier(curr),
        "alert": alert,
    }


def kpi10_press_mentions(tier: str) -> dict:
    lo, hi = MENTION_RANGES[tier]
    curr = random.randint(lo, hi)
    prev = max(0, curr + random.randint(-6, 6))
    delta_abs = curr - prev
    delta_pct = _pct_delta(curr, prev)
    return {
        "kpi_id": 10,
        "kpi_name": "News & Press Mentions",
        "current_value": curr,
        "previous_value": prev,
        "delta_absolute": delta_abs,
        "delta_percent": delta_pct,
        "trend": _trend(delta_pct),
        "benchmark_tier": _mention_tier(curr),
        "alert": None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_kpis(tier: str) -> list[dict]:
    k1 = kpi1_total_reach(tier)
    k2 = kpi2_reach_velocity(k1)
    k3 = kpi3_engagement_rate(tier)
    k4 = kpi4_spotify_listeners(tier)
    k5 = kpi5_spotify_trend(k4)
    k6 = kpi6_content_velocity(tier)
    k7 = kpi7_platform_diversity()
    k8 = kpi8_video_view_momentum(tier)
    k9 = kpi9_release_recency()
    k10 = kpi10_press_mentions(tier)
    return [k1, k2, k3, k4, k5, k6, k7, k8, k9, k10]


def main() -> None:
    roster_path = ROOT / "data" / "sample-roster.json"
    out_path    = ROOT / "data" / "sample-snapshot.json"

    roster = json.loads(roster_path.read_text())

    snapshot: dict = {
        "snapshot_date": "2026-04-05",
        "previous_snapshot_date": "2026-04-04",
        "generated_by": "scripts/generate_sample_snapshot.py",
        "seed": SEED,
        "note": (
            "Sample data — realistic estimates for dashboard development. "
            "All values are seeded-random within tier-appropriate ranges. "
            "Run the real pipeline to replace with live data."
        ),
        "artists": [],
    }

    for artist in roster["artists"]:
        slug  = artist["slug"]
        tier  = ARTIST_TIERS.get(slug, "rising")   # default rising if unknown
        kpis  = build_kpis(tier)
        snapshot["artists"].append({
            "artist_slug":  slug,
            "artist_name":  artist["name"],
            "tier":         tier,
            "kpis":         kpis,
        })

    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"Wrote {len(snapshot['artists'])} artists → {out_path}")

    # Quick sanity summary
    alerts = [
        (a["artist_name"], k["kpi_name"], k["alert"])
        for a in snapshot["artists"]
        for k in a["kpis"]
        if k["alert"]
    ]
    print(f"Alerts flagged: {len(alerts)}")
    for name, kpi, msg in alerts[:8]:
        print(f"  {name:25s}  {kpi:35s}  {msg}")
    if len(alerts) > 8:
        print(f"  … and {len(alerts) - 8} more")


if __name__ == "__main__":
    main()
