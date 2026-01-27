# executor_mod/margin_policy.py
from __future__ import annotations

import json
from decimal import Decimal, ROUND_UP
from typing import Any, Dict, Optional


def _ensure_margin_state(st: Dict[str, Any]) -> Dict[str, Any]:
    margin = st.setdefault("margin", {})
    margin.setdefault("borrowed_assets", {})
    margin.setdefault("borrowed_by_trade", {})
    margin.setdefault("borrowed_trade_keys", [])
    margin.setdefault("repaid_trade_keys", [])
    margin.setdefault("active_trade_key", None)
    return margin


def _account_assets(account: Dict[str, Any]) -> list[Dict[str, Any]]:
    assets = account.get("userAssets")
    if isinstance(assets, list):
        return assets
    assets = account.get("assets")
    if isinstance(assets, list):
        if assets and isinstance(assets[0], dict) and ("baseAsset" in assets[0] or "quoteAsset" in assets[0]):
            flattened: list[Dict[str, Any]] = []
            for row in assets:
                if not isinstance(row, dict):
                    continue
                base_asset = row.get("baseAsset")
                quote_asset = row.get("quoteAsset")
                if isinstance(base_asset, dict):
                    flattened.append(base_asset)
                if isinstance(quote_asset, dict):
                    flattened.append(quote_asset)
            return flattened
        return assets
    return []


def _asset_snapshot(account: Dict[str, Any], asset: str) -> Dict[str, Any]:
    for item in _account_assets(account):
        if item.get("asset") == asset:
            return item
    return {}


