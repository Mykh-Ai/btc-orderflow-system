"""Use a server-held API key without transferring it to the local runner."""
from __future__ import annotations

import base64
import json
import subprocess
from typing import Any


_REMOTE_CODE = r'''
import json
import os
import sys
import urllib.error
import urllib.request

request_data = json.load(sys.stdin)
key = os.environ.get("OPENAI_API_KEY", "").strip()
if not key:
    with open("/root/volume-alert/.executor.env", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("OPENAI_API_KEY="):
                key = line.partition("=")[2].strip()
                if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
                    key = key[1:-1]
                break
if not key:
    raise RuntimeError("server OPENAI_API_KEY absent")
if request_data.get("preflight"):
    probe = urllib.request.Request(
        "https://api.openai.com/v1/models/gpt-5.6-sol",
        headers={"Authorization": "Bearer " + key}, method="GET",
    )
    try:
        with urllib.request.urlopen(probe, timeout=30) as response:
            probe_status = int(response.status)
    except urllib.error.HTTPError as exc:
        probe_status = int(exc.code)
    print(json.dumps({"key_present": True, "model_probe_http_status": probe_status}))
    sys.exit(0)
payload = request_data["payload"]
request = urllib.request.Request(
    "https://api.openai.com/v1/responses",
    data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=300) as response:
        body = response.read().decode("utf-8")
        status = int(response.status)
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    status = int(exc.code)
try:
    parsed = json.loads(body)
except json.JSONDecodeError:
    parsed = {"unparsed_error_body": body}
print(json.dumps({"http_status": status, "body": parsed}, ensure_ascii=False))
'''


def call_on_server(host: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], int | None]:
    encoded = base64.b64encode(_REMOTE_CODE.encode("utf-8")).decode("ascii")
    remote_command = f'python3 -c "exec(__import__(\'base64\').b64decode(\'{encoded}\'))"'
    data = {"preflight": True} if payload is None else {"payload": payload}
    result = subprocess.run(
        ["C:/Windows/System32/OpenSSH/ssh.exe", "-F", "NUL", "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=10", host, remote_command],
        input=json.dumps(data, ensure_ascii=False), text=True, capture_output=True,
        timeout=330, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"SSH transport failed (exit={result.returncode}): {result.stderr.strip()[-500:]}")
    response = json.loads(result.stdout)
    if payload is None:
        if not response.get("key_present") or response.get("model_probe_http_status") != 200:
            raise RuntimeError(f"server model preflight failed: HTTP {response.get('model_probe_http_status')}")
        return response, None
    return response["body"], int(response["http_status"])
