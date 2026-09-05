# executor_mod/baseline_policy.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from executor_mod import margin_policy

BASE_ASSET = "BTC"
QUOTE_ASSET = "USDC"

_LOG = logging.getLogger(__name__)


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_float(val: Any) -> float:
    try:
        return float(val or 0.0)
    except Exception:
        return 0.0


def _spot_account(api: Any, env: Dict[str, Any]) -> Dict[str, Any]:
    for fn_name in ("account", "get_account", "spot_account", "get_spot_account"):
        fn = getattr(api, fn_name, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                continue
    _LOG.warning("baseline spot account fetch unavailable")
    return {}


def _find_balance(balances: Any, asset: str) -> Tuple[float, float]:
    if not isinstance(balances, list):
        return 0.0, 0.0
    for row in balances:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset", "")).upper() == asset:
            return _as_float(row.get("free")), _as_float(row.get("locked"))
    return 0.0, 0.0


def _is_isolated(env: Dict[str, Any]) -> bool:
    raw = env.get("MARGIN_ISOLATED", "FALSE")
    return str(raw).strip().upper() in ("TRUE", "1", "YES", "Y", "ON")


def _margin_mode_label(env: Dict[str, Any]) -> str:
    return "isolated" if _is_isolated(env) else "cross"


def _snapshot_margin_balances(api: Any, env: Dict[str, Any], symbol: str) -> Dict[str, float]:
    account = api.margin_account(is_isolated=_is_isolated(env), symbols=symbol)
    base = margin_policy._asset_snapshot(account, BASE_ASSET)
    quote = margin_policy._asset_snapshot(account, QUOTE_ASSET)
    return {
        "base_free": _as_float(base.get("free")),
        "base_locked": _as_float(base.get("locked")),
        "quote_free": _as_float(quote.get("free")),
        "quote_locked": _as_float(quote.get("locked")),
    }


def _snapshot_spot_balances(api: Any, env: Dict[str, Any]) -> Dict[str, float]:
    account = _spot_account(api, env)
    balances = {}
    if isinstance(account, dict):
        balances = account.get("balances") or account.get("userAssets") or []
    else:
        _LOG.warning("baseline spot account payload invalid")
    base_free, base_locked = _find_balance(balances, BASE_ASSET)
    quote_free, quote_locked = _find_balance(balances, QUOTE_ASSET)
    return {
        "base_free": base_free,
        "base_locked": base_locked,
        "quote_free": quote_free,
        "quote_locked": quote_locked,
    }


def take_snapshot(
    api: Any,
    env: Dict[str, Any],
    symbol: str,
    trade_key: Any,
    baseline_kind: str,
) -> Dict[str, Any]:
    trade_key_str = str(trade_key) if trade_key else "unknown"
    if not trade_key:
        _LOG.warning("baseline snapshot missing trade_key; using 'unknown'")
    trade_mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if trade_mode == "margin":
        balances = _snapshot_margin_balances(api, env, symbol)
        debt = api.get_margin_debt_snapshot(symbol=symbol if _is_isolated(env) else None, is_isolated=_is_isolated(env))
        margin_mode = _margin_mode_label(env)
    else:
        balances = _snapshot_spot_balances(api, env)
        debt = {"has_debt": False}
        margin_mode = "unknown"
    return {
        "ts": _iso_utc(),
        "symbol": symbol,
        "trade_key": trade_key_str,
        "baseline_kind": baseline_kind,
        "trade_mode": trade_mode,
        "margin_mode": margin_mode,
        "debt": debt,
        "balances": balances,
    }
