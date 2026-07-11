#!/usr/bin/env python3
"""
Sony Latin Pulse — Daily Pipeline Orchestrator
================================================
Runs all pipeline phases in sequence. A failure in one phase is logged and
the pipeline continues to subsequent phases where possible, so a bad scrape
never silences the news desk.

Phases:
  1   build_roster.py    — produce data/roster.json from data/curated_artists.yaml
                            (replaces the old Sony Music Latin website scrape)
  1b  enrich_links.py    — populate social links via MusicBrainz API
  2   harvest_social.py  — scrape social metrics for every artist
  3   compute_kpis.py    — compute 10 KPIs with day-over-day deltas
  4   generate_news.py   — score changes, call Anthropic for Top-15 briefing

Skip flags let you re-run individual phases without redoing earlier work.

Usage:
    .venv/bin/python scripts/run_pipeline.py
    .venv/bin/python scripts/run_pipeline.py --skip-scrape --skip-enrich
    .venv/bin/python scripts/run_pipeline.py --skip-harvest   # re-run KPIs + news only
    .venv/bin/python scripts/run_pipeline.py --limit 10       # quick test (10 artists)
    .venv/bin/python scripts/run_pipeline.py --no-ai          # skip LLM blurbs
    .venv/bin/python scripts/run_pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT  = Path(__file__).parent.parent
TODAY = date.today().isoformat()
log   = logging.getLogger(__name__)

# Use the interpreter that launched this script so the venv is always respected.
PYTHON = sys.executable


# ── Phase result tracking ──────────────────────────────────────────────────────

@dataclass
class PhaseResult:
    name:     str
    status:   str   = "pending"   # "ok" | "failed" | "skipped" | "warning"
    duration: float = 0.0
    note:     str   = ""

    @property
    def icon(self) -> str:
        return {"ok": "✓", "failed": "✗", "skipped": "⊘", "warning": "⚠"}.get(
            self.status, "?"
        )


# ── Subprocess runner ──────────────────────────────────────────────────────────

def run_phase(
    result: PhaseResult,
    cmd:    list[str],
    *,
    critical: bool = False,
) -> bool:
    """
    Run a subprocess command with live-streamed output.

    critical=True means failure is logged at ERROR level and the caller may
    choose to abort subsequent dependent phases.  critical=False logs at WARNING
    and always returns False without raising.

    Returns True on success, False on failure.
    """
    sep = "─" * 60
    log.info(sep)
    log.info("▶  %s", result.name)
    log.info(sep)

    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ROOT)
        result.duration = time.monotonic() - t0

        if proc.returncode == 0:
            result.status = "ok"
            log.info("✓  %s  (%.1fs)", result.name, result.duration)
            return True
        else:
            result.status = "failed"
            result.note   = f"exit {proc.returncode}"
            msg = "✗  %s failed (exit %d, %.1fs)"
            if critical:
                log.error(msg, result.name, proc.returncode, result.duration)
            else:
                log.warning(msg, result.name, proc.returncode, result.duration)
            return False

    except Exception as exc:
        result.duration = time.monotonic() - t0
        result.status   = "failed"
        result.note     = str(exc)
        log.error("✗  %s raised: %s", result.name, exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sony Latin Pulse — full daily pipeline"
    )
    parser.add_argument("--skip-build",    action="store_true",
                        help="Skip Phase 1 (build roster from curated YAML)")
    parser.add_argument("--skip-scrape",   action="store_true",
                        help=argparse.SUPPRESS)   # back-compat alias for --skip-build
    parser.add_argument("--skip-enrich",   action="store_true",
                        help="Skip Phase 1b (social-link enrichment)")
    parser.add_argument("--skip-images",   action="store_true",
                        help="Skip Phase 1c (image discovery + download)")
    parser.add_argument("--skip-harvest",  action="store_true",
                        help="Skip Phase 2 (social harvest); reuse today's snapshot")
    parser.add_argument("--skip-kpis",     action="store_true",
                        help="Skip Phase 3 (KPI computation); reuse today's KPI file")
    parser.add_argument("--skip-news",     action="store_true",
                        help="Skip Phase 4 (news generation)")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Limit Phase 2 to first N artists (for testing)")
    parser.add_argument("--delay",   type=float, default=1.5,
                        help="Seconds between requests in Phase 2 (default: 1.5)")
    parser.add_argument("--no-ai",   action="store_true",
                        help="Skip Anthropic API in Phase 4; use template blurbs")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    verbose_flag  = ["--verbose"] if args.verbose else []
    snapshot_path = ROOT / "data" / "snapshots" / f"{TODAY}.json"
    kpi_path      = ROOT / "data" / "snapshots" / f"{TODAY}-kpis.json"
    news_path     = ROOT / "data" / "news"       / f"{TODAY}.json"

    results: list[PhaseResult] = []
    t_pipeline_start = time.monotonic()

    log.info("═" * 60)
    log.info("  Sony Latin Pulse — Daily Pipeline  [%s]", TODAY)
    log.info("═" * 60)

    # ── Phase 1: Build roster from curated YAML ────────────────────────────────
    # The curated list (data/curated_artists.yaml) is the authoritative source;
    # build_roster.py merges it with the prior data/roster.json so previously
    # discovered social links / images / bios are preserved across runs.
    p1 = PhaseResult("Phase 1 — Build Roster (curated)")
    results.append(p1)
    if args.skip_build or args.skip_scrape:
        p1.status = "skipped"
        log.info("⊘  Phase 1 — Build Roster  (skipped)")
    else:
        ok = run_phase(p1, [
            PYTHON, "scripts/build_roster.py",
            "--curated", "data/curated_artists.yaml",
            "--output",  "data/roster.json",
            *verbose_flag,
        ])
        if not ok:
            p1.status = "warning"   # demote: prior roster.json is still usable
            log.warning("   Continuing with existing data/roster.json")

    # ── Phase 1b: Social-link enrichment ──────────────────────────────────────
    p1b = PhaseResult("Phase 1b — Social Link Enrichment")
    results.append(p1b)
    if args.skip_enrich:
        p1b.status = "skipped"
        log.info("⊘  Phase 1b — Social Link Enrichment  (skipped)")
    else:
        ok = run_phase(p1b, [
            PYTHON, "scripts/enrich_links.py",
            "--roster", "data/roster.json",
            *verbose_flag,
        ])
        if not ok:
            p1b.status = "warning"
            log.warning("   Continuing — social links may be incomplete")

    # ── Phase 1c: Image discovery ─────────────────────────────────────────────
    # Fills missing artist headshots from Spotify og:image (primary), Deezer,
    # or Wikipedia (fallback). Skips artists that already have a local file.
    p1c = PhaseResult("Phase 1c — Image Discovery")
    results.append(p1c)
    if args.skip_images:
        p1c.status = "skipped"
        log.info("⊘  Phase 1c — Image Discovery  (skipped)")
    else:
        ok = run_phase(p1c, [
            PYTHON, "scripts/fetch_images.py",
            *verbose_flag,
        ])
        if not ok:
            p1c.status = "warning"
            log.warning("   Continuing — some artists may show placeholder images")

    # ── Phase 2: Social harvest ────────────────────────────────────────────────
    p2 = PhaseResult("Phase 2 — Social Media Harvest")
    results.append(p2)
    if args.skip_harvest:
        p2.status = "skipped"
        log.info("⊘  Phase 2 — Social Media Harvest  (skipped)")
        if not snapshot_path.exists():
            log.error("   --skip-harvest set but no snapshot found at %s", snapshot_path)
            log.error("   Cannot run Phase 3 without a harvest snapshot — aborting")
            _print_summary(results, time.monotonic() - t_pipeline_start)
            return 1
    else:
        harvest_cmd = [
            PYTHON, "scripts/harvest_social.py",
            "--roster",  "data/roster.json",
            "--output",  str(snapshot_path),
            "--delay",   str(args.delay),
            *verbose_flag,
        ]
        if args.limit:
            harvest_cmd += ["--limit", str(args.limit)]

        ok = run_phase(p2, harvest_cmd, critical=True)
        if not ok:
            # Fall back to the most recent existing snapshot if one exists
            existing = sorted(
                (ROOT / "data" / "snapshots").glob("[0-9]*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            # Exclude -kpis.json files
            existing = [p for p in existing if "-kpis" not in p.name]
            if existing:
                fallback = existing[0]
                log.warning("   Harvest failed — falling back to %s", fallback.name)
                snapshot_path = fallback
                p2.note += f" → fallback: {fallback.name}"
            else:
                log.error("   No fallback snapshot available — aborting")
                _print_summary(results, time.monotonic() - t_pipeline_start)
                return 1

    # ── Phase 3: KPI computation ───────────────────────────────────────────────
    p3 = PhaseResult("Phase 3 — KPI Engine")
    results.append(p3)
    if args.skip_kpis:
        p3.status = "skipped"
        log.info("⊘  Phase 3 — KPI Engine  (skipped)")
        if not kpi_path.exists():
            log.error("   --skip-kpis set but no KPI file found at %s", kpi_path)
            log.error("   Cannot run Phase 4 without KPI data — aborting")
            _print_summary(results, time.monotonic() - t_pipeline_start)
            return 1
    else:
        ok = run_phase(p3, [
            PYTHON, "scripts/compute_kpis.py",
            "--snapshot",      str(snapshot_path),
            "--roster",        "data/roster.json",
            "--output",        str(kpi_path),
            "--dashboard-out", "data/dashboard.json",
            *verbose_flag,
        ], critical=True)
        if not ok:
            # Try to fall back to the most recent KPI file
            existing_kpis = sorted(
                (ROOT / "data" / "snapshots").glob("[0-9]*-kpis.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if existing_kpis:
                fallback = existing_kpis[0]
                log.warning("   KPI computation failed — falling back to %s",
                            fallback.name)
                kpi_path  = fallback
                p3.note  += f" → fallback: {fallback.name}"
            else:
                log.warning("   KPI computation failed and no fallback KPI file found")
                log.warning("   Skipping Phase 4 (no data to score)")
                p3.note = "no fallback available"
                _print_summary(results, time.monotonic() - t_pipeline_start)
                return 1

    # ── Phase 4: News desk ─────────────────────────────────────────────────────
    p4 = PhaseResult("Phase 4 — News Desk")
    results.append(p4)
    if args.skip_news:
        p4.status = "skipped"
        log.info("⊘  Phase 4 — News Desk  (skipped)")
    else:
        news_cmd = [
            PYTHON, "scripts/generate_news.py",
            "--kpis",   str(kpi_path),
            "--output", str(news_path),
            *verbose_flag,
        ]
        if args.no_ai:
            news_cmd.append("--no-ai")

        # Phase 4 failure is logged but never aborts — stale news is better than
        # no news.  The previous data/news.json remains in place on the frontend.
        run_phase(p4, news_cmd)
        if p4.status == "failed":
            log.warning("   News generation failed — frontend retains previous briefing")

    # ── Final summary ──────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_pipeline_start
    _print_summary(results, elapsed)

    # Return non-zero only if any required phase failed outright (not just warning)
    failed = [r for r in results if r.status == "failed"]
    return 1 if failed else 0


def _print_summary(results: list[PhaseResult], elapsed: float) -> None:
    log.info("═" * 60)
    log.info("  Pipeline Summary  (%.1fs total)", elapsed)
    log.info("═" * 60)
    for r in results:
        dur_str = f"  {r.duration:.1f}s" if r.duration > 0 else ""
        note_str = f"  [{r.note}]" if r.note else ""
        log.info("  %s  %-38s%s%s", r.icon, r.name, dur_str, note_str)
    log.info("─" * 60)

    # Show output file locations for successful/skipped phases
    snap_path = ROOT / "data" / "snapshots" / f"{TODAY}-kpis.json"
    news_path = ROOT / "data" / "news" / f"{TODAY}.json"
    if snap_path.exists():
        log.info("  KPI snapshot  →  %s", snap_path.relative_to(ROOT))
    if news_path.exists():
        log.info("  News briefing →  %s", news_path.relative_to(ROOT))
    frontend_snap = ROOT / "data" / "snapshot.json"
    frontend_news = ROOT / "data" / "news.json"
    if frontend_snap.exists():
        log.info("  Frontend KPIs →  data/snapshot.json")
    if frontend_news.exists():
        log.info("  Frontend news →  data/news.json")
    log.info("═" * 60)


if __name__ == "__main__":
    sys.exit(main())
