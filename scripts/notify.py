#!/usr/bin/env python3
"""
notify.py — pipeline success/failure email notifier
=====================================================

Sends a plain-text email to ``NOTIFY_EMAIL_TO`` via the SMTP server configured
in environment variables. Designed to be called by ``scripts/cron_refresh.sh``
at the end of each daily run.

Graceful degradation: if SMTP isn't configured, the script writes a record to
``logs/notifications.log`` and exits 0 — it MUST NOT fail the pipeline.

Usage:
    python scripts/notify.py --mode success --body-file logs/pipeline-2026-05-27.log
    python scripts/notify.py --mode failure --body-file logs/pipeline-2026-05-27.log
    python scripts/notify.py --mode success --subject "Custom" --body "Inline body text"

Required env vars (when actually sending email):
    SMTP_HOST          smtp.gmail.com, smtp-mail.outlook.com, etc.
    SMTP_PORT          587 (STARTTLS) or 465 (SMTP_SSL)
    SMTP_USER          your account on the SMTP server
    SMTP_PASSWORD      account password or app-specific password
    SMTP_FROM          (optional) From: address — defaults to SMTP_USER
    NOTIFY_EMAIL_TO    recipient — defaults to praveer@chromadata.com

Returns 0 in all expected cases (success, dry-fallback, SMTP soft failure).
Returns 2 only on argument errors.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT     = Path(__file__).parent.parent
LOG_DIR  = ROOT / "logs"

DEFAULT_TO = "praveer@chromadata.com"

log = logging.getLogger(__name__)


# ── Body composition ─────────────────────────────────────────────────────────

def _extract_pipeline_summary(log_text: str) -> str:
    """Pull the human-readable Pipeline Summary block + a tail of the log."""
    summary_lines: list[str] = []
    capturing = False
    for line in log_text.splitlines():
        if "Pipeline Summary" in line:
            capturing = True
        if capturing:
            summary_lines.append(line)
            if line.strip().endswith("═" * 5) and len(summary_lines) > 3:
                # Trailing rule that closes the summary section
                break
    if summary_lines:
        return "\n".join(summary_lines)
    # Fallback: last 60 lines of log
    return "\n".join(log_text.splitlines()[-60:])


def _failure_excerpt(log_text: str) -> str:
    """For failure emails: the Pipeline Summary if present, plus the last 60 log lines so the cause is visible."""
    parts = [_extract_pipeline_summary(log_text), "", "── Last 60 lines ─────────────────────────────────"]
    parts.extend(log_text.splitlines()[-60:])
    return "\n".join(parts)


def compose_body(mode: str, body_arg: str | None, body_file: Path | None) -> str:
    if body_arg:
        return body_arg
    if body_file and body_file.exists():
        text = body_file.read_text(errors="replace")
        if mode == "success":
            return _extract_pipeline_summary(text)
        return _failure_excerpt(text)
    return "(no log content available)"


# ── Email sending ────────────────────────────────────────────────────────────

def send_email(*, to: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Returns (ok, detail).
    Soft-fails (returns False) when SMTP isn't configured or transport breaks —
    the caller should write to the local notifications log in that case.
    """
    host = os.environ.get("SMTP_HOST", "").strip()
    port_str = os.environ.get("SMTP_PORT", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pwd  = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", user).strip()

    if not (host and port_str and user and pwd and sender):
        return False, "SMTP not configured (one or more of SMTP_HOST/PORT/USER/PASSWORD missing)"

    try:
        port = int(port_str)
    except ValueError:
        return False, f"SMTP_PORT not a number: {port_str!r}"

    msg = EmailMessage()
    msg["From"]    = sender
    msg["To"]      = to
    msg["Subject"] = subject
    msg.set_content(body)

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pwd)
                s.send_message(msg)
    except (smtplib.SMTPException, ssl.SSLError, socket.error, OSError) as exc:
        return False, f"SMTP send failed: {exc}"
    return True, f"sent to {to} via {host}:{port}"


def _local_fallback_log(subject: str, body: str, detail: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOG_DIR / "notifications.log"
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    with f.open("a") as fh:
        fh.write(f"\n========== {stamp} ==========\n")
        fh.write(f"SUBJECT: {subject}\n")
        fh.write(f"DELIVERY: {detail}\n")
        fh.write(f"BODY:\n{body}\n")


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send pipeline success/failure email")
    parser.add_argument("--mode",    choices=("success", "failure"), required=True)
    parser.add_argument("--to",      default=os.environ.get("NOTIFY_EMAIL_TO", DEFAULT_TO))
    parser.add_argument("--subject", default=None,
                        help="Override subject (default: auto-generated from mode)")
    parser.add_argument("--body",    default=None,
                        help="Inline body text")
    parser.add_argument("--body-file", type=Path, default=None,
                        help="Read body from this log file (preferred)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s  %(message)s",
    )

    today = _dt.date.today().isoformat()
    if args.subject:
        subject = args.subject
    elif args.mode == "success":
        subject = f"[sme_artistTracker] Daily refresh OK — {today}"
    else:
        subject = f"[sme_artistTracker] FAILED — {today}"

    body = compose_body(args.mode, args.body, args.body_file)

    # Always prepend a small header so the email is readable on its own.
    header = (
        f"Host:        {socket.gethostname()}\n"
        f"Project:     {ROOT}\n"
        f"Mode:        {args.mode}\n"
        f"Date:        {today}\n"
        f"────────────────────────────────────────────────────────\n"
    )
    full_body = header + body

    ok, detail = send_email(to=args.to, subject=subject, body=full_body)
    if ok:
        log.info("Email sent: %s", detail)
    else:
        log.warning("Email NOT sent — %s  (writing to logs/notifications.log)", detail)
        _local_fallback_log(subject, full_body, detail)

    # Notification failures must never break the pipeline.
    return 0


if __name__ == "__main__":
    sys.exit(main())
