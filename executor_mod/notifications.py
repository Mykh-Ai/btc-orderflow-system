from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

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

_SNAPSHOT_OK_STATE: Dict[Tuple[str, str], bool] = {}
_SNAPSHOT_LAST_ERR_TS: Dict[Tuple[str, str, str], float] = {}
_SNAPSHOT_ERR_THROTTLE_SEC = float(os.getenv("SNAPSHOT_ERR_THROTTLE_SEC", "60"))


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


def _should_log_snapshot_refresh(action: str, fields: Dict[str, Any]) -> bool:
    if action not in ("SNAPSHOT_REFRESH", "PRICE_SNAPSHOT_REFRESH"):
        return True
    if "ok" not in fields:
        return True
    ok = fields.get("ok")
    source = fields.get("source") or "executor"
    key = (action, str(source))
    if ok is False:
        _SNAPSHOT_OK_STATE[key] = False
        err = fields.get("error")
        err_s = str(err) if err is not None else ""
        fingerprint = (err_s[:180] if err_s else "unknown")
        ekey = (action, str(source), fingerprint)
        now = time.time()
        last = float(_SNAPSHOT_LAST_ERR_TS.get(ekey) or 0.0)
        if now - last >= _SNAPSHOT_ERR_THROTTLE_SEC:
            _SNAPSHOT_LAST_ERR_TS[ekey] = now
            return True
        return False
    if ok is True:
        last_ok = _SNAPSHOT_OK_STATE.get(key)
        if last_ok is not True:
            _SNAPSHOT_OK_STATE[key] = True
            return True
        return False
    return True


def log_event(action: str, **fields: Any) -> None:
    if not _should_log_snapshot_refresh(action, fields):
        return
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


def _extract_trade_key(st: Dict[str, Any], pos: Dict[str, Any]) -> Optional[str]:
    """Best-effort trade_key extraction for dedup. Returns None if not available."""
    try:
        tk = None
        if isinstance(pos, dict):
            tk = pos.get("trade_key") or pos.get("tradeKey")
        if not tk and isinstance(st, dict):
            tk = st.get("trade_key")
            if not tk and isinstance(st.get("position"), dict):
                tk = st["position"].get("trade_key")
            if not tk and isinstance(st.get("last_closed"), dict):
                tk = st["last_closed"].get("trade_key")
        return str(tk) if tk is not None else None
    except Exception:
        return None


def send_trade_closed(st: Dict[str, Any], pos: Dict[str, Any], close_reason: str, mode: str = "live") -> None:
    """
    Single source of truth for TRADE_CLOSED webhook emission.
    - Dedup by trade_key persisted in state: st["last_notified_close_trade_key"]
    - Fail-soft: never raises; must not block close.
    """
    try:
        st = st if isinstance(st, dict) else {}
        pos = pos if isinstance(pos, dict) else {}

        trade_key = _extract_trade_key(st, pos)
        last_sent = st.get("last_notified_close_trade_key")
        if trade_key and last_sent == trade_key:
            return

        symbol = str(pos.get("symbol") or st.get("symbol") or os.getenv("SYMBOL", "") or "")
        side = str(pos.get("side") or "")
        payload: Dict[str, Any] = {
            "event": "TRADE_CLOSED",
            "mode": mode,
            "symbol": symbol,
            "side": side,
            "trade_key": trade_key,
            "close_reason": str(close_reason or ""),
        }

        for k_src, k_out in (
            ("qty", "qty"),
            ("qty_base_total", "qty_base_total"),
            ("entry", "entry"),
            ("entry_price", "entry_price"),
            ("avg_exit_price", "avg_exit_price"),
            ("exit_price", "exit_price"),
        ):
            v = pos.get(k_src)
            if v is not None:
                payload[k_out] = v

        with suppress(Exception):
            log_event("TRADE_CLOSED", **{k: v for k, v in payload.items() if v is not None})

        send_webhook(payload)

        if trade_key:
            st["last_notified_close_trade_key"] = trade_key
    except Exception as e:
        with suppress(Exception):
            log_event("TRADE_CLOSED_NOTIFY_ERROR", error=str(e), close_reason=str(close_reason or ""))
        return
