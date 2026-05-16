"""Append-only final execution snapshots for closed trades.

This module is intentionally read-only with respect to trading state. It records
local closure facts plus best-effort exchange fill evidence and must never block
position cleanup or margin repayment.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "trade_execution_snapshot_v1"
DEFAULT_PATH = "/data/state/trade_execution_snapshots.jsonl"
DEFAULT_SCORE_EXCLUDE_KEYS = "EX_EN_1778689753"

ORDER_ROLES = ("entry", "tp1", "tp2", "final_sl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_default(obj: Any) -> Any:
    try:
        return str(obj)
    except Exception:
        return None


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=_safe_default))
    except Exception:
        return str(value)


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        if s == "":
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _dec_str(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(value, "f")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_from_api(binance_api: Any) -> Dict[str, Any]:
    fn = getattr(binance_api, "_env", None)
    if callable(fn):
        try:
            env = fn()
            if isinstance(env, dict):
                return env
        except Exception:
            return {}
    return {}


def _symbol_from(st: Dict[str, Any], last_closed: Dict[str, Any], env: Optional[Dict[str, Any]] = None) -> str:
    env = env or {}
    return str(
        st.get("symbol")
        or last_closed.get("symbol")
        or env.get("SYMBOL")
        or os.getenv("SYMBOL", "BTCUSDC")
        or ""
    ).strip().upper()


def _snapshot_path(env: Optional[Dict[str, Any]] = None) -> str:
    env = env or {}
    return str(
        env.get("TRADE_EXECUTION_SNAPSHOTS_FN")
        or os.getenv("TRADE_EXECUTION_SNAPSHOTS_FN", DEFAULT_PATH)
        or DEFAULT_PATH
    )


def _score_exclude_keys() -> set[str]:
    raw = os.getenv("LLM_TRADE_JUDGE_SCORE_EXCLUDE_KEYS", DEFAULT_SCORE_EXCLUDE_KEYS)
    return {part.strip() for part in str(raw or "").split(",") if part.strip()}


def _quote_asset(symbol: str) -> str:
    s = str(symbol or "").upper()
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "BNB", "EUR", "TRY"):
        if s.endswith(quote) and len(s) > len(quote):
            return quote
    return ""


def _append_error(snapshot: Dict[str, Any], *, stage: str, code: str, message: str, **extra: Any) -> None:
    err = {"stage": stage, "code": code, "message": str(message)}
    err.update({k: v for k, v in extra.items() if v is not None})
    snapshot.setdefault("errors", []).append(err)


def classify_lifecycle_from_last_closed(last_closed: Dict[str, Any]) -> str:
    tp1_done = _as_bool((last_closed or {}).get("tp1_done"))
    tp2_done = _as_bool((last_closed or {}).get("tp2_done"))
    sl_done = _as_bool((last_closed or {}).get("sl_done"))
    if not tp1_done and not tp2_done and sl_done:
        return "plain_sl"
    if tp1_done and not tp2_done and sl_done:
        return "tp1_sl"
    if tp1_done and tp2_done:
        return "tp1_tp2_trailing_stop"
    return "manual_or_unknown"


def should_exclude_from_scoring(trade_key: Any, source: str, last_closed: Dict[str, Any]) -> Dict[str, Any]:
    tk = str(trade_key or "").strip()
    src = str(source or "")
    reason = str((last_closed or {}).get("reason") or "")
    if tk and tk in _score_exclude_keys():
        return {
            "excluded_from_scoring": True,
            "scoring_exclusion_reason": "manual_false_peak_mechanics_test",
        }
    if src == "sync_exchange_clear":
        return {
            "excluded_from_scoring": True,
            "scoring_exclusion_reason": "reconciliation_exchange_clear",
        }
    if src == "sync_confirmed_canceled":
        return {
            "excluded_from_scoring": True,
            "scoring_exclusion_reason": "entry_canceled_no_fill",
        }
    if src == "_clear_position_slot":
        if "FAILSAFE" in reason.upper():
            exclusion_reason = "failsafe_cleanup"
        elif reason.upper().startswith("ENTRY_") or "ENTRY_TIMEOUT" in reason.upper():
            exclusion_reason = "entry_canceled_no_fill"
        else:
            exclusion_reason = "local_cleanup"
        return {"excluded_from_scoring": True, "scoring_exclusion_reason": exclusion_reason}
    return {"excluded_from_scoring": False, "scoring_exclusion_reason": None}


def normalize_trade_fill(raw_trade: Dict[str, Any]) -> Dict[str, Any]:
    raw = raw_trade or {}
    price = _dec(raw.get("price"))
    qty = _dec(raw.get("qty"))
    quote_qty = _dec(raw.get("quoteQty"))
    if quote_qty is None and price is not None and qty is not None:
        quote_qty = price * qty
    commission = _dec(raw.get("commission"))

    out = {
        "id": raw.get("id"),
        "orderId": raw.get("orderId"),
        "price": _dec_str(price),
        "qty": _dec_str(qty),
        "quoteQty": _dec_str(quote_qty),
        "commission": _dec_str(commission),
        "commissionAsset": raw.get("commissionAsset"),
        "time": raw.get("time"),
        "isBuyer": raw.get("isBuyer"),
        "isMaker": raw.get("isMaker"),
    }
    if "isBestMatch" in raw:
        out["isBestMatch"] = raw.get("isBestMatch")
    return out


def summarize_fills(fills: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not fills:
        return {}
    total_qty = Decimal("0")
    total_quote_qty = Decimal("0")
    commissions: Dict[str, Decimal] = {}
    first_time = None
    last_time = None

    for fill in fills:
        f = normalize_trade_fill(fill) if "quoteQty" not in fill else fill
        qty = _dec(f.get("qty")) or Decimal("0")
        quote_qty = _dec(f.get("quoteQty")) or Decimal("0")
        commission = _dec(f.get("commission")) or Decimal("0")
        asset = str(f.get("commissionAsset") or "").strip().upper()
        total_qty += qty
        total_quote_qty += quote_qty
        if asset and commission:
            commissions[asset] = commissions.get(asset, Decimal("0")) + commission
        fill_time = f.get("time")
        if fill_time is not None:
            if first_time is None or fill_time < first_time:
                first_time = fill_time
            if last_time is None or fill_time > last_time:
                last_time = fill_time

    avg_price = (total_quote_qty / total_qty) if total_qty > 0 else None
    return {
        "total_qty": _dec_str(total_qty),
        "total_quote_qty": _dec_str(total_quote_qty),
        "avg_price": _dec_str(avg_price),
        "commission_by_asset": {asset: _dec_str(value) for asset, value in sorted(commissions.items())},
        "first_fill_time": first_time,
        "last_fill_time": last_time,
    }


def _local_borrowed(st: Dict[str, Any], trade_key: str) -> Optional[Dict[str, Any]]:
    margin = st.get("margin") if isinstance(st, dict) else None
    if not isinstance(margin, dict):
        return None
    by_trade = margin.get("borrowed_by_trade")
    if isinstance(by_trade, dict) and trade_key and isinstance(by_trade.get(trade_key), dict):
        return _jsonable(by_trade.get(trade_key))
    borrowed_assets = margin.get("borrowed_assets")
    if isinstance(borrowed_assets, dict) and borrowed_assets:
        return _jsonable(borrowed_assets)
    return None


def build_local_snapshot(st: Dict[str, Any], last_closed: Dict[str, Any], source: str) -> Dict[str, Any]:
    lc = last_closed if isinstance(last_closed, dict) else {}
    symbol = _symbol_from(st or {}, lc)
    trade_key = str(lc.get("trade_key") or lc.get("client_id") or lc.get("order_id") or "")
    exclusion = should_exclude_from_scoring(trade_key, source, lc)
    borrowed = _local_borrowed(st or {}, trade_key)

    snapshot = {
        "schema": SCHEMA_VERSION,
        "ts": lc.get("ts") or _now_iso(),
        "trade_key": trade_key,
        "symbol": symbol,
        "source": str(source or ""),
        "snapshot_status": "local_only",
        "excluded_from_scoring": exclusion["excluded_from_scoring"],
        "scoring_exclusion_reason": exclusion["scoring_exclusion_reason"],
        "lifecycle_class": classify_lifecycle_from_last_closed(lc),
        "local_last_closed": _jsonable(lc),
        "orders": {
            "entry": {"order_id": lc.get("order_id")},
            "tp1": {"order_id": lc.get("order_id_tp1"), "local_qty": lc.get("qty1")},
            "tp2": {"order_id": lc.get("order_id_tp2"), "local_qty": lc.get("qty2")},
            "final_sl": {"order_id": lc.get("order_id_sl"), "local_qty": lc.get("qty3")},
        },
        "fills": {"entry": [], "tp1": [], "tp2": [], "final_sl": []},
        "fill_summaries": {"entry": {}, "tp1": {}, "tp2": {}, "final_sl": {}},
        "fees": {
            "commission_total": None,
            "commission_by_asset": {},
            "borrow_interest": None,
            "borrow_asset": next(iter(borrowed.keys()), None) if isinstance(borrowed, dict) and borrowed else None,
        },
        "pnl": {"gross_realized_pnl_approx": None, "net_realized_pnl_approx": None},
        "margin": {"borrowed": borrowed, "repaid": None, "repay_evidence": None},
        "errors": [],
    }
    return snapshot


def _apply_fee_summary(snapshot: Dict[str, Any]) -> None:
    totals: Dict[str, Decimal] = {}
    for summary in (snapshot.get("fill_summaries") or {}).values():
        if not isinstance(summary, dict):
            continue
        for asset, amount in (summary.get("commission_by_asset") or {}).items():
            d = _dec(amount) or Decimal("0")
            if asset and d:
                totals[str(asset).upper()] = totals.get(str(asset).upper(), Decimal("0")) + d
    by_asset = {asset: _dec_str(value) for asset, value in sorted(totals.items())}
    snapshot.setdefault("fees", {})["commission_by_asset"] = by_asset
    snapshot["fees"]["commission_total"] = next(iter(by_asset.values())) if len(by_asset) == 1 else None


def enrich_snapshot_with_margin_trades(
    snapshot: Dict[str, Any],
    binance_api: Any,
    time_window: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    helper = getattr(binance_api, "margin_my_trades", None)
    if not callable(helper):
        _append_error(snapshot, stage="exchange_fills", code="helper_unavailable", message="margin_my_trades helper unavailable")
        return snapshot

    env = _env_from_api(binance_api)
    symbol = str(snapshot.get("symbol") or env.get("SYMBOL") or os.getenv("SYMBOL", "")).strip().upper()
    is_isolated = _as_bool(env.get("MARGIN_ISOLATED", os.getenv("MARGIN_ISOLATED", "FALSE")))
    tw = time_window or {}
    attempted = 0
    succeeded = 0

    for role in ORDER_ROLES:
        order_id = ((snapshot.get("orders") or {}).get(role) or {}).get("order_id")
        if order_id in (None, "", 0, "0"):
            continue
        attempted += 1
        try:
            raw_fills = helper(
                symbol,
                order_id=order_id,
                start_time=tw.get("start_time"),
                end_time=tw.get("end_time"),
                limit=1000,
                is_isolated=is_isolated,
            )
            fills = [normalize_trade_fill(fill) for fill in (raw_fills or []) if isinstance(fill, dict)]
            snapshot["fills"][role] = fills
            snapshot["fill_summaries"][role] = summarize_fills(fills)
            succeeded += 1
        except Exception as exc:
            _append_error(
                snapshot,
                stage="exchange_fills",
                code="margin_my_trades_failed",
                message=str(exc),
                role=role,
                order_id=order_id,
            )

    if attempted == 0:
        snapshot["snapshot_status"] = "local_only"
    elif succeeded == 0:
        snapshot["snapshot_status"] = "local_only"
    elif snapshot.get("errors"):
        snapshot["snapshot_status"] = "partial"
    else:
        snapshot["snapshot_status"] = "complete"

    if succeeded > 0:
        _apply_fee_summary(snapshot)
        compute_gross_realized_pnl_approx(snapshot)
    return snapshot


def _summary_quote_qty(snapshot: Dict[str, Any], role: str) -> Decimal:
    summary = ((snapshot.get("fill_summaries") or {}).get(role) or {})
    return _dec(summary.get("total_quote_qty")) or Decimal("0")


def compute_gross_realized_pnl_approx(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    side = str(((snapshot.get("local_last_closed") or {}).get("side") or "")).strip().upper()
    if side and side != "LONG":
        _append_error(snapshot, stage="pnl", code="short_pnl_not_implemented", message="Gross PnL approximation currently supports LONG only")
        return snapshot

    entry_cost = _summary_quote_qty(snapshot, "entry")
    exit_proceeds = (
        _summary_quote_qty(snapshot, "tp1")
        + _summary_quote_qty(snapshot, "tp2")
        + _summary_quote_qty(snapshot, "final_sl")
    )
    if entry_cost <= 0 or exit_proceeds <= 0:
        return snapshot

    gross = exit_proceeds - entry_cost
    snapshot.setdefault("pnl", {})["gross_realized_pnl_approx"] = _dec_str(gross)

    quote = _quote_asset(str(snapshot.get("symbol") or ""))
    fees = snapshot.get("fees") or {}
    commission_by_asset = fees.get("commission_by_asset") or {}
    if commission_by_asset and set(commission_by_asset.keys()) == {quote}:
        commission = _dec(commission_by_asset.get(quote)) or Decimal("0")
        snapshot["pnl"]["net_realized_pnl_approx"] = _dec_str(gross - commission)
    elif commission_by_asset:
        _append_error(
            snapshot,
            stage="pnl",
            code="net_pnl_commission_conversion_unavailable",
            message="Net PnL left null because commissions are not all in quote asset",
        )
    return snapshot


def append_execution_snapshot(path: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    try:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, default=_safe_default) + "\n")
        return {"ok": True, "path": path, "error": None}
    except Exception as exc:
        return {"ok": False, "path": path, "error": str(exc)}


def record_final_execution_snapshot(st: Dict[str, Any], source: str, binance_api: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Build and append a final execution snapshot without raising."""
    snapshot: Optional[Dict[str, Any]] = None
    try:
        last_closed = (st or {}).get("last_closed")
        if not isinstance(last_closed, dict) or not last_closed:
            return None

        env = _env_from_api(binance_api) if binance_api is not None else {}
        snapshot = build_local_snapshot(st or {}, last_closed, source)
        if env:
            snapshot["symbol"] = _symbol_from(st or {}, last_closed, env)

        mode = str(env.get("TRADE_MODE") or os.getenv("TRADE_MODE", "spot")).strip().lower()
        if mode == "margin" and source == "_close_slot":
            _append_error(
                snapshot,
                stage="margin",
                code="repay_occurs_after_snapshot",
                message="Margin repayment runs after this snapshot; durable repay update is a future event.",
            )

        if binance_api is not None and mode == "margin":
            enrich_snapshot_with_margin_trades(snapshot, binance_api)

        path = _snapshot_path(env)
        result = append_execution_snapshot(path, snapshot)
        if not result.get("ok"):
            _append_error(snapshot, stage="append", code="append_failed", message=result.get("error") or "unknown append failure")
            try:
                from executor_mod.notifications import log_event
                log_event("TRADE_EXECUTION_SNAPSHOT_WRITE_ERROR", source=str(source or ""), error=result.get("error"))
            except Exception:
                pass
        return snapshot
    except Exception as exc:
        try:
            from executor_mod.notifications import log_event
            log_event("TRADE_EXECUTION_SNAPSHOT_ERROR", source=str(source or ""), error=str(exc))
        except Exception:
            pass
        return snapshot
