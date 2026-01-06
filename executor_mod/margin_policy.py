# executor_mod/margin_policy.py
from __future__ import annotations

from typing import Any, Dict


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
    try:
        needed_f = float(needed or 0.0)
    except Exception:
        needed_f = 0.0
    if needed_f <= 0.0:
        margin["last_borrow_skip_reason"] = "needed<=0"
        return

    is_isolated = _is_true(plan.get("is_isolated"))
    margin["is_isolated"] = is_isolated
    account = api.margin_account(is_isolated=is_isolated, symbols=symbol)
    snap = _asset_snapshot(account, asset)
    try:
        free = float(snap.get("free") or 0.0)
    except Exception:
        free = 0.0

    if free >= needed_f:
        return

    borrow_amt = needed_f - free
    api.margin_borrow(asset, borrow_amt, is_isolated=is_isolated, symbol=symbol)
    margin["borrowed_assets"][asset] = float(margin["borrowed_assets"].get(asset, 0.0)) + float(borrow_amt)
    if trade_key and trade_key not in margin["borrowed_trade_keys"]:
        per = margin["borrowed_by_trade"].setdefault(trade_key, {})
        per[asset] = float(per.get(asset, 0.0)) + float(borrow_amt)
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
