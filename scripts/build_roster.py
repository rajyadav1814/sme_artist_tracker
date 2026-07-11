#!/usr/bin/env python3
"""
Phase 1 — Roster Builder
========================
Reads data/curated_artists.yaml (the customer-curated authoritative list) and
produces data/roster.json in the schema expected by the rest of the pipeline
and the React frontend.

Replaces the older "scrape Sony Music Latin website" approach.  The curated
YAML is now the source of truth; scraping is demoted to an optional enrichment
helper for filling missing social links / images / bios.

Idempotency:
  - If data/roster.json already exists, social_links / image_url / bio_excerpt
    from previous runs are preserved (per-slug merge).
  - YAML edits propagate through; manual values in YAML always win.

Usage:
    .venv/bin/python scripts/build_roster.py
    .venv/bin/python scripts/build_roster.py --no-enrich    # YAML only, skip SML fetch
    .venv/bin/python scripts/build_roster.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
from datetime import date
from pathlib import Path

import yaml

# Reuse helpers from the existing scraper rather than duplicating
sys.path.insert(0, str(Path(__file__).parent))
from scrape_roster import (   # noqa: E402
    SocialLinks,
    RosterArtist,
    enrich_from_detail_page,
    artist_profile_url,
    image_placeholder,
)

ROOT          = Path(__file__).parent.parent
CURATED_PATH  = ROOT / "data" / "curated_artists.yaml"
ROSTER_PATH   = ROOT / "data" / "roster.json"

log = logging.getLogger(__name__)


# ── Schema validation ────────────────────────────────────────────────────────

ALLOWED_LABEL_STATUS = {
    "sony-latin", "sony-brasil", "sony-spain", "sony-mexico",
    "non-sony", "unconfirmed",
}
ALLOWED_ENTITY_TYPE  = {"solo", "duo", "group", "estate"}
ALLOWED_STATUS       = {"active", "hiatus", "legacy_estate", "archived"}
ALLOWED_PRIORITY     = {"high", "standard", "rising", "catalog"}


def _validate(curated_artists: list[dict]) -> None:
    """Fail fast on malformed YAML — better than producing a broken roster."""
    seen_slugs: set[str] = set()
    errors: list[str] = []

    for i, a in enumerate(curated_artists):
        prefix = f"artist[{i}] ({a.get('name', '?')})"

        for required in ("name", "slug"):
            if not a.get(required):
                errors.append(f"{prefix}: missing required field '{required}'")

        slug = a.get("slug")
        if slug:
            if slug in seen_slugs:
                errors.append(f"{prefix}: duplicate slug '{slug}'")
            seen_slugs.add(slug)

        for field, allowed in (
            ("label_status", ALLOWED_LABEL_STATUS),
            ("entity_type",  ALLOWED_ENTITY_TYPE),
            ("status",       ALLOWED_STATUS),
            ("priority",     ALLOWED_PRIORITY),
        ):
            val = a.get(field)
            if val is not None and val not in allowed:
                errors.append(
                    f"{prefix}: {field}='{val}' not in {sorted(allowed)}"
                )

    if errors:
        for e in errors:
            log.error("  %s", e)
        raise SystemExit(f"curated_artists.yaml has {len(errors)} validation error(s)")


# ── Build ────────────────────────────────────────────────────────────────────

def _load_existing_roster(path: Path) -> dict[str, dict]:
    """Return {slug: artist_dict} from a prior roster.json, for idempotent merge."""
    if not path.exists():
        return {}
    try:
        prior = json.loads(path.read_text())
        return {a["slug"]: a for a in prior.get("artists", []) if a.get("slug")}
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("Existing roster.json unreadable (%s) — starting fresh", exc)
        return {}


def _to_roster_artist(curated: dict, prior: dict | None) -> tuple[RosterArtist, dict]:
    """
    Build a RosterArtist (legacy-shape fields the pipeline expects) and an
    extras dict (new metadata fields we'll add to the JSON output but that
    aren't on the dataclass).

    Manual social_links / image_url in YAML always win.
    Otherwise we carry forward whatever the previous run discovered.
    """
    slug          = curated["slug"]
    name          = curated["name"]
    profile_url   = curated.get("profile_url") or artist_profile_url(slug)

    # ── Social links: YAML > prior roster > empty ────────────────────────────
    yaml_social   = curated.get("social_links") or {}
    prior_social  = (prior or {}).get("social_links") or {}
    merged_social = SocialLinks(
        instagram   = yaml_social.get("instagram")   or prior_social.get("instagram"),
        youtube     = yaml_social.get("youtube")     or prior_social.get("youtube"),
        tiktok      = yaml_social.get("tiktok")      or prior_social.get("tiktok"),
        x           = yaml_social.get("x")           or prior_social.get("x"),
        spotify     = yaml_social.get("spotify")     or prior_social.get("spotify"),
        apple_music = yaml_social.get("apple_music") or prior_social.get("apple_music"),
        facebook    = yaml_social.get("facebook")    or prior_social.get("facebook"),
    )

    # ── Image: YAML > prior > placeholder ─────────────────────────────────────
    image_url = (
        curated.get("image_url")
        or (prior or {}).get("image_url")
        or image_placeholder(slug)
    )
    image_local_path = (
        curated.get("image_local_path")
        or (prior or {}).get("image_local_path")
        or f"data/images/{slug}.jpg"
    )

    # ── Bio: YAML > prior > empty ────────────────────────────────────────────
    bio_excerpt = curated.get("bio_excerpt") or (prior or {}).get("bio_excerpt") or ""

    artist = RosterArtist(
        name             = name,
        slug             = slug,
        profile_url      = profile_url,
        image_url        = image_url,
        image_local_path = image_local_path,
        bio_excerpt      = bio_excerpt,
        social_links     = merged_social,
    )

    # ── Curated metadata fields (additive — pass through to JSON) ────────────
    extras: dict = {}
    for field in (
        "country", "primary_market", "genre_tags",
        "label_division", "label_status",
        "entity_type", "members",
        "status", "deceased_date",
        "priority", "aliases", "notes",
    ):
        if field in curated:
            extras[field] = curated[field]

    return artist, extras


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build roster.json from curated YAML")
    parser.add_argument("--curated",   type=Path, default=CURATED_PATH,
                        help="Curated YAML (default: data/curated_artists.yaml)")
    parser.add_argument("--output",    type=Path, default=ROSTER_PATH,
                        help="Output roster.json (default: data/roster.json)")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip SML detail-page enrichment for missing fields")
    parser.add_argument("--delay",     type=float, default=2.0,
                        help="Seconds between SML enrichment fetches (default: 2.0)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.curated.exists():
        log.error("Curated YAML not found: %s", args.curated)
        return 1

    raw = yaml.safe_load(args.curated.read_text())
    curated_artists = raw.get("artists") or []
    if not curated_artists:
        log.error("No artists in %s", args.curated)
        return 1

    log.info("Loaded %d curated artists from %s", len(curated_artists), args.curated.name)
    _validate(curated_artists)

    prior_by_slug = _load_existing_roster(args.output)
    if prior_by_slug:
        log.info("Found prior roster.json with %d artists — merging", len(prior_by_slug))

    built: list[tuple[RosterArtist, dict]] = []
    needs_enrichment: list[RosterArtist] = []

    for c in curated_artists:
        artist, extras = _to_roster_artist(c, prior_by_slug.get(c["slug"]))
        built.append((artist, extras))

        # Flag for enrichment if any social link is missing AND no manual override
        any_social_link = any(
            getattr(artist.social_links, f) for f in
            ("instagram", "youtube", "tiktok", "x", "spotify", "apple_music", "facebook")
        )
        # Skip enrichment for legacy estates and non-sony artists where SML page won't exist
        is_sml = (c.get("label_status") in {"sony-latin", "sony-mexico"})
        if (not any_social_link or "placehold.co" in artist.image_url) and is_sml \
                and c.get("status") != "legacy_estate":
            needs_enrichment.append(artist)

    # ── Optional SML detail enrichment ───────────────────────────────────────
    if not args.no_enrich and needs_enrichment:
        log.info("Enriching %d artists from SML detail pages "
                 "(--no-enrich to skip)", len(needs_enrichment))
        for i, artist in enumerate(needs_enrichment, 1):
            log.info("  [%d/%d] %s", i, len(needs_enrichment), artist.name)
            enrich_from_detail_page(artist, args.delay)
    elif args.no_enrich:
        log.info("Skipping SML enrichment (--no-enrich)")
    else:
        log.info("All artists have social links + images cached — no enrichment needed")

    # ── Write output ─────────────────────────────────────────────────────────
    artists_out: list[dict] = []
    for artist, extras in built:
        d = artist.to_dict()
        d.update(extras)        # curated metadata layered on top
        artists_out.append(d)

    payload = {
        "roster_date":  date.today().isoformat(),
        "source":       f"curated:{args.curated.name} (v{raw.get('version','?')})",
        "artist_count": len(artists_out),
        "artists":      artists_out,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    log.info("Wrote %d artists → %s", len(artists_out), args.output)
    print(f"\n✓  {len(artists_out)} artists → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
