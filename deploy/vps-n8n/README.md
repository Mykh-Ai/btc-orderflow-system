# VPS-n8n: private n8n and internal Buyer routing

This deployment overlay belongs to the runtime at `/root/volume-alert` on
`VPS-n8n` (`95.216.139.172`). The existing base Compose file and real `.env`
files remain private on the VPS; do not commit their resolved contents.

## Scope

- Keep n8n at the already deployed **1.122.5** image and digest.
- Keep all four active workflow IDs, paths, and production node definitions.
- Keep three existing producers on `http://n8n:5678`.
- Change only Buyer's webhook origin from the public IP to Docker DNS, keeping
  its private path and `DRY_RUN=1` unchanged.
- When the Access and HTTPS acceptance gate passes, bind host `5678` only to
  `127.0.0.1` and configure n8n's public URLs and secure cookies for HTTPS.
- Do not restart Executor, DeltaScout, the collector, or the aggregator.
- Do not upgrade n8n, reboot the VPS, or change SSH settings.

## Private deployment input

Copy `n8n-security.env.example` to
`/root/volume-alert/.n8n-security.env`, mode `0600`. Set the existing Buyer
webhook URL with origin `http://n8n:5678` and its unchanged private path.
Never put a real webhook path, password, API token, database, or encryption key
in this repository. Use the existing persistent n8n data directory.

Use this overlay for every subsequent n8n/Buyer deployment. A base-only
`docker compose -f /root/volume-alert/docker-compose.yml up` ignores it and
can revert the security settings. The wrapper always uses both files.

```sh
bash deploy/vps-n8n/apply-n8n-security.sh validate
bash deploy/vps-n8n/apply-n8n-security.sh buyer
```

The `buyer` operation changes only that service and uses the already installed
image. Compare resolved environment against the current inspect first; only
`N8N_WEBHOOK_URL` may change. Preserve all existing volumes, networks, and
restart policy. Check that Buyer has no open position and that its persistent
dedup state is retained before its brief restart.

## HTTPS and Access gate

1. Activate **Cloudflare Zero Trust Free** in the account if needed. Activation
   may require the account owner to enter billing details and accept terms.
   Do not treat selecting the free plan as completed activation.
2. Protect the whole `n8n.zevsflow.sk` hostname with Cloudflare Access. Allow
   only the existing n8n owner, not all users of an email domain. Retain n8n's
   normal email/password login behind Access.
3. On the existing **officeflow-android-pilot-api** Tunnel, add
   `n8n.zevsflow.sk -> http://127.0.0.1:5678`. The connector uses host networking;
   a bridge-network replica's localhost would be wrong. Preserve the existing
   API rule and final `http_status:404` rule.
4. Add an explicit proxied `n8n` CNAME for that Tunnel. Preserve unrelated DNS
   and the main `zevsflow.sk` Worker. The existing wildcard reaches a legacy
   parking page, so a plain `200` from this hostname is not sufficient.
5. Check HTTPS certificate validation, Access denial without a session, owner
   login, the actual n8n editor, and the editor's live connection. Verify the
   returned version is **1.122.5**, not parking HTML.
6. Confirm all four internal producer routes and isolated workflow tests.
   Only then run the n8n operation:

```sh
N8N_HTTPS_ACCEPTED=1 bash deploy/vps-n8n/apply-n8n-security.sh n8n
```

The wrapper refuses this operation without an Access login redirect. It does
not substitute for a real owner login/editor acceptance check.

## Webhook access model

All four known producers run on this VPS and share `volume-alert_default`.
They use private Docker HTTP and do not need public webhook ingress or a
Cloudflare Access bypass. Protect the entire external hostname, including
`/webhook/*`. Do not add a catch-all unauthenticated bypass.

If a new external producer is required, identify its exact path and configure
machine authentication for that path before enabling it. Do not expose all
four production webhook paths to make one integration work.

## Parameters for the installed version

n8n **1.122.5** uses `WEBHOOK_URL`; do not blindly use the replacement
`N8N_WEBHOOK_URL` from later n8n versions. Keep internal port `5678` while
setting public host/protocol/editor/webhook URLs to HTTPS.
`N8N_PROXY_HOPS=1` trusts the origin proxy (`cloudflared`); confirm forwarded
headers along the actual path. Basic Auth environment variables are obsolete
in n8n 1.x and are removed by the overlay; User Management remains active.

## Validation and rollback

Before any change, create a root-only config/inspect backup and a consistent
SQLite online backup, including the persistent encryption-key configuration.
Record IDs/PIDs/StartedAt of unrelated containers.

For no-send workflow acceptance, use an isolated copy of the same n8n image and
database with **no default network route**, no credential rows, no published
ports, and Telegram nodes replaced only in that copy by expression-rendering
Set nodes. Wait for all four webhook registrations before posting synthetic
payloads. Require `200`, successful execution, and a suppressed-delivery marker
for each workflow. Never modify the four production workflows just to suppress
test delivery.

After migration, require:

- Four registered active production webhooks with unchanged node definitions.
- Internal `/healthz` `200` from all four producers.
- HTTPS owner/editor acceptance and Access denial without a session.
- No host binding on `0.0.0.0:5678` or `[::]:5678`.
- Independent IPv4 and IPv6 connection failure to the VPS public port.
- Stable IDs/PIDs/StartedAt for unrelated containers.

If HTTPS or owner access fails, stop before closing the public port. If a
post-recreate check fails, restore the saved private config and recreate only
the affected n8n/Buyer service with the preserved image. Do not roll back
workflow data automatically: ordinary production executions may have occurred
since the backup. Keep direct SSH available throughout.
