#!/usr/bin/env python3
"""
Deploy to GCP Cloud Storage
=============================
Uploads the Vite build output (dist/) to a GCS bucket configured for
static website hosting, with correct cache headers per file type:

  dist/assets/*   →  Cache-Control: public, max-age=31536000, immutable
                      (content-hashed filenames; can be cached forever)
  dist/index.html →  Cache-Control: no-cache, no-store, must-revalidate
                      (entry point changes on every deploy; never cache)
  dist/* (other)  →  Cache-Control: public, max-age=3600
                      (e.g. favicons, robots.txt; refresh every hour)

After upload, the bucket is configured for SPA fallback routing so that
any URL that returns 404 falls back to index.html (client-side routing).
allUsers:objectViewer is granted so the site is publicly accessible.

Usage:
    .venv/bin/python scripts/deploy.py
    .venv/bin/python scripts/deploy.py --bucket my-other-bucket
    .venv/bin/python scripts/deploy.py --dry-run          # preview only
    .venv/bin/python scripts/deploy.py --no-make-public   # skip IAM change

Environment (read from .env, then .env.example, then shell):
    GCP_BUCKET_NAME   required
    GCP_PROJECT_ID    optional — used only for display
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"

# Cache policies
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"   # hashed assets
CACHE_HTML      = "no-cache, no-store, must-revalidate"    # index.html
CACHE_STATIC    = "public, max-age=3600"                   # everything else


# ── Env loading ───────────────────────────────────────────────────────────────

def _load_dotenv(path: Path) -> None:
    """Load key=value pairs from a file into os.environ (won't overwrite)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def load_env() -> None:
    # .env takes priority over .env.example
    _load_dotenv(ROOT / ".env")
    _load_dotenv(ROOT / ".env.example")


# ── Shell runner ──────────────────────────────────────────────────────────────

def run(
    cmd:     list[str],
    *,
    dry_run: bool = False,
    fatal:   bool = True,
) -> bool:
    """
    Print and optionally execute a command.
    Returns True on success, False on non-zero exit.
    Raises SystemExit on failure when fatal=True (and not dry_run).
    """
    display = " ".join(str(c) for c in cmd)
    if dry_run:
        print(f"    [dry-run] {display}")
        return True

    print(f"    $ {display}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        msg = f"    ✗  exited {result.returncode}"
        if fatal:
            print(msg, file=sys.stderr)
            sys.exit(result.returncode)
        print(msg + "  (non-fatal, continuing)")
        return False
    return True


# ── Deploy steps ──────────────────────────────────────────────────────────────

def upload_assets(bucket: str, dry_run: bool) -> None:
    """Upload dist/assets/ with immutable cache headers."""
    assets = DIST / "assets"
    if not assets.exists():
        print("  assets/  — none found, skipping")
        return

    count = sum(1 for _ in assets.iterdir())
    print(f"\n── Step 1 of 4 ─── assets/ ({count} files, 1-year immutable cache)")
    run([
        "gsutil", "-m",
        "-h", f"Cache-Control:{CACHE_IMMUTABLE}",
        "cp", "-r",
        str(assets),
        f"{bucket}/",
    ], dry_run=dry_run)


def upload_html(bucket: str, dry_run: bool) -> None:
    """Upload HTML files with no-cache headers."""
    html_files = list(DIST.glob("*.html"))
    print(f"\n── Step 2 of 4 ─── *.html ({len(html_files)} file(s), no-cache)")
    for html in html_files:
        run([
            "gsutil",
            "-h", f"Cache-Control:{CACHE_HTML}",
            "-h", "Content-Type:text/html; charset=utf-8",
            "cp",
            str(html),
            f"{bucket}/{html.name}",
        ], dry_run=dry_run)


def upload_other(bucket: str, dry_run: bool) -> None:
    """Upload any other root-level files (favicons, robots.txt, etc.)."""
    others = [
        f for f in DIST.iterdir()
        if f.is_file()
        and f.suffix != ".html"
        and f.name != ".gitkeep"
    ]
    if not others:
        print("\n── Step 3 of 4 ─── other root files (none)")
        return
    print(f"\n── Step 3 of 4 ─── other root files ({len(others)} file(s), 1-hour cache)")
    for f in others:
        run([
            "gsutil",
            "-h", f"Cache-Control:{CACHE_STATIC}",
            "cp",
            str(f),
            f"{bucket}/{f.name}",
        ], dry_run=dry_run)


def configure_website(bucket: str, dry_run: bool) -> None:
    """
    Set the bucket's website configuration.

      -m index.html  — main page (directory index)
      -e index.html  — 404 error page (SPA fallback routing)

    The 404 fallback means any URL like /artist/camilo that doesn't exist
    as a real object will serve index.html, letting React handle routing.
    """
    print(f"\n── Step 4 of 4 ─── website config (404 → index.html fallback)")
    run([
        "gsutil", "web", "set",
        "-m", "index.html",
        "-e", "index.html",
        bucket,
    ], dry_run=dry_run)


def grant_public_access(bucket: str, dry_run: bool) -> None:
    """Grant allUsers:objectViewer so the site is publicly accessible."""
    print("\n── Public access ── granting allUsers:objectViewer")
    run([
        "gsutil", "iam", "ch",
        "allUsers:objectViewer",
        bucket,
    ], dry_run=dry_run, fatal=False)   # non-fatal: may already be set, or org policy may block


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    load_env()

    parser = argparse.ArgumentParser(
        description="Deploy dist/ to GCP Cloud Storage"
    )
    parser.add_argument(
        "--bucket", default=os.environ.get("GCP_BUCKET_NAME"),
        help="GCS bucket name (default: $GCP_BUCKET_NAME)",
    )
    parser.add_argument(
        "--project", default=os.environ.get("GCP_PROJECT_ID"),
        help="GCP project ID — display only (default: $GCP_PROJECT_ID)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print commands without executing anything",
    )
    parser.add_argument(
        "--no-make-public", action="store_true",
        help="Skip granting allUsers:objectViewer (bucket already public)",
    )
    args = parser.parse_args(argv)

    # ── Preflight checks ──────────────────────────────────────────────────────

    if not args.bucket:
        print(
            "error: bucket name required\n"
            "  set GCP_BUCKET_NAME in .env, or pass --bucket BUCKET_NAME",
            file=sys.stderr,
        )
        return 1

    if not DIST.exists() or not (DIST / "index.html").exists():
        print(
            f"error: dist/index.html not found — run 'npm run build' first",
            file=sys.stderr,
        )
        return 1

    if not shutil.which("gsutil"):
        print(
            "error: gsutil not found\n"
            "  install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install\n"
            "  then authenticate: gcloud auth login",
            file=sys.stderr,
        )
        return 1

    bucket = f"gs://{args.bucket}"

    # ── Header ────────────────────────────────────────────────────────────────

    print("═" * 60)
    print("  Sony Latin Pulse — Deploy to GCP Cloud Storage")
    print("═" * 60)
    print(f"  Bucket:  {bucket}")
    if args.project:
        print(f"  Project: {args.project}")
    if args.dry_run:
        print("  Mode:    DRY RUN (no changes made)")
    print()

    # Summarise what's in dist/
    all_dist = [f for f in DIST.rglob("*") if f.is_file() and f.name != ".gitkeep"]
    total_bytes = sum(f.stat().st_size for f in all_dist)
    print(f"  {len(all_dist)} files  /  {total_bytes / 1024:.0f} KB total")

    # ── Upload ────────────────────────────────────────────────────────────────

    upload_assets(bucket, args.dry_run)
    upload_html(bucket, args.dry_run)
    upload_other(bucket, args.dry_run)
    configure_website(bucket, args.dry_run)

    if not args.no_make_public:
        grant_public_access(bucket, args.dry_run)

    # ── Summary ───────────────────────────────────────────────────────────────

    print()
    print("═" * 60)
    if args.dry_run:
        print("  Dry run complete — no files uploaded")
    else:
        print("  ✓  Deploy complete")
        bucket_name = args.bucket
        print(f"\n  Public URL:")
        print(f"    https://storage.googleapis.com/{bucket_name}/")
        print(f"\n  If you've mapped a custom domain or Cloud Run URL:")
        print(f"    gsutil web set -m index.html -e index.html {bucket}")
        print(f"    gcloud compute backend-buckets create ... --gcs-bucket-name={bucket_name}")
    print("═" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
