# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import inspect
import json
import math
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable

import pandas as pd

# injected from executor.py via configure()
_ENV: Optional[Dict[str, Any]] = None
_iso_utc: Optional[Callable[[], str]] = None
_save_state: Optional[Callable[[Dict[str, Any]], None]] = None
_log_event: Optional[Callable[..., None]] = None


def configure(
    env: Dict[str, Any],
    *,
    iso_utc: Callable[[], str],
    save_state: Callable[[Dict[str, Any]], None],
    log_event: Callable[..., None],
) -> None:
    """
    Executor must call this ONCE at startup.
    We keep call sites unchanged and avoid circular imports.
    """
    global _ENV, _iso_utc, _save_state, _log_event
    _ENV = env
    _iso_utc = iso_utc
    _save_state = save_state
    _log_event = log_event


def _require() -> Dict[str, Any]:
    if _ENV is None or _iso_utc is None or _save_state is None or _log_event is None:
        raise RuntimeError("event_dedup not configured: call event_dedup.configure(...) in executor.py")
    return _ENV


def _ts_norm(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        with suppress(Exception):
            return pd.to_datetime(s, utc=True).isoformat()
        return s
    with suppress(Exception):
        return pd.to_datetime(ts, utc=True).isoformat()
    return None


def stable_event_key(evt: Dict[str, Any]) -> Optional[str]:
    env = _require()

    if not isinstance(evt, dict):
        return None

    if evt.get("action") != "PEAK":
        return None

    if env.get("STRICT_SOURCE") and evt.get("source") != "DeltaScout":
        return None

    kind = str(evt.get("kind") or "").strip().lower()
    if kind not in ("long", "short"):
        return None

    ts = _ts_norm(evt.get("ts"))
    if not ts:
        return None

    # bucket minute (stable across small ts jitter)
    minute = ts[:16]  # YYYY-MM-DDTHH:MM

    price = evt.get("price")
    with suppress(Exception):
        price = float(price)
    if not isinstance(price, (int, float)):
        return None

    dec = int(env.get("DEDUP_PRICE_DECIMALS", 2))
    step = 10 ** dec
    price_r = math.floor(price * step + 0.5) / step  # round half up-ish

    return f"{evt.get('action')}|{minute}|{kind}|{price_r:.{dec}f}"


def dedup_fingerprint() -> str:
    env = _require()
    src = inspect.getsource(stable_event_key)
    payload = (
        f"dedup_v1|{src}|DEDUP_PRICE_DECIMALS={env.get('DEDUP_PRICE_DECIMALS')}"
        f"|STRICT_SOURCE={env.get('STRICT_SOURCE')}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dt_utc(s: Any):
    if s is None:
        return None
    with suppress(Exception):
        return pd.to_datetime(s, utc=True).to_pydatetime()
    return None


def bootstrap_seen_keys_from_tail(st: Dict[str, Any], tail_lines: List[str]) -> None:
    env = _require()
    assert _iso_utc is not None and _save_state is not None and _log_event is not None

    meta = st.setdefault("meta", {})

    fp_now = dedup_fingerprint()
    if meta.get("dedup_fp") != fp_now:
        meta["seen_keys"] = []
        meta["dedup_fp"] = fp_now

    seen = set(meta.get("seen_keys") or [])
    added = 0

    for line in tail_lines[-300:]:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        with suppress(Exception):
            evt = json.loads(line)
        if not isinstance(evt, dict):
            continue
        key = stable_event_key(evt)
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            added += 1

    meta["seen_keys"] = list(seen)[-int(env.get("SEEN_KEYS_MAX", 500)):]
    meta["dedup_fp"] = fp_now
    meta["boot_ts"] = _iso_utc()

    _save_state(st)

    _log_event(
        "BOOTSTRAP_SEEN_KEYS",
        added=added,
        total=len(meta["seen_keys"]),
        last_peak_ts=meta.get("last_peak_ts"),
        dedup_fp=meta.get("dedup_fp"),
    )

    
