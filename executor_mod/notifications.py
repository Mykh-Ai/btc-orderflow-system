from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


ENV: Dict[str, Any] = {
    "EXEC_LOG": os.getenv("EXEC_LOG", "/data/logs/executor.log"),
    "LOG_MAX_LINES": _get_int("LOG_MAX_LINES", 200),
    "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
    "N8N_BASIC_AUTH_USER": os.getenv("N8N_BASIC_AUTH_USER", ""),
    "N8N_BASIC_AUTH_PASSWORD": os.getenv("N8N_BASIC_AUTH_PASSWORD", ""),
}


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat()


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def append_line_with_cap(path: str, line: str, cap: int) -> None:
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > cap:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-cap:])
    except FileNotFoundError:
        pass


def log_event(action: str, **fields: Any) -> None:
    obj = {"ts": iso_utc(), "source": "executor", "action": action}
    obj.update(fields)
    append_line_with_cap(
        ENV["EXEC_LOG"],
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str),
        ENV["LOG_MAX_LINES"],
    )


def send_webhook(payload: Dict[str, Any]) -> None:
    url = ENV["N8N_WEBHOOK_URL"]
    if not url:
        return

    payload = dict(payload)
    payload.setdefault("source", "executor")

    try:
        auth = None
        if ENV["N8N_BASIC_AUTH_USER"] and ENV["N8N_BASIC_AUTH_PASSWORD"]:
            auth = (ENV["N8N_BASIC_AUTH_USER"], ENV["N8N_BASIC_AUTH_PASSWORD"])
        requests.post(url, json=payload, timeout=5, auth=auth)
    except Exception as e:
        log_event("WEBHOOK_ERROR", error=str(e), payload=payload)
