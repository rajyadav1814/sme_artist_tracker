#!/usr/bin/env python3
"""
Merge client-provided social-links CSV into data/curated_artists.yaml.

The client periodically returns a filled copy of
``data/curated_social_links_template.csv``. This script:

  1. Validates every URL against the expected domain for its column
     (e.g. a value in the ``spotify`` column must be on open.spotify.com).
     Cells that fail validation are reported and SKIPPED — they are not
     merged. This catches accidental copy-paste smears where one URL was
     pasted into the wrong column.

  2. Normalizes URLs (adds the ``https://`` prefix when missing).

  3. Loads the YAML with ruamel.yaml (preserves the file's comments and
     ordering), writes the validated URLs into each artist's
     ``social_links:`` block, and saves the file back in place.

  4. Manual values in the YAML always win: when the same field is already
     populated, the existing value is kept and the CSV value is skipped
     (logged for visibility).

Usage:
    .venv/bin/python scripts/merge_social_links.py
    .venv/bin/python scripts/merge_social_links.py --csv path/to/filled.csv
    .venv/bin/python scripts/merge_social_links.py --dry-run    # preview, don't write
    .venv/bin/python scripts/merge_social_links.py --force      # overwrite existing values
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path

from ruamel.yaml import YAML

ROOT       = Path(__file__).parent.parent
YAML_PATH  = ROOT / "data" / "curated_artists.yaml"
CSV_PATH   = ROOT / "data" / "curated_social_links_filled.csv"

# CSV column → YAML field name (CSV uses x_twitter, YAML uses x)
COL_TO_FIELD = {
    "instagram":   "instagram",
    "youtube":     "youtube",
    "tiktok":      "tiktok",
    "x_twitter":   "x",
    "spotify":     "spotify",
    "apple_music": "apple_music",
    "facebook":    "facebook",
    "soundcloud":  "soundcloud",
}

# Domain pattern required for each column to count as valid data
DOMAIN_PATTERNS = {
    "instagram":   [r"(?:www\.)?instagram\.com/"],
    "youtube":     [r"(?:www\.)?youtube\.com/", r"youtu\.be/"],
    "tiktok":      [r"(?:www\.)?tiktok\.com/"],
    "x_twitter":   [r"(?:www\.)?(?:twitter|x)\.com/"],
    "spotify":     [r"open\.spotify\.com/artist/"],
    "apple_music": [r"(?:music|itunes)\.apple\.com/"],
    "facebook":    [r"(?:www\.)?facebook\.com/", r"fb\.com/"],
    "soundcloud":  [r"(?:www\.)?soundcloud\.com/"],
}

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Add https:// if no protocol; strip whitespace."""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url


def valid_for_column(col: str, url: str) -> bool:
    for pat in DOMAIN_PATTERNS.get(col, []):
        if re.search(pat, url, re.I):
            return True
    return False


def read_csv(path: Path) -> tuple[dict[str, dict[str, str]], list[tuple[str, str, str]]]:
    """Parse CSV → {slug: {field: url}} plus a list of validation errors."""
    by_slug:  dict[str, dict[str, str]] = {}
    skipped:  list[tuple[str, str, str]] = []

    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue

            fields: dict[str, str] = {}
            for col, field in COL_TO_FIELD.items():
                url = normalize_url(row.get(col) or "")
                if not url:
                    continue
                if not valid_for_column(col, url):
                    skipped.append((slug, col, url))
                    continue
                fields[field] = url
            if fields:
                by_slug[slug] = fields

    return by_slug, skipped


def apply_to_yaml(
    yaml_data,
    by_slug: dict[str, dict[str, str]],
    force: bool,
) -> tuple[int, int, list[tuple[str, str]]]:
    """Mutate yaml_data in place. Returns (applied, kept_existing_count, kept_existing_list)."""
    applied = 0
    kept_existing: list[tuple[str, str]] = []

    artists = yaml_data.get("artists") or []
    artists_by_slug = {a["slug"]: a for a in artists if isinstance(a, dict) and a.get("slug")}

    for slug, fields in by_slug.items():
        artist = artists_by_slug.get(slug)
        if artist is None:
            log.warning("Slug %r is in CSV but not in YAML — skipping", slug)
            continue

        social = artist.get("social_links")
        if social is None:
            artist["social_links"] = {}
            social = artist["social_links"]

        for field, url in fields.items():
            existing = social.get(field)
            if existing and not force:
                kept_existing.append((slug, field))
                continue
            social[field] = url
            applied += 1

    return applied, len(kept_existing), kept_existing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge CSV social links into curated_artists.yaml")
    parser.add_argument("--csv",    type=Path, default=CSV_PATH,
                        help="CSV path (default: data/curated_social_links_filled.csv)")
    parser.add_argument("--yaml",   type=Path, default=YAML_PATH,
                        help="YAML path (default: data/curated_artists.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing the YAML")
    parser.add_argument("--force",   action="store_true",
                        help="Overwrite social_links fields already set in the YAML")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s  %(message)s",
    )

    if not args.csv.exists():
        log.error("CSV not found: %s", args.csv)
        return 1
    if not args.yaml.exists():
        log.error("YAML not found: %s", args.yaml)
        return 1

    by_slug, skipped = read_csv(args.csv)
    log.info("Parsed %d artist rows from %s", len(by_slug), args.csv.name)
    if skipped:
        log.warning("Skipped %d invalid URLs (domain mismatch):", len(skipped))
        for slug, col, url in skipped:
            log.warning("  %s.%s → %s", slug, col, url)

    # Load YAML preserving comments
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096   # don't wrap long URLs
    yaml_data = y.load(args.yaml.read_text())

    applied, kept_count, kept_list = apply_to_yaml(yaml_data, by_slug, force=args.force)
    log.info("Applied %d URL assignments to YAML", applied)
    if kept_count:
        log.info("Kept %d existing YAML values (use --force to overwrite):", kept_count)
        for slug, field in kept_list[:10]:
            log.info("  %s.%s already set", slug, field)
        if kept_count > 10:
            log.info("  ... and %d more", kept_count - 10)

    if args.dry_run:
        log.info("--dry-run: not writing YAML")
        return 0

    with args.yaml.open("w") as f:
        y.dump(yaml_data, f)
    log.info("Wrote %s", args.yaml)

    print()
    print(f"✓  Merge complete")
    print(f"   Applied:  {applied}  URL assignments")
    print(f"   Skipped:  {len(skipped)}  invalid (domain mismatch) — kept null in YAML")
    print(f"   Kept:     {kept_count}  existing YAML values preserved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
