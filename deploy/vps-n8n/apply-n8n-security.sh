#!/usr/bin/env bash
set -euo pipefail

# Deploy only the named service. Do not rebuild or pull any application image.
action="${1:-validate}"
runtime_root="${N8N_RUNTIME_ROOT:-/root/volume-alert}"
source_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
test "$(hostname)" = VPS-n8n
test -f "$runtime_root/docker-compose.yml"
test -f "$runtime_root/.n8n-security.env"

compose=(docker compose -p volume-alert)
if test -f "$runtime_root/.env"; then
  compose+=(--env-file "$runtime_root/.env")
fi
compose+=(--env-file "$runtime_root/.n8n-security.env"
  -f "$runtime_root/docker-compose.yml"
  -f "$source_dir/n8n-security.compose.yml")
"${compose[@]}" config --quiet

case "$action" in
  validate) exit 0 ;;
  buyer) service=buyer ;;
  n8n)
    # Deployment is forbidden until the exact hostname is protected by Access.
    headers="$(curl -sS --max-time 10 -I https://n8n.zevsflow.sk/)"
    if ! printf '%s\n' "$headers" | tr -d '\r' | grep -Eiq '^location: https://[a-z0-9.-]+\.cloudflareaccess\.com/'; then
      printf '%s\n' 'Refusing n8n migration: Cloudflare Access redirect is not active.' >&2
      exit 1
    fi
    if test "${N8N_HTTPS_ACCEPTED:-}" != 1; then
      printf '%s\n' 'Verify owner login/editor and isolated webhook tests, then set N8N_HTTPS_ACCEPTED=1.' >&2
      exit 1
    fi
    service=n8n
    ;;
  *) printf '%s\n' 'Usage: apply-n8n-security.sh validate|buyer|n8n' >&2; exit 2 ;;
esac

"${compose[@]}" up -d --no-deps --no-build --pull never "$service"