def _is_true(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().upper() in ("TRUE", "1", "YES", "Y", "ON")


def _split_symbol_assets(symbol: str) -> tuple[str, str]:
    s = str(symbol or "").strip().upper()
    if not s:
        return "", ""
    quotes = [
        "USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI",
        "BTC", "ETH", "EUR", "TRY", "BRL", "GBP", "JPY",
        "AUD", "CAD", "CHF",
    ]
    for quote in sorted(quotes, key=len, reverse=True):
        if s.endswith(quote) and len(s) > len(quote):
            return s[:-len(quote)], quote
    return "", ""


def _to_decimal(value: Any) -> Optional[Decimal]:
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except Exception:
        return None


def _get_env(api: Any) -> Dict[str, Any]:
    env_fn = getattr(api, "_env", None)
    if callable(env_fn):
        try:
            env = env_fn()
            if isinstance(env, dict):
                return env
        except Exception:
            return {}
    return {}


def _asset_step_size(plan: Dict[str, Any], api: Any, asset: str, symbol: str) -> Optional[Decimal]:
    asset_s = str(asset or "").strip().upper()
    for key in ("stepSize", "step_size", "asset_step", "borrow_step", "borrow_step_size"):
        if key in plan and plan.get(key) is not None:
            return _to_decimal(plan.get(key))
    env = _get_env(api)
    if asset_s:
        for key in (
            f"{asset_s}_STEP_SIZE",
            f"{asset_s}_STEP",
            f"ASSET_STEP_{asset_s}",
            f"ASSET_STEP_SIZE_{asset_s}",
        ):
            if key in env and env.get(key) is not None:
                return _to_decimal(env.get(key))
        asset_steps = env.get("ASSET_STEP_SIZES") or env.get("ASSET_STEPS")
        if isinstance(asset_steps, str):
            try:
                asset_steps = json.loads(asset_steps)
            except Exception:
                asset_steps = None
        if isinstance(asset_steps, dict):
            if asset_s in asset_steps and asset_steps.get(asset_s) is not None:
                return _to_decimal(asset_steps.get(asset_s))
            if asset_s.lower() in asset_steps and asset_steps.get(asset_s.lower()) is not None:
                return _to_decimal(asset_steps.get(asset_s.lower()))
    base_asset, quote_asset = _split_symbol_assets(symbol)
    if asset_s and asset_s == base_asset:
        if env.get("QTY_STEP") is not None:
            return _to_decimal(env.get("QTY_STEP"))
    if asset_s and asset_s == quote_asset:
        for key in ("QUOTE_STEP", "QUOTE_ASSET_STEP", "QUOTE_STEP_SIZE"):
            if env.get(key) is not None:
                return _to_decimal(env.get(key))
    return None



def _round_amount_up(amount: Decimal, step_size: Decimal) -> Decimal:
    step_d = _to_decimal(step_size)
    if step_d is None or step_d <= 0:
        return Decimal(str(amount))
    units = (Decimal(str(amount)) / step_d).to_integral_value(rounding=ROUND_UP)
    return units * step_d


def ensure_borrow_if_needed(
    st: Dict[str, Any],
    api: Any,
    symbol: str,
    side: str,
    qty: float,
    plan: Dict[str, Any],
) -> None:
    """Borrow only if available free balance is below plan-needed."""
    margin = _ensure_margin_state(st)
    trade_key = plan.get("trade_key") or plan.get("trade_id") or plan.get("key")
    if trade_key and trade_key in margin["borrowed_trade_keys"]:
        return

    asset = plan.get("borrow_asset") or plan.get("asset")
    needed = plan.get("borrow_amount") or plan.get("needed")
    if not asset:
        margin["last_borrow_skip_reason"] = "missing_borrow_asset"
        return
    needed_dec = _to_decimal(needed) or Decimal("0")
    if needed_dec <= 0:
        margin["last_borrow_skip_reason"] = "needed<=0"
        return

    is_isolated = _is_true(plan.get("is_isolated"))
    margin["is_isolated"] = is_isolated
    account = api.margin_account(is_isolated=is_isolated, symbols=symbol)
    snap = _asset_snapshot(account, asset)
    free_dec = _to_decimal(snap.get("free") or "0") or Decimal("0")
    if free_dec >= needed_dec:
        return

    borrow_amt_dec = max(needed_dec - free_dec, Decimal("0"))
    borrow_amt_raw = borrow_amt_dec
    base_asset, quote_asset = _split_symbol_assets(symbol)
    step_size = _asset_step_size(plan, api, asset, symbol)
    step_size_log: Optional[Decimal] = None
    if step_size is not None and step_size > 0:
        borrow_amt_dec = _round_amount_up(borrow_amt_dec, step_size)
        step_size_log = step_size
    else:
        env = _get_env(api)
        asset_s = str(asset or "").strip().upper()
        if asset_s and asset_s == quote_asset:
            margin["last_borrow_skip_reason"] = "missing_quote_step_size"
            log_fn = getattr(api, "log_event", None)
            if not callable(log_fn):
                from executor_mod.notifications import log_event as log_fn
            log_fn(
                "BORROW_SKIP",
                asset=asset_s,
                symbol=str(symbol or ""),
                reason="missing_quote_step_size",
                needed=str(needed_dec),
                free=str(free_dec),
                raw_amount=str(borrow_amt_raw),
            )
            return
        fallback_step: Optional[Decimal] = None
        if asset_s and asset_s == base_asset:
            qty_step = env.get("QTY_STEP")
            qty_step_d = _to_decimal(qty_step) if qty_step is not None else None
            if qty_step_d is not None and qty_step_d > 0:
                fallback_step = qty_step_d
                borrow_amt_dec = _round_amount_up(borrow_amt_dec, qty_step_d)
            elif asset_s == "BTC":
                fallback_step = Decimal("0.000001")
                borrow_amt_dec = _round_amount_up(borrow_amt_dec, fallback_step)
        if fallback_step is not None:
            step_size_log = fallback_step
    log_fn = getattr(api, "log_event", None)
    if not callable(log_fn):
        from executor_mod.notifications import log_event as log_fn
    log_fn(
        "BORROW_AMOUNT_ROUNDED",
        raw_amount=str(borrow_amt_raw),
        rounded_amount=str(borrow_amt_dec),
        stepSize=str(step_size_log) if step_size_log is not None else None,
    )
    if borrow_amt_dec <= 0:
        margin["last_borrow_skip_reason"] = "borrow<=0_after_round"
        return
    api.margin_borrow(asset, borrow_amt_dec, is_isolated=is_isolated, symbol=symbol)
    margin["borrowed_assets"][asset] = float(margin["borrowed_assets"].get(asset, 0.0)) + float(borrow_amt_dec)
    if trade_key and trade_key not in margin["borrowed_trade_keys"]:
        per = margin["borrowed_by_trade"].setdefault(trade_key, {})
        per[asset] = float(per.get(asset, 0.0)) + float(borrow_amt_dec)
        margin["borrowed_trade_keys"].append(trade_key)
        margin["active_trade_key"] = trade_key


def repay_if_any(st: Dict[str, Any], api: Any, symbol: str) -> None:
    """Repay borrowed balances once per trade."""
    margin = _ensure_margin_state(st)
    trade_key = margin.get("active_trade_key")
    if trade_key and trade_key in margin["repaid_trade_keys"]:
        return

    is_isolated = _is_true(margin.get("is_isolated"))
    if trade_key and trade_key in margin["borrowed_by_trade"]:
        tracked = margin["borrowed_by_trade"][trade_key]
    else:
        tracked = margin.get("borrowed_assets", {})
    global_borrowed = margin["borrowed_assets"]
    tracked_is_global = tracked is global_borrowed
    if not tracked:
        return

    account = api.margin_account(is_isolated=is_isolated, symbols=symbol)
    for asset, tracked_amt in list(tracked.items()):
        prev_global = float(global_borrowed.get(asset, 0.0))
        try:
            outstanding = float(_asset_snapshot(account, asset).get("borrowed") or 0.0)
        except Exception:
            outstanding = 0.0
        repay_amt = min(float(tracked_amt or 0.0), float(outstanding or 0.0))
        if repay_amt > 0.0:
            api.margin_repay(asset, repay_amt, is_isolated=is_isolated, symbol=symbol)
        remaining = max(0.0, float(tracked_amt or 0.0) - repay_amt)
        if tracked_is_global:
            global_borrowed[asset] = remaining
        else:
            tracked[asset] = remaining
            global_borrowed[asset] = max(0.0, prev_global - repay_amt)

    if trade_key and all(amount == 0 for amount in tracked.values()):
        margin["repaid_trade_keys"].append(trade_key)
        margin["active_trade_key"] = None
        # cleanup per-trade borrow map to prevent state growth
        if trade_key in margin.get("borrowed_by_trade", {}):
            margin["borrowed_by_trade"].pop(trade_key, None)
