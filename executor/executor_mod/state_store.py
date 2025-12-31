# executor_mod/state_store.py
from __future__ import annotations

import os
import json
import time
from contextlib import suppress
from typing import Any, Dict


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _state_fn() -> str:
    # Keep identical default as executor ENV["STATE_FN"]
    return os.getenv("STATE_FN", "/data/state/executor_state.json")


def load_state() -> Dict[str, Any]:
    fn = _state_fn()
    try:
        with open(fn, "r", encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    except Exception:
        st = {}

    st.setdefault("meta", {})
    st["meta"].setdefault("seen_keys", [])
    st.setdefault("position", None)
    st.setdefault("last_closed", None)
    st.setdefault("cooldown_until", 0.0)
    st.setdefault("lock_until", 0.0)
    return st


def save_state(st: Dict[str, Any]) -> None:
    fn = _state_fn()
    _ensure_dir(fn)
    tmp = fn + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, fn)


def has_open_position(st: Dict[str, Any]) -> bool:
    pos = st.get("position")
    if not pos:
        return False
    return pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED")


def in_cooldown(st: Dict[str, Any]) -> bool:
    with suppress(Exception):
        return time.time() < float(st.get("cooldown_until") or 0.0)
    return False


def locked(st: Dict[str, Any]) -> bool:
    with suppress(Exception):
        return time.time() < float(st.get("lock_until") or 0.0)
    return False
