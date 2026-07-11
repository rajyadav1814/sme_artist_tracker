#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy-gcs.sh — Full pipeline → build → deploy to GCP Cloud Storage
#
# Usage:
#   ./scripts/deploy-gcs.sh <bucket-name>
#   ./scripts/deploy-gcs.sh sme-artist-tracker
#
# Requirements:
#   - gcloud SDK installed and authenticated (gcloud auth login)
#   - Python venv at .venv/ with pipeline dependencies installed
#   - Node + npm installed
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────

BUCKET_NAME="${1:-}"

if [[ -z "$BUCKET_NAME" ]]; then
  # Fall back to env var
  BUCKET_NAME="${GCP_BUCKET_NAME:-}"
fi

if [[ -z "$BUCKET_NAME" ]]; then
  echo "error: bucket name required" >&2
  echo "  Usage: $0 <bucket-name>" >&2
  echo "  Or set GCP_BUCKET_NAME in your environment / .env file" >&2
  exit 1
fi

GCS_BUCKET="gs://${BUCKET_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
PYTHON="${ROOT_DIR}/.venv/bin/python"

# ── Load .env (optional) ──────────────────────────────────────────────────────

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -o allexport
  # shellcheck disable=SC1090
  source "${ROOT_DIR}/.env"
  set +o allexport
fi

# ── Dependency checks ─────────────────────────────────────────────────────────

if ! command -v gsutil &>/dev/null; then
  echo "error: gsutil not found — install the Google Cloud SDK" >&2
  echo "  https://cloud.google.com/sdk/docs/install" >&2
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo "error: npm not found" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "error: Python venv not found at .venv/" >&2
  echo "  Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# ── Header ────────────────────────────────────────────────────────────────────

echo "════════════════════════════════════════════════════════════"
echo "  Sony Music Latin Pulse — Full Deploy"
echo "════════════════════════════════════════════════════════════"
echo "  Bucket:  ${GCS_BUCKET}"
echo "  Root:    ${ROOT_DIR}"
echo ""

# ── Step 1: Python pipeline ───────────────────────────────────────────────────

echo "── Step 1/4 ── Running data pipeline"
cd "${ROOT_DIR}"
"$PYTHON" scripts/run_pipeline.py
echo "  ✓ Pipeline complete"
echo ""

# ── Step 2: Vite build ────────────────────────────────────────────────────────

echo "── Step 2/4 ── Building static site (npm run build)"
npm run build
echo "  ✓ Build complete → dist/"
echo ""

# ── Step 3: Create bucket if it doesn't exist ────────────────────────────────

echo "── Step 3/4 ── Configuring GCS bucket"

if ! gsutil ls "${GCS_BUCKET}" &>/dev/null; then
  echo "  Bucket not found — creating ${GCS_BUCKET}"
  gsutil mb "${GCS_BUCKET}"
  echo "  ✓ Bucket created"
else
  echo "  Bucket exists — skipping creation"
fi

# Enable static website hosting (index.html for both main page and 404 fallback
# so client-side routing works: any unknown path returns index.html)
gsutil web set -m index.html -e index.html "${GCS_BUCKET}"
echo "  ✓ Website hosting configured (index.html + SPA 404 fallback)"

# Grant public read access (non-fatal — org policy may already enforce it)
gsutil iam ch allUsers:objectViewer "${GCS_BUCKET}" 2>/dev/null \
  && echo "  ✓ Public read access granted" \
  || echo "  ⚠ Could not set public access (may already be set or blocked by org policy)"

echo ""

# ── Step 4: Incremental upload via rsync ─────────────────────────────────────

echo "── Step 4/4 ── Uploading dist/ → ${GCS_BUCKET}"
echo ""

# assets/ — content-hashed filenames, safe to cache for 1 year
echo "  Uploading assets/ (immutable cache)"
gsutil -m \
  -h "Cache-Control:public, max-age=31536000, immutable" \
  rsync -r -d \
  "${DIST_DIR}/assets" \
  "${GCS_BUCKET}/assets"

# data/ — JSON snapshots, short cache so refreshes propagate within an hour
if [[ -d "${DIST_DIR}/data" ]]; then
  echo "  Uploading data/ (1-hour cache)"
  gsutil -m \
    -h "Cache-Control:public, max-age=3600" \
    rsync -r -d \
    "${DIST_DIR}/data" \
    "${GCS_BUCKET}/data"
fi

# *.html — never cache; must always be fresh for SPA routing to work
echo "  Uploading HTML (no-cache)"
for html_file in "${DIST_DIR}"/*.html; do
  gsutil \
    -h "Cache-Control:no-cache, no-store, must-revalidate" \
    -h "Content-Type:text/html; charset=utf-8" \
    cp "${html_file}" "${GCS_BUCKET}/$(basename "${html_file}")"
done

# Everything else at root (favicons, robots.txt, etc.) — 1-hour cache
OTHER_FILES=()
while IFS= read -r -d '' f; do
  name="$(basename "$f")"
  if [[ "$name" != *.html && "$name" != ".gitkeep" ]]; then
    OTHER_FILES+=("$f")
  fi
done < <(find "${DIST_DIR}" -maxdepth 1 -type f -print0)

if [[ ${#OTHER_FILES[@]} -gt 0 ]]; then
  echo "  Uploading root files (1-hour cache)"
  for f in "${OTHER_FILES[@]}"; do
    gsutil \
      -h "Cache-Control:public, max-age=3600" \
      cp "$f" "${GCS_BUCKET}/$(basename "$f")"
  done
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ✓  Deploy complete"
echo ""
echo "  Public URL:"
echo "    https://storage.googleapis.com/${BUCKET_NAME}/"
echo ""
echo "  To redeploy (incremental, only changed files):"
echo "    ./scripts/deploy-gcs.sh ${BUCKET_NAME}"
echo "════════════════════════════════════════════════════════════"
