#!/usr/bin/env bash
# ============================================================================
# Daily refresh wrapper for sme_artistTracker.
#
# Run automatically by launchd via:
#   ~/Library/LaunchAgents/com.chromadata.smetracker.plist
#
# Run manually for testing:
#   bash /Users/praveer/sme_artistTracker/scripts/cron_refresh.sh
#
# What it does:
#   1. cd to project root
#   2. Load secrets from .env (ANTHROPIC_API_KEY etc.) — keeps them out of the plist
#   3. Inject npm/node/system paths (launchd starts with a minimal PATH)
#   4. Run `npm run build:full` (full data pipeline + dist/ rebuild)
#   5. Log everything to logs/pipeline-YYYY-MM-DD.log
# ============================================================================

set -uo pipefail

PROJECT_ROOT="/Users/praveer/sme_artistTracker"
LOG_DIR="$PROJECT_ROOT/logs"
TODAY="$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/pipeline-$TODAY.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT" || { echo "FATAL: cannot cd $PROJECT_ROOT"; exit 2; }

# ── Load secrets from .env (kept out of plist) ────────────────────────────────
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# .env stores the Anthropic key as VITE_ANTHROPIC_API_KEY (for the Vite frontend).
# generate_news.py reads ANTHROPIC_API_KEY (no prefix). Bridge them here so the
# launchd run gets the same key the interactive shell has.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${VITE_ANTHROPIC_API_KEY:-}" ]; then
    export ANTHROPIC_API_KEY="$VITE_ANTHROPIC_API_KEY"
fi

# ── Restore PATH (launchd's default doesn't include nvm/homebrew/venv) ────────
export PATH="/Users/praveer/.nvm/versions/node/v23.8.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# ── Run pipeline with logging ─────────────────────────────────────────────────
{
  echo "============================================================="
  echo "  Refresh start: $(date -Iseconds)"
  echo "  PATH=$PATH"
  echo "  ANTHROPIC_API_KEY set: $([ -n "${ANTHROPIC_API_KEY:-}" ] && echo yes || echo NO)"
  echo "============================================================="
} | tee -a "$LOG_FILE"

npm run build:full >> "$LOG_FILE" 2>&1
EXIT=$?

{
  echo ""
  echo "============================================================="
  echo "  Refresh end:   $(date -Iseconds)  exit=$EXIT"
  echo "============================================================="
} | tee -a "$LOG_FILE"

# ── Notifications ─────────────────────────────────────────────────────────────
# Failure → always email.
# Success → email daily through SUCCESS_EMAIL_UNTIL (initial 15-day window),
#           after which success runs are silent.
# Notification failures never affect the pipeline exit code.

SUCCESS_EMAIL_UNTIL="${SUCCESS_EMAIL_UNTIL:-2026-06-10}"
TODAY_DATE="$(date +%Y-%m-%d)"

if [ "$EXIT" -ne 0 ]; then
    .venv/bin/python scripts/notify.py \
        --mode failure \
        --body-file "$LOG_FILE" \
        2>>"$LOG_FILE" || true
elif [[ "$TODAY_DATE" < "$SUCCESS_EMAIL_UNTIL" || "$TODAY_DATE" == "$SUCCESS_EMAIL_UNTIL" ]]; then
    .venv/bin/python scripts/notify.py \
        --mode success \
        --body-file "$LOG_FILE" \
        2>>"$LOG_FILE" || true
fi

# ── Light log retention: keep last 30 days, prune older ───────────────────────
find "$LOG_DIR" -name "pipeline-*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT
