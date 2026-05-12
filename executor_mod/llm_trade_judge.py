"""LLM Trade Judge foundation.

Patch 1 is intentionally stub-only: no external LLM/API calls and no Telegram.
The durable artifact is an append-only JSONL verdict journal.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

ENV: Dict[str, Any] = {
    "SYMBOL": os.getenv("SYMBOL", "BTCUSDC"),
    "LLM_TRADE_JUDGE_ENABLED": os.getenv("LLM_TRADE_JUDGE_ENABLED", "false"),
    "LLM_TRADE_JUDGE_VERDICTS_FN": os.getenv("LLM_TRADE_JUDGE_VERDICTS_FN", "/data/state/llm_trade_verdicts.jsonl"),
    "LLM_TRADE_JUDGE_MODE": os.getenv("LLM_TRADE_JUDGE_MODE", "stub"),
}

save_state: Optional[Callable[[dict], None]] = None
log_event: Optional[Callable[..., None]] = None


def configure(
    env: Dict[str, Any],
    *,
    save_state_fn: Optional[Callable[[dict], None]] = None,
    log_event_fn: Optional[Callable[..., None]] = None,
) -> None:
    global ENV, save_state, log_event
    ENV = env
    save_state = save_state_fn
    log_event = log_event_fn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled() -> bool:
    raw = ENV.get("LLM_TRADE_JUDGE_ENABLED", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _journal_path() -> str:
    return str(ENV.get("LLM_TRADE_JUDGE_VERDICTS_FN") or "/data/state/llm_trade_verdicts.jsonl")


def get_trade_key(pos: Dict[str, Any]) -> Optional[str]:
    if not isinstance(pos, dict):
        return None
    for key in ("trade_key", "client_id", "clientOrderId", "order_id", "orderId"):
        value = pos.get(key)
        if value:
            return str(value)
    return None


def choose_analysis_cutoff(pos: Dict[str, Any]) -> Dict[str, Any]:
    data_gaps = []
    src_evt = pos.get("src_evt") if isinstance(pos, dict) else None
    if isinstance(src_evt, dict) and src_evt.get("ts"):
        ts = src_evt.get("ts")
        return {
            "peak_ts": ts,
            "analysis_cutoff_ts": ts,
            "cutoff_source": "position.src_evt.ts",
            "data_gaps": data_gaps,
        }

    fallback_ts = None
    if isinstance(pos, dict):
        fallback_ts = pos.get("filled_at") or pos.get("opened_at")
    if fallback_ts:
        return {
            "peak_ts": None,
            "analysis_cutoff_ts": fallback_ts,
            "cutoff_source": "entry_ts_fallback",
            "data_gaps": data_gaps,
        }

    data_gaps.append("missing_analysis_cutoff_ts")
    return {
        "peak_ts": None,
        "analysis_cutoff_ts": None,
        "cutoff_source": "missing",
        "data_gaps": data_gaps,
    }


def _direction(side: Any, src_evt: Dict[str, Any]) -> Optional[str]:
    kind = str(src_evt.get("kind") or "").strip().lower()
    if kind in ("long", "short"):
        return kind
    side_u = str(side or "").strip().upper()
    if side_u == "LONG":
        return "long"
    if side_u == "SHORT":
        return "short"
    return None


def build_pretrade_evidence_pack(pos: Dict[str, Any], st: Dict[str, Any], trigger: str) -> Dict[str, Any]:
    src_evt = pos.get("src_evt") if isinstance(pos.get("src_evt"), dict) else {}
    prices = pos.get("prices") if isinstance(pos.get("prices"), dict) else {}
    orders = pos.get("orders") if isinstance(pos.get("orders"), dict) else {}
    cutoff = choose_analysis_cutoff(pos)
    baseline = st.get("baseline") if isinstance(st, dict) and isinstance(st.get("baseline"), dict) else {}

    pack = {
        "schema_version": "llm_trade_judge_open_v1",
        "trigger": trigger,
        "trade_key": get_trade_key(pos),
        "symbol": pos.get("symbol") or (st.get("symbol") if isinstance(st, dict) else None) or ENV.get("SYMBOL"),
        "direction": _direction(pos.get("side"), src_evt),
        "qty": pos.get("qty"),
        "entry": pos.get("entry") or prices.get("entry"),
        "entry_actual": pos.get("entry_actual"),
        "prices": {
            "entry": prices.get("entry"),
            "sl": prices.get("sl"),
            "tp1": prices.get("tp1"),
            "tp2": prices.get("tp2"),
        },
        "orders": {
            "sl": orders.get("sl"),
            "tp1": orders.get("tp1"),
            "tp2": orders.get("tp2"),
        },
        "src_evt": src_evt,
        "opened_at": pos.get("opened_at"),
        "filled_at": pos.get("filled_at"),
        "peak_ts": cutoff.get("peak_ts"),
        "analysis_cutoff_ts": cutoff.get("analysis_cutoff_ts"),
        "cutoff_source": cutoff.get("cutoff_source"),
        "data_gaps": list(cutoff.get("data_gaps") or []),
    }

    for key in ("client_id", "order_id", "entry_mode", "executedQty", "cummulativeQuoteQty", "k_entry"):
        if key in pos:
            pack[key] = pos.get(key)
    if isinstance(baseline.get("active"), dict):
        pack["baseline"] = {"active": baseline.get("active")}
    if "kind" in src_evt:
        pack["src_evt_kind"] = src_evt.get("kind")
    if "price_usdt" in src_evt:
        pack["src_evt_price_usdt"] = src_evt.get("price_usdt")
    return pack


def append_jsonl(path: str, record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        return {"status": "ok", "path": path}
    except Exception as exc:
        return {"status": "error", "path": path, "error": str(exc)}


def has_primary_verdict(journal_path: str, trade_key: str) -> bool:
    if not trade_key:
        return False
    try:
        with open(journal_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("trade_key") == trade_key and obj.get("is_primary") is True:
                    return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return False


def append_stub_pretrade_verdict(journal_path: str, evidence_pack: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "schema_version": "llm_trade_judge_verdict_v1",
        "verdict_id": f"stub-{uuid.uuid4().hex}",
        "created_at": _now_iso(),
        "trade_key": evidence_pack.get("trade_key"),
        "trigger": evidence_pack.get("trigger") or "EXITS_PLACED_V15",
        "is_primary": True,
        "model": None,
        "llm_call_status": "disabled",
        "verdict": "STUB_NOT_CALLED",
        "competitive_side": None,
        "confidence": None,
        "setup_class": None,
        "reason_codes": [],
        "risk_flags": [],
        "summary_ua": None,
        "evidence_pack": evidence_pack,
    }
    result = append_jsonl(journal_path, record)
    result["record"] = record
    if result.get("status") == "ok":
        result["verdict_id"] = record["verdict_id"]
    return result


def maybe_record_llm_pretrade_stub(st: Dict[str, Any], pos: Dict[str, Any], trigger: str = "EXITS_PLACED_V15") -> Dict[str, Any]:
    try:
        if not _is_enabled():
            return {"status": "noop", "reason": "disabled"}
        if str(ENV.get("LLM_TRADE_JUDGE_MODE") or "stub").strip().lower() != "stub":
            return {"status": "noop", "reason": "non_stub_mode"}
        if not isinstance(pos, dict) or str(pos.get("status") or "").upper() != "OPEN":
            return {"status": "noop", "reason": "position_not_open"}
        if not pos.get("orders"):
            return {"status": "noop", "reason": "missing_orders"}

        trade_key = get_trade_key(pos)
        if not trade_key:
            return {"status": "noop", "reason": "missing_trade_key"}

        journal_path = _journal_path()
        if has_primary_verdict(journal_path, trade_key):
            return {"status": "noop", "reason": "duplicate_primary", "trade_key": trade_key}

        evidence_pack = build_pretrade_evidence_pack(pos, st, trigger)
        result = append_stub_pretrade_verdict(journal_path, evidence_pack)
        if result.get("status") != "ok":
            if log_event:
                log_event("LLM_TRADE_JUDGE_WRITE_ERROR", trade_key=trade_key, error=result.get("error"))
            return result

        llm_state = st.setdefault("llm", {})
        pretrade_done = llm_state.setdefault("pretrade_done", {})
        pretrade_done[trade_key] = result.get("verdict_id")
        if save_state:
            try:
                save_state(st)
            except Exception as exc:
                result["state_marker_error"] = str(exc)
        if log_event:
            log_event("LLM_TRADE_JUDGE_STUB_RECORDED", trade_key=trade_key, verdict_id=result.get("verdict_id"))
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def classify_lifecycle(tp1_done: Any, tp2_done: Any, sl_done: Any, trail_active: Any, reason: Any) -> str:
    tp1 = bool(tp1_done)
    tp2 = bool(tp2_done)
    sl = bool(sl_done)
    if not tp1 and not tp2 and sl:
        return "plain_sl"
    if tp1 and not tp2 and sl:
        return "tp1_sl"
    if tp1 and tp2:
        return "tp1_tp2_trailing_stop"
    return "manual_or_unknown"


def score_llm_vs_bot(verdict: Any, lifecycle_class: str) -> Dict[str, Any]:
    verdict_u = str(verdict or "").strip().upper()
    lifecycle = str(lifecycle_class or "")
    if verdict_u == "STUB_NOT_CALLED":
        return {"applies": False, "llm_points": 0, "bot_points": 0, "alignment_score": None}

    competitive = {
        ("REJECT", "plain_sl"): (2, 0),
        ("REJECT", "tp1_sl"): (1, 0),
        ("REJECT", "tp1_tp2_trailing_stop"): (0, 2),
        ("UNCLEAR", "plain_sl"): (1, 0),
        ("UNCLEAR", "tp1_sl"): (0, 1),
        ("UNCLEAR", "tp1_tp2_trailing_stop"): (0, 2),
    }
    if (verdict_u, lifecycle) in competitive:
        llm_points, bot_points = competitive[(verdict_u, lifecycle)]
        return {
            "applies": True,
            "competitive": True,
            "llm_points": llm_points,
            "bot_points": bot_points,
            "alignment_score": None,
        }

    alignment = {
        ("SUPPORT", "plain_sl"): -2,
        ("SUPPORT", "tp1_sl"): 1,
        ("SUPPORT", "tp1_tp2_trailing_stop"): 2,
    }
    if (verdict_u, lifecycle) in alignment:
        return {
            "applies": True,
            "competitive": False,
            "llm_points": 0,
            "bot_points": 0,
            "alignment_score": alignment[(verdict_u, lifecycle)],
        }

    return {"applies": False, "llm_points": 0, "bot_points": 0, "alignment_score": None}
