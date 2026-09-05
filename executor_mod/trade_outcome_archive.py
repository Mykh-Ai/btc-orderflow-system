"""trade_outcome_archive.py

Append-only JSONL raw outcome journal for closed trades.
One record per closure episode, written best-effort after last_closed is set.

Path: /data/state/trade_outcomes.jsonl  (configurable via TRADE_OUTCOMES_FN env var)
Consumers: DeltaScout offline, FinAnalytics.

This is a raw operational artifact, not a dataset. Downstream layers build
their own research datasets by reading this journal independently.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

SCHEMA_VERSION = "trade_outcome_v1"
DEFAULT_PATH = "/data/state/trade_outcomes.jsonl"


def _outcome_path() -> str:
    return os.getenv("TRADE_OUTCOMES_FN", DEFAULT_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_default(obj: Any) -> Any:
    """JSON fallback: non-serialisable values become their str()."""
    try:
        return str(obj)
    except Exception:
        return None


def record_outcome(st: Dict[str, Any], source: str, symbol: str) -> None:
    """Append a TRADE_OUTCOME record to the raw outcome journal.

    Reads ``st["last_closed"]`` as the closure snapshot; that field must
    already be written by the caller before this function is invoked.

    Best-effort: all exceptions are swallowed and logged; never raises into
    the trading / finalization flow.

    Args:
        st:      executor state dict (last_closed must already be set)
        source:  insertion-point label, e.g. ``"_close_slot"``
        symbol:  trading symbol, e.g. ``"BTCUSDC"``
    """
    try:
        last_closed = st.get("last_closed")
        if not last_closed:
            return  # nothing to archive — skip silently

        ts = (
            last_closed.get("ts") if isinstance(last_closed, dict) else None
        ) or _now_iso()

        record = {
            "schema": SCHEMA_VERSION,
            "event": "TRADE_OUTCOME",
            "ts": ts,
            "symbol": str(symbol or ""),
            "source": str(source or ""),
            "last_closed": last_closed,
        }

        path = _outcome_path()
        line = json.dumps(record, default=_safe_default)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    except Exception as exc:
        # Best-effort: log the error but never raise into trading flow.
        try:
            from executor_mod.notifications import log_event
            log_event("TRADE_OUTCOME_WRITE_ERROR", source=str(source or ""), error=str(exc))
        except Exception:
            pass
