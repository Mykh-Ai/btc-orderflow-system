"""LLM Trade Judge foundation.

The judge is advisory only. It never opens, closes, or modifies orders.
The durable artifact is an append-only JSONL verdict journal.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

ENV: Dict[str, Any] = {
    "SYMBOL": os.getenv("SYMBOL", "BTCUSDC"),
    "LLM_TRADE_JUDGE_ENABLED": os.getenv("LLM_TRADE_JUDGE_ENABLED", "false"),
    "LLM_TRADE_JUDGE_VERDICTS_FN": os.getenv("LLM_TRADE_JUDGE_VERDICTS_FN", "/data/state/llm_trade_verdicts.jsonl"),
    "LLM_TRADE_JUDGE_MODE": os.getenv("LLM_TRADE_JUDGE_MODE", "stub"),
    "LLM_TRADE_JUDGE_MODEL": os.getenv("LLM_TRADE_JUDGE_MODEL", "gpt-5.5"),
    "LLM_TRADE_JUDGE_TIMEOUT_SEC": os.getenv("LLM_TRADE_JUDGE_TIMEOUT_SEC", "20"),
    "LLM_TRADE_JUDGE_MAX_RETRIES": os.getenv("LLM_TRADE_JUDGE_MAX_RETRIES", "1"),
    "LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": os.getenv("LLM_TRADE_JUDGE_NOTIFY_TELEGRAM", "true"),
}

save_state: Optional[Callable[[dict], None]] = None
log_event: Optional[Callable[..., None]] = None
send_webhook: Optional[Callable[[dict], None]] = None
openai_client: Optional[Callable[..., Any]] = None

ALLOWED_VERDICTS = {"SUPPORT", "REJECT", "UNCLEAR"}
ALLOWED_SETUP_CLASSES = {
    "continuation_pressure",
    "reversal_onset",
    "reversal_confirmation",
    "exhaustion",
    "trap_false_break",
    "absorption_like",
    "honest_directional_flow",
    "noisy_peak",
    "unknown",
}


def configure(
    env: Dict[str, Any],
    *,
    save_state_fn: Optional[Callable[[dict], None]] = None,
    log_event_fn: Optional[Callable[..., None]] = None,
    send_webhook_fn: Optional[Callable[[dict], None]] = None,
    openai_client_fn: Optional[Callable[..., Any]] = None,
) -> None:
    global ENV, save_state, log_event, send_webhook, openai_client
    ENV = env
    save_state = save_state_fn
    log_event = log_event_fn
    send_webhook = send_webhook_fn
    openai_client = openai_client_fn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled() -> bool:
    raw = ENV.get("LLM_TRADE_JUDGE_ENABLED", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


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
    _add_required_data_gaps(pack)
    return pack


def _add_required_data_gaps(pack: Dict[str, Any]) -> None:
    gaps = list(pack.get("data_gaps") or [])

    def missing(value: Any) -> bool:
        return value is None or value == ""

    checks = {
        "missing_trade_key": pack.get("trade_key"),
        "missing_symbol": pack.get("symbol"),
        "missing_direction": pack.get("direction"),
        "missing_qty": pack.get("qty"),
        "missing_entry": pack.get("entry"),
        "missing_entry_actual": pack.get("entry_actual"),
        "missing_prices.entry": (pack.get("prices") or {}).get("entry"),
        "missing_prices.sl": (pack.get("prices") or {}).get("sl"),
        "missing_prices.tp1": (pack.get("prices") or {}).get("tp1"),
        "missing_prices.tp2": (pack.get("prices") or {}).get("tp2"),
        "missing_orders.sl": (pack.get("orders") or {}).get("sl"),
        "missing_orders.tp1": (pack.get("orders") or {}).get("tp1"),
        "missing_orders.tp2": (pack.get("orders") or {}).get("tp2"),
        "missing_src_evt": pack.get("src_evt"),
        "missing_opened_at": pack.get("opened_at"),
        "missing_filled_at": pack.get("filled_at"),
    }
    for gap, value in checks.items():
        if missing(value) and gap not in gaps:
            gaps.append(gap)
    pack["data_gaps"] = gaps


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


def _model_name() -> str:
    return str(ENV.get("LLM_TRADE_JUDGE_MODEL") or "gpt-5.5")


def _notify_enabled() -> bool:
    return _as_bool(ENV.get("LLM_TRADE_JUDGE_NOTIFY_TELEGRAM", True), True)


def _competitive_side_for_verdict(verdict: str) -> Optional[str]:
    verdict_u = str(verdict or "").strip().upper()
    if verdict_u == "SUPPORT":
        return "BOT"
    if verdict_u in ("REJECT", "UNCLEAR"):
        return "LLM_REJECT"
    return None


def _json_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": sorted(ALLOWED_VERDICTS)},
            "competitive_side": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "setup_class": {"type": "string", "enum": sorted(ALLOWED_SETUP_CLASSES)},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "summary_ua": {"type": ["string", "null"]},
        },
        "required": [
            "verdict",
            "competitive_side",
            "confidence",
            "setup_class",
            "reason_codes",
            "risk_flags",
            "summary_ua",
        ],
    }


def build_llm_trade_judge_prompt(evidence_pack: Dict[str, Any]) -> str:
    return (
        "You are LLM Trade Judge for an automated Binance execution engine.\n"
        "Judge only the trade signal quality at entry time.\n"
        "You only see information available until analysis_cutoff_ts.\n"
        "Do not infer future outcome. Do not mention whether the trade won or lost.\n"
        "The LLM is advisory only and must not suggest changing live orders.\n"
        "Return only JSON, no markdown.\n"
        "Allowed verdict values: SUPPORT, REJECT, UNCLEAR.\n"
        "SUPPORT means the bot side is favored. REJECT means reject the bot trade. "
        "UNCLEAR counts as reject-side in the game, but keep verdict UNCLEAR if edge is not clear.\n"
        "Allowed setup_class values: continuation_pressure, reversal_onset, reversal_confirmation, "
        "exhaustion, trap_false_break, absorption_like, honest_directional_flow, noisy_peak, unknown.\n"
        "Evidence pack follows:\n"
        f"{json.dumps(evidence_pack, ensure_ascii=False, separators=(',', ':'), default=str)}"
    )


def _extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        output = response.get("output")
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and isinstance(c.get("text"), str):
                            parts.append(c["text"])
                elif isinstance(content, str):
                    parts.append(content)
            if parts:
                return "\n".join(parts)
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text
    return str(response)


def call_openai_trade_judge(evidence_pack: Dict[str, Any]) -> str:
    prompt = build_llm_trade_judge_prompt(evidence_pack)
    model = _model_name()
    timeout_sec = _as_float(ENV.get("LLM_TRADE_JUDGE_TIMEOUT_SEC"), 20.0)
    max_retries = max(0, _as_int(ENV.get("LLM_TRADE_JUDGE_MAX_RETRIES"), 1))

    if openai_client is not None:
        response = openai_client(
            prompt=prompt,
            evidence_pack=evidence_pack,
            model=model,
            timeout_sec=timeout_sec,
            schema=_json_schema(),
        )
        return _extract_response_text(response)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing_openai_api_key")

    payload = {
        "model": model,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "llm_trade_judge_verdict",
                "strict": True,
                "schema": _json_schema(),
            }
        },
        "max_output_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
                timeout=timeout_sec,
            )
            if response.status_code != 200:
                raise RuntimeError(f"openai_http_{response.status_code}")
            return _extract_response_text(response.json())
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(min(1.0, 0.25 * (attempt + 1)))
                continue
            raise
    raise RuntimeError(str(last_exc) if last_exc else "openai_call_failed")


def validate_llm_verdict_json(raw_text: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    try:
        parsed = json.loads(raw_text)
    except Exception as exc:
        return None, [f"json_parse_error:{exc}"]
    if not isinstance(parsed, dict):
        return None, ["json_not_object"]

    verdict = str(parsed.get("verdict") or "").strip().upper()
    if verdict not in ALLOWED_VERDICTS:
        return None, [f"invalid_verdict:{parsed.get('verdict')}"]

    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except Exception:
            return None, ["invalid_confidence"]
        if confidence < 0.0 or confidence > 1.0:
            return None, ["invalid_confidence_range"]

    setup_class = str(parsed.get("setup_class") or "unknown").strip()
    if setup_class not in ALLOWED_SETUP_CLASSES:
        errors.append(f"unknown_setup_class:{setup_class}")
        setup_class = "unknown"

    reason_codes = parsed.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
        errors.append("invalid_reason_codes")
    risk_flags = parsed.get("risk_flags")
    if not isinstance(risk_flags, list):
        risk_flags = []
        errors.append("invalid_risk_flags")

    return {
        "verdict": verdict,
        "competitive_side": _competitive_side_for_verdict(verdict),
        "confidence": confidence,
        "setup_class": setup_class,
        "reason_codes": [str(x) for x in reason_codes],
        "risk_flags": [str(x) for x in risk_flags],
        "summary_ua": parsed.get("summary_ua") if parsed.get("summary_ua") is not None else None,
        "validation_errors": errors,
    }, errors


def _base_record(evidence_pack: Dict[str, Any], *, model: Optional[str], status: str) -> Dict[str, Any]:
    return {
        "schema_version": "llm_trade_judge_verdict_v1",
        "verdict_id": f"llmj-{uuid.uuid4().hex}",
        "created_at": _now_iso(),
        "trade_key": evidence_pack.get("trade_key"),
        "trigger": evidence_pack.get("trigger") or "EXITS_PLACED_V15",
        "is_primary": True,
        "model": model,
        "llm_call_status": status,
        "evidence_pack": evidence_pack,
    }


def build_success_verdict_record(evidence_pack: Dict[str, Any], validated: Dict[str, Any]) -> Dict[str, Any]:
    record = _base_record(evidence_pack, model=_model_name(), status="success")
    record.update({
        "verdict": validated.get("verdict"),
        "competitive_side": validated.get("competitive_side"),
        "confidence": validated.get("confidence"),
        "setup_class": validated.get("setup_class"),
        "reason_codes": validated.get("reason_codes") or [],
        "risk_flags": validated.get("risk_flags") or [],
        "summary_ua": validated.get("summary_ua"),
    })
    if validated.get("validation_errors"):
        record["validation_errors"] = validated.get("validation_errors")
    return record


def build_error_verdict_record(
    evidence_pack: Dict[str, Any],
    error_type: str,
    error_message: str,
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    record = _base_record(evidence_pack, model=model if model is not None else _model_name(), status="error")
    record.update({
        "error_type": str(error_type or "unknown_error"),
        "error_message": str(error_message or ""),
        "verdict": "ERROR_NOT_SCORED",
        "competitive_side": None,
        "confidence": None,
        "setup_class": None,
        "reason_codes": [],
        "risk_flags": [],
        "summary_ua": None,
    })
    return record


def append_real_pretrade_verdict(journal_path: str, record: Dict[str, Any]) -> Dict[str, Any]:
    result = append_jsonl(journal_path, record)
    result["record"] = record
    if result.get("status") == "ok":
        result["verdict_id"] = record["verdict_id"]
    return result


def _mark_state_done(st: Dict[str, Any], trade_key: str, verdict_id: str, result: Dict[str, Any]) -> None:
    llm_state = st.setdefault("llm", {})
    pretrade_done = llm_state.setdefault("pretrade_done", {})
    pretrade_done[trade_key] = verdict_id
    if save_state:
        try:
            save_state(st)
        except Exception as exc:
            result["state_marker_error"] = str(exc)


def _telegram_text(record: Dict[str, Any]) -> str:
    evidence = record.get("evidence_pack") if isinstance(record.get("evidence_pack"), dict) else {}
    trade_key = record.get("trade_key") or evidence.get("trade_key")
    if record.get("llm_call_status") == "error":
        return (
            "🤖 LLM Trade Judge ERROR\n\n"
            f"Trade: {trade_key}\n"
            f"Status: {record.get('llm_call_status')}\n"
            f"Reason: {record.get('error_type')}\n"
            "Execution was not affected."
        )

    lines = [
        "🤖 LLM Trade Judge",
        "",
        f"Symbol: {evidence.get('symbol')}",
        f"Direction: {str(evidence.get('direction') or '').upper()}",
        f"Trade: {trade_key}",
        f"Cutoff: {evidence.get('analysis_cutoff_ts')}",
        f"Cutoff source: {evidence.get('cutoff_source')}",
        "",
        f"Verdict: {record.get('verdict')}",
        f"Game side: {record.get('competitive_side')}",
        f"Confidence: {record.get('confidence')}",
        f"Setup: {record.get('setup_class')}",
    ]
    if record.get("verdict") == "UNCLEAR":
        lines.extend(["", "Game rule: UNCLEAR counts as reject-side."])
    if evidence.get("cutoff_source") == "entry_ts_fallback":
        lines.extend(["", "Cutoff fallback: entry_ts_fallback"])
    if record.get("summary_ua"):
        lines.extend(["", "Summary:", str(record.get("summary_ua"))])
    risk_flags = record.get("risk_flags") if isinstance(record.get("risk_flags"), list) else []
    if risk_flags:
        lines.extend(["", "Risk flags:"])
        lines.extend([f"- {flag}" for flag in risk_flags])
    return "\n".join(lines)


def _send_telegram_notification(record: Dict[str, Any]) -> Dict[str, Any]:
    if not _notify_enabled():
        return {"status": "noop", "reason": "telegram_disabled"}
    if send_webhook is None:
        return {"status": "noop", "reason": "no_webhook_sender"}
    try:
        evidence = record.get("evidence_pack") if isinstance(record.get("evidence_pack"), dict) else {}
        text = _telegram_text(record)
        send_webhook({
            "event": "LLM_TRADE_JUDGE_VERDICT",
            "type": "LLM_TRADE_JUDGE_VERDICT",
            "mode": record.get("mode") or evidence.get("mode") or "live",
            "symbol": evidence.get("symbol") or "",
            "trade_key": record.get("trade_key"),
            "llm_call_status": record.get("llm_call_status"),
            "verdict": record.get("verdict"),
            "competitive_side": record.get("competitive_side"),
            "confidence": record.get("confidence"),
            "setup_class": record.get("setup_class"),
            "summary_ua": record.get("summary_ua"),
            "risk_flags": record.get("risk_flags") if isinstance(record.get("risk_flags"), list) else [],
            "cutoff": evidence.get("analysis_cutoff_ts"),
            "cutoff_source": evidence.get("cutoff_source"),
            "text": text,
            "message": text,
            "telegram_text": text,
        })
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def maybe_record_llm_pretrade_judge(st: Dict[str, Any], pos: Dict[str, Any], trigger: str = "EXITS_PLACED_V15") -> Dict[str, Any]:
    try:
        if not _is_enabled():
            return {"status": "noop", "reason": "disabled"}
        if not isinstance(pos, dict) or str(pos.get("status") or "").upper() != "OPEN":
            return {"status": "noop", "reason": "position_not_open"}
        if not pos.get("orders"):
            return {"status": "noop", "reason": "missing_orders"}

        trade_key = get_trade_key(pos)
        if not trade_key:
            return {"status": "noop", "reason": "missing_trade_key"}

        journal_path = _journal_path()
        if has_primary_verdict(journal_path, trade_key):
            if log_event:
                log_event("LLM_TRADE_JUDGE_DUPLICATE_SKIPPED", trade_key=trade_key)
            return {"status": "noop", "reason": "duplicate_primary", "trade_key": trade_key}

        evidence_pack = build_pretrade_evidence_pack(pos, st, trigger)
        mode = str(ENV.get("LLM_TRADE_JUDGE_MODE") or "stub").strip().lower()
        if mode == "stub":
            result = append_stub_pretrade_verdict(journal_path, evidence_pack)
        elif mode == "openai":
            try:
                raw_text = call_openai_trade_judge(evidence_pack)
                validated, errors = validate_llm_verdict_json(raw_text)
                if validated is None:
                    record = build_error_verdict_record(
                        evidence_pack,
                        "json_validation_error",
                        ";".join(errors) if errors else "invalid_json",
                    )
                else:
                    record = build_success_verdict_record(evidence_pack, validated)
            except requests.exceptions.Timeout as exc:
                record = build_error_verdict_record(evidence_pack, "timeout", str(exc))
            except Exception as exc:
                error_msg = str(exc)
                error_type = "missing_api_key" if error_msg == "missing_openai_api_key" else "api_error"
                record = build_error_verdict_record(evidence_pack, error_type, error_msg)
            result = append_real_pretrade_verdict(journal_path, record)
        else:
            record = build_error_verdict_record(evidence_pack, "unsupported_mode", mode, model=None)
            result = append_real_pretrade_verdict(journal_path, record)

        if result.get("status") != "ok":
            if log_event:
                log_event("LLM_TRADE_JUDGE_WRITE_ERROR", trade_key=trade_key, error=result.get("error"))
            return result

        _mark_state_done(st, trade_key, str(result.get("verdict_id") or ""), result)
        if log_event:
            record = result.get("record") or {}
            action = "LLM_TRADE_JUDGE_ERROR" if record.get("llm_call_status") == "error" else "LLM_TRADE_JUDGE_VERDICT"
            log_event(
                action,
                trade_key=trade_key,
                verdict_id=result.get("verdict_id"),
                llm_call_status=record.get("llm_call_status"),
                verdict=record.get("verdict"),
                error_type=record.get("error_type"),
            )
        notify_result = _send_telegram_notification(result.get("record") or {})
        result["telegram"] = notify_result
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def maybe_record_llm_pretrade_stub(st: Dict[str, Any], pos: Dict[str, Any], trigger: str = "EXITS_PLACED_V15") -> Dict[str, Any]:
    return maybe_record_llm_pretrade_judge(st, pos, trigger=trigger)


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
    if verdict_u in ("STUB_NOT_CALLED", "ERROR_NOT_SCORED"):
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
