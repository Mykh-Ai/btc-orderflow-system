from __future__ import annotations

from typing import Any, Dict


def tick(
    st: Dict[str, Any],
    pos: Dict[str, Any],
    api: Any,
    margin_policy: Any,
    env: Dict[str, Any],
    now_s: float,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "handled": False,
        "state_dirty": False,
    }

    if not isinstance(st, dict) or not isinstance(pos, dict):
        return result

    baseline = st.get("baseline")
    if not isinstance(baseline, dict):
        return result
    active = baseline.get("active")
    if not isinstance(active, dict):
        return result

    if pos.get("mode") != "live" or pos.get("status") not in ("OPEN", "OPEN_FILLED"):
        return result

    check_sec = _get_float(env.get("MANUAL_CLOSE_CHECK_SEC"), 120.0)
    if check_sec <= 0.0:
        check_sec = 0.0

    next_check = _get_float(pos.get("manual_close_next_check_s"), 0.0)
    if now_s < next_check:
        return result

    pos["manual_close_next_check_s"] = now_s + check_sec
    result["state_dirty"] = True

    trade_mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    symbol = str(env.get("SYMBOL") or pos.get("symbol") or "")
    base_asset, quote_asset = _split_symbol_assets(symbol, env)
    if not base_asset or not quote_asset:
        pos["manual_close_last_error"] = "missing_assets"
        result["state_dirty"] = True
        return result

    try:
        if trade_mode == "margin":
            is_isolated = _is_true(env.get("MARGIN_ISOLATED", "FALSE"))
            account = api.margin_account(is_isolated=is_isolated, symbols=symbol)
            base = margin_policy._asset_snapshot(account, base_asset)
            quote = margin_policy._asset_snapshot(account, quote_asset)
            balances = {
                "base_free": _get_float(base.get("free"), 0.0),
                "base_locked": _get_float(base.get("locked"), 0.0),
                "quote_free": _get_float(quote.get("free"), 0.0),
                "quote_locked": _get_float(quote.get("locked"), 0.0),
            }
            debt = api.get_margin_debt_snapshot(
                symbol=symbol if is_isolated else None,
                is_isolated=is_isolated,
            )
        else:
            account = _spot_account(api)
            balances = _spot_balances(account, base_asset, quote_asset)
            debt = {"has_debt": False}
    except Exception as exc:
        pos["manual_close_last_error"] = str(exc)
        result["state_dirty"] = True
        return result

    base_total = balances["base_free"] + balances["base_locked"]
    quote_total = balances["quote_free"] + balances["quote_locked"]

    active_bal = active.get("balances") if isinstance(active.get("balances"), dict) else {}
    base_base = _get_float(active_bal.get("base_free"), 0.0) + _get_float(active_bal.get("base_locked"), 0.0)
    quote_base = _get_float(active_bal.get("quote_free"), 0.0) + _get_float(active_bal.get("quote_locked"), 0.0)

    base_delta = base_total - base_base
    quote_delta = quote_total - quote_base

    base_eps = _get_float(env.get("BASE_EPS"), 0.00001)
    quote_eps = _get_float(env.get("QUOTE_EPS"), 2.0)
    if base_eps < 0.0:
        base_eps = 0.0
    if quote_eps < 0.0:
        quote_eps = 0.0

    has_debt = bool(debt.get("has_debt")) if trade_mode == "margin" else False
    guard_base = abs(base_delta) < base_eps

    side = str(pos.get("side") or "").upper()
    if side == "LONG":
        guard = guard_base and (not has_debt if trade_mode == "margin" else True)
    elif side == "SHORT":
        guard = (not has_debt) and guard_base
    else:
        guard = False

    if guard:
        candidate = _get_float(pos.get("manual_close_candidate_s"), 0.0)
        if candidate <= 0.0:
            pos["manual_close_candidate_s"] = now_s
            result["state_dirty"] = True
        else:
            confirm_sec = _get_float(env.get("MANUAL_CLOSE_CONFIRM_SEC"), check_sec or 120.0)
            if confirm_sec <= 0.0:
                confirm_sec = check_sec or 120.0
            if (now_s - candidate) >= confirm_sec:
                pos.pop("manual_close_candidate_s", None)
                result["state_dirty"] = True
                result["handled"] = True
                result["reason"] = "MANUAL_CLOSE_DETECTED"
                result["tag"] = "MANUAL_CLOSE_DETECTED_OK"
                result["details"] = {
                    "trade_mode": trade_mode,
                    "side": side,
                    "base_total": base_total,
                    "quote_total": quote_total,
                    "base_baseline": base_base,
                    "quote_baseline": quote_base,
                    "base_delta": base_delta,
                    "quote_delta": quote_delta,
                    "has_debt": has_debt,
                }
    else:
        if pos.get("manual_close_candidate_s") is not None:
            pos.pop("manual_close_candidate_s", None)
            result["state_dirty"] = True

    return result


def _get_float(val: Any, default: float) -> float:
    try:
        return float(val if val is not None else default)
    except Exception:
        return default


def _is_true(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().upper() in ("TRUE", "1", "YES", "Y", "ON")


def _spot_account(api: Any) -> Dict[str, Any]:
    for fn_name in ("account", "get_account", "spot_account", "get_spot_account"):
        fn = getattr(api, fn_name, None)
        if callable(fn):
            return fn()
    return {}


def _spot_balances(account: Dict[str, Any], base_asset: str, quote_asset: str) -> Dict[str, float]:
    balances = account.get("balances") or account.get("userAssets") or []
    base_free, base_locked = _find_balance(balances, base_asset)
    quote_free, quote_locked = _find_balance(balances, quote_asset)
    return {
        "base_free": base_free,
        "base_locked": base_locked,
        "quote_free": quote_free,
        "quote_locked": quote_locked,
    }


def _find_balance(balances: Any, asset: str) -> tuple[float, float]:
    if not isinstance(balances, list):
        return 0.0, 0.0
    asset_u = str(asset or "").upper()
    for row in balances:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset", "")).upper() == asset_u:
            return _get_float(row.get("free"), 0.0), _get_float(row.get("locked"), 0.0)
    return 0.0, 0.0


def _split_symbol_assets(symbol: str, env: Dict[str, Any]) -> tuple[str, str]:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return "", ""

    base_env = env.get("BASE_ASSET") or env.get("BASE")
    quote_env = env.get("QUOTE_ASSET") or env.get("QUOTE")
    if base_env and quote_env:
        return str(base_env).strip().upper(), str(quote_env).strip().upper()

    quotes = [
        "USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI",
        "BTC", "ETH", "EUR", "TRY", "BRL", "GBP", "JPY",
        "AUD", "CAD", "CHF",
    ]
    for quote in sorted(quotes, key=len, reverse=True):
        if sym.endswith(quote) and len(sym) > len(quote):
            return sym[:-len(quote)], quote

    return "", ""
