#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/volume-alert"
SERVICE="executor"
COMPOSE_FILE="$ROOT/docker-compose.yml"

REPORT_MD_HOST="$ROOT/data/reports/manager_report.md"
LOG_DIR="$ROOT/data/logs"
LOG_FILE="$LOG_DIR/manager_report_monthly.log"
LOCK_FILE="/var/lock/manager_report_monthly.lock"

MAIL_ENV="$ROOT/.reporter.env"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

# run from ROOT so docker compose always finds the compose file + relative mounts behave
cd "$ROOT"

# Prevent concurrent runs
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) [SKIP] Another run is in progress." | tee -a "$LOG_FILE"
  exit 0
fi

# Low priority
IONICE_PREFIX=()
if command -v ionice >/dev/null 2>&1; then
  IONICE_PREFIX=(ionice -c2 -n7)
fi

cexec() {
  ${IONICE_PREFIX[@]} nice -n 15 docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" sh -lc "$1"
}

# Previous calendar month in UTC (run Feb -> report for Jan)
REPORT_MONTH="$(date -u -d "$(date -u +%Y-%m-01) - 1 day" +%Y-%m)"
echo "$(date -Is) [START] monthly report for $REPORT_MONTH" | tee -a "$LOG_FILE"

# 1) Enrich (fees)
echo "$(date -Is) [STEP] enrich_trades_with_fees.py --input /data/reports/trades.jsonl --output /data/reports/trades_enriched.jsonl" | tee -a "$LOG_FILE"
cexec "python /app/tools/enrich_trades_with_fees.py --input /data/reports/trades.jsonl --output /data/reports/trades_enriched.jsonl" >>"$LOG_FILE" 2>&1

# 2) Build manager report
echo "$(date -Is) [STEP] make_manager_report.py --input /data/reports/trades_enriched.jsonl --output /data/reports/manager_report.md" | tee -a "$LOG_FILE"
cexec "python /app/tools/make_manager_report.py --input /data/reports/trades_enriched.jsonl --output /data/reports/manager_report.md" >>"$LOG_FILE" 2>&1

# Verify artifact
if [ ! -s "$REPORT_MD_HOST" ]; then
  echo "$(date -Is) [ERROR] manager_report.md not found or empty at: $REPORT_MD_HOST" | tee -a "$LOG_FILE"
  exit 2
fi
echo "$(date -Is) [OK] report generated: $REPORT_MD_HOST" | tee -a "$LOG_FILE"

# 3) Optional email (host)
if [ -f "$MAIL_ENV" ]; then
  # export vars for python
  set -a
  # shellcheck disable=SC1090
  source "$MAIL_ENV"
  set +a

  : "${SMTP_HOST:=smtp.gmail.com}"
  : "${SMTP_PORT:=587}"
  : "${MAIL_SUBJECT_PREFIX:=Bot Manager Report}"

  if [ -n "${SMTP_USER:-}" ] && [ -n "${SMTP_PASS:-}" ] && [ -n "${MAIL_FROM:-}" ] && [ -n "${MAIL_TO:-}" ]; then
    echo "$(date -Is) [STEP] send email to $MAIL_TO" | tee -a "$LOG_FILE"

    python3 - <<PY >>"$LOG_FILE" 2>&1
import os, smtplib, ssl
from email.message import EmailMessage
from pathlib import Path

month = os.environ.get("REPORT_MONTH", "$REPORT_MONTH")
smtp_host = os.environ.get("SMTP_HOST", "$SMTP_HOST")
smtp_port = int(os.environ.get("SMTP_PORT", "$SMTP_PORT"))

smtp_user = os.environ["SMTP_USER"]
smtp_pass = os.environ["SMTP_PASS"]
mail_from = os.environ["MAIL_FROM"]
mail_to   = os.environ["MAIL_TO"]
prefix    = os.environ.get("MAIL_SUBJECT_PREFIX", "$MAIL_SUBJECT_PREFIX")

report_path = Path("$REPORT_MD_HOST")
data = report_path.read_bytes()

msg = EmailMessage()
msg["Subject"] = f"{prefix} — {month}"
msg["From"] = mail_from
msg["To"] = mail_to
msg.set_content(f"Monthly manager report for {month}.\nAttached: {report_path.name}\n")
msg.add_attachment(data, maintype="text", subtype="markdown", filename=report_path.name)

ctx = ssl.create_default_context()
with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
    s.ehlo()
    s.starttls(context=ctx)
    s.login(smtp_user, smtp_pass)
    s.send_message(msg)

print("EMAIL_SENT")
PY

    echo "$(date -Is) [OK] email sent" | tee -a "$LOG_FILE"
  else
    echo "$(date -Is) [WARN] MAIL_ENV present, but SMTP_USER/SMTP_PASS/MAIL_FROM/MAIL_TO not set -> skip email" | tee -a "$LOG_FILE"
  fi
else
  echo "$(date -Is) [INFO] $MAIL_ENV not found -> skip email" | tee -a "$LOG_FILE"
fi

echo "$(date -Is) [DONE] monthly report flow finished" | tee -a "$LOG_FILE"
