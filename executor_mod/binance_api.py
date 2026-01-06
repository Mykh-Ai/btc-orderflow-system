#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""executor_mod.binance_api

Binance REST adapter used by executor.py.
Design:
- No circular imports (does NOT import executor.py).
- executor.py must call configure(ENV, fmt_qty=..., fmt_price=..., round_qty=...)
  before using order helpers.
"""
from __future__ import annotations

import time
import math
import hmac
import hashlib
from typing import Any, Dict, Optional, List

import requests
from urllib.parse import urlencode

from executor_mod.notifications import log_event

_ENV: Optional[Dict[str, Any]] = None
_BINANCE_TIME_OFFSET_MS: int = 0

_fmt_qty = None
_fmt_price = None
_round_qty = None


def configure(env: Dict[str, Any], *, fmt_qty=None, fmt_price=None, round_qty=None) -> None:
    """Wire runtime dependencies from executor.py.

    We keep these as injected callables to avoid pulling generic formatting/math
    into this module (and to avoid circular imports).
    """
    global _ENV, _fmt_qty, _fmt_price, _round_qty
    _ENV = env
    if fmt_qty is not None:
        _fmt_qty = fmt_qty
    if fmt_price is not None:
        _fmt_price = fmt_price
    if round_qty is not None:
        _round_qty = round_qty


def _env() -> Dict[str, Any]:
    if _ENV is None:
        raise RuntimeError("binance_api not configured: call binance_api.configure(ENV, ...) in executor.py")
    return _ENV


def _require_fmt() -> None:
    if _fmt_qty is None or _fmt_price is None or _round_qty is None:
        raise RuntimeError("binance_api missing fmt_* deps: call configure(..., fmt_qty=..., fmt_price=..., round_qty=...)")


def _tf(v: Any) -> str:
    """Normalize bool-ish values to Binance 'TRUE'/'FALSE' strings."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    s = str(v).strip().upper()
    if s in ("TRUE", "T", "1", "YES", "Y", "ON"):
        return "TRUE"
    if s in ("FALSE", "F", "0", "NO", "N", "OFF", ""):
        return "FALSE"
    # If the user passed something custom, don't guess – return as-is.
    return str(v)


def _margin_borrow_mode(env: Dict[str, Any]) -> str:
    return str(env.get("MARGIN_BORROW_MODE") or "manual").strip().lower()


def _margin_side_effect(env: Dict[str, Any]) -> str:
    # Avoid double borrow/repay: manual mode forces NO_SIDE_EFFECT.
    if _margin_borrow_mode(env) == "manual":
        return "NO_SIDE_EFFECT"
    return str(env.get("MARGIN_SIDE_EFFECT") or "NO_SIDE_EFFECT").strip().upper()
# ===================== Signed/Public requests =====================

def _binance_signed_request(method: str, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    env = _env()
    api_key = env["BINANCE_API_KEY"]
    api_secret = env["BINANCE_API_SECRET"]
    base_url = env["BINANCE_BASE_URL"]
    if not api_key or not api_secret:
        raise RuntimeError("Binance API key/secret missing")

    params = dict(params)
    params["timestamp"] = int(time.time() * 1000) + int(_BINANCE_TIME_OFFSET_MS)
    params.setdefault("recvWindow", env.get("RECV_WINDOW", 5000))

    # Deterministic query string for signature
    params_str = {k: str(v) for k, v in sorted(params.items(), key=lambda kv: kv[0])}
    query = urlencode(params_str)
    signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {"X-MBX-APIKEY": api_key}
    url = base_url + endpoint

    req_params = dict(params_str)
    req_params["signature"] = signature

    if method == "POST":
        r = requests.post(url, headers=headers, params=req_params, timeout=5)
    elif method == "GET":
        r = requests.get(url, headers=headers, params=req_params, timeout=5)
    elif method == "DELETE":
        r = requests.delete(url, headers=headers, params=req_params, timeout=5)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if r.status_code != 200:
        raise RuntimeError(f"Binance API error: {r.status_code} {r.text}")
    return r.json()


def binance_public_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Public GET without signature (used for rare Plan B guards / sanity checks)."""
    env = _env()
    base_url = env["BINANCE_BASE_URL"]
    url = base_url + endpoint
    r = requests.get(url, params=params or {}, timeout=5)
    if r.status_code != 200:
        raise RuntimeError(f"Binance API error: {r.status_code} {r.text}")
    return r.json() if r.text else {}


def _planb_exec_price(symbol: str, entry_side: str) -> Optional[float]:
    """Return a conservative executable price for Plan B checks.
    BUY  -> use ask
    SELL -> use bid
    """
    j = binance_public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    try:
        bid = float(j.get("bidPrice"))
        ask = float(j.get("askPrice"))
    except Exception:
        return None
    if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask > 0):
        return None
    return ask if entry_side.upper() == "BUY" else bid


def get_mid_price(symbol: str) -> float:
    j = binance_public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    bid = float(j["bidPrice"])
    ask = float(j["askPrice"])
    return (bid + ask) / 2.0


# ===================== Order helpers =====================

def place_spot_limit(symbol: str, side: str, qty: float, price: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Place a LIMIT order.

    Supports:
      - TRADE_MODE=spot   -> POST /api/v3/order
      - TRADE_MODE=margin -> POST /sapi/v1/margin/order
    """
    env = _env()
    _require_fmt()

    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()

    # Format quantity/price as strings to avoid float quirks
    qty_s = _fmt_qty(qty)
    price_s = _fmt_price(price)

    if mode == "margin":
        params: Dict[str, Any] = {
            "symbol": symbol,
            "isIsolated": _tf(env.get("MARGIN_ISOLATED", "FALSE")),
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty_s,
            "price": price_s,
            "newOrderRespType": "FULL",
            "sideEffectType": _margin_side_effect(env),
        }
        if client_id:
            params["newClientOrderId"] = client_id
        if _margin_borrow_mode(env) == "auto" and env.get("MARGIN_AUTO_REPAY_AT_CANCEL") is not None:
            params["autoRepayAtCancel"] = _tf(env.get("MARGIN_AUTO_REPAY_AT_CANCEL", False))
        return _binance_signed_request("POST", "/sapi/v1/margin/order", params)

    # spot
    params2: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": qty_s,
        "price": price_s,
    }
    if client_id:
        params2["newClientOrderId"] = client_id
    return _binance_signed_request("POST", "/api/v3/order", params2)


def place_spot_market(symbol: str, side: str, qty: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Place a MARKET order in current TRADE_MODE (spot or margin)."""
    _require_fmt()
    qty_r = _round_qty(qty)
    params: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": _fmt_qty(qty_r),
        "newOrderRespType": "FULL",
    }
    if client_id:
        params["newClientOrderId"] = client_id
    return place_order_raw(params)


def flatten_market(symbol: str, pos_side: str, qty: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Fail-safe: close a live position by MARKET (best effort)."""
    exit_side = "SELL" if str(pos_side).upper() == "LONG" else "BUY"
    if not client_id:
        client_id = f"EX_FLAT_{int(time.time())}"
    return place_spot_market(symbol, exit_side, qty, client_id=client_id)


def check_order_status(symbol: str, order_id: int) -> Dict[str, Any]:
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        return _binance_signed_request(
            "GET",
            "/sapi/v1/margin/order",
            {"symbol": symbol, "isIsolated": _tf(env.get("MARGIN_ISOLATED", "FALSE")), "orderId": order_id},
        )
    return _binance_signed_request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        return _binance_signed_request(
            "DELETE",
            "/sapi/v1/margin/order",
            {"symbol": symbol, "isIsolated": _tf(env.get("MARGIN_ISOLATED", "FALSE")), "orderId": order_id},
        )
    return _binance_signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})


def open_orders(symbol: str) -> List[Dict[str, Any]]:
    """Return open orders for symbol in current TRADE_MODE."""
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        j = _binance_signed_request(
            "GET",
            "/sapi/v1/margin/openOrders",
            {"symbol": symbol, "isIsolated": _tf(env.get("MARGIN_ISOLATED", "FALSE"))},
        )
        return list(j) if isinstance(j, list) else []
    j = _binance_signed_request("GET", "/api/v3/openOrders", {"symbol": symbol})
    return list(j) if isinstance(j, list) else []


def place_order_raw(endpoint_params: Dict[str, Any]) -> Dict[str, Any]:
    """Place an order in current TRADE_MODE.

    For margin orders, required common parameters are injected:
      - isIsolated
      - sideEffectType (if not already provided)
      - autoRepayAtCancel (if not already provided)
    """
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()

    if mode == "margin":
        p = dict(endpoint_params)
        p.setdefault("symbol", env["SYMBOL"])
        p.setdefault("isIsolated", _tf(env.get("MARGIN_ISOLATED", "FALSE")))  # Binance expects "TRUE"/"FALSE"
        if _margin_borrow_mode(env) == "manual":
            # Manual mode: prevent auto-borrow/repay from order side effects.
            p["sideEffectType"] = "NO_SIDE_EFFECT"
            if "autoRepayAtCancel" in p:
                p["autoRepayAtCancel"] = "FALSE"
        else:
            p.setdefault("sideEffectType", _margin_side_effect(env))
            # Inject auto repay at cancel if configured
            if "autoRepayAtCancel" not in p and env.get("MARGIN_AUTO_REPAY_AT_CANCEL") is not None:
                p.setdefault("autoRepayAtCancel", _tf(env.get("MARGIN_AUTO_REPAY_AT_CANCEL", False)))
        return _binance_signed_request("POST", "/sapi/v1/margin/order", p)

    # spot
    p = dict(endpoint_params)
    p.setdefault("symbol", env["SYMBOL"])
    return _binance_signed_request("POST", "/api/v3/order", p)


def margin_account(*, is_isolated: Optional[bool] = None, symbols: Optional[str] = None) -> Dict[str, Any]:
    """Return margin account info.

    Cross margin: GET /sapi/v1/margin/account
    Isolated    : GET /sapi/v1/margin/isolated/account (param: symbols="BTCUSDT,ETHUSDT")
    """
    env = _env()
    if (env.get("TRADE_MODE") or "").lower() != "margin":
        raise RuntimeError("margin_account() called while TRADE_MODE is not 'margin'")

    iso = _tf(is_isolated if is_isolated is not None else env.get("MARGIN_ISOLATED", "FALSE"))
    if iso == "TRUE":
        p: Dict[str, Any] = {}
        sym = symbols or env.get("SYMBOL")
        if sym:
            p["symbols"] = sym
        return _binance_signed_request("GET", "/sapi/v1/margin/isolated/account", p)

    return _binance_signed_request("GET", "/sapi/v1/margin/account", {})


def margin_borrow(asset: str, amount: Any, *, is_isolated: Optional[bool] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Manual borrow (if you do NOT rely on sideEffectType auto-borrow)."""
    env = _env()
    iso = _tf(is_isolated if is_isolated is not None else env.get("MARGIN_ISOLATED", "FALSE"))
    sym = symbol or env.get("SYMBOL")
    p: Dict[str, Any] = {
        "asset": asset,
        "amount": str(amount),
        "type": "BORROW",
        "isIsolated": iso,
    }
    if iso == "TRUE":
        if not sym:
            raise RuntimeError("margin_borrow(): isolated borrow requires symbol")
        p["symbol"] = sym
    return _binance_signed_request("POST", "/sapi/v1/margin/borrow-repay", p)


def margin_repay(asset: str, amount: Any, *, is_isolated: Optional[bool] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Manual repay (if you do NOT rely on sideEffectType auto-repay)."""
    env = _env()
    iso = _tf(is_isolated if is_isolated is not None else env.get("MARGIN_ISOLATED", "FALSE"))
    sym = symbol or env.get("SYMBOL")
    p: Dict[str, Any] = {
        "asset": asset,
        "amount": str(amount),
        "type": "REPAY",
        "isIsolated": iso,
    }
    if iso == "TRUE":
        if not sym:
            raise RuntimeError("margin_repay(): isolated repay requires symbol")
        p["symbol"] = sym
    return _binance_signed_request("POST", "/sapi/v1/margin/borrow-repay", p)

# ===================== Sanity/time sync =====================

def binance_sanity_check() -> None:
    """Fast connectivity + auth check.

    - public ping/time via /api/v3
    - signed check:
        - spot  : GET /api/v3/account
        - margin: GET /sapi/v1/margin/account
    """
    env = _env()
    # public
    binance_public_get("/api/v3/ping")
    srv_time = binance_public_get("/api/v3/time")

    global _BINANCE_TIME_OFFSET_MS
    try:
        server_ms = int(srv_time.get("serverTime", 0) or 0)
        local_ms = int(time.time() * 1000)
        _BINANCE_TIME_OFFSET_MS = (server_ms - local_ms) if server_ms else 0
    except Exception:
        _BINANCE_TIME_OFFSET_MS = 0

    log_event("BINANCE_PUBLIC_OK", server_time=srv_time.get("serverTime"), time_offset_ms=_BINANCE_TIME_OFFSET_MS)

    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        acc = _binance_signed_request("GET", "/sapi/v1/margin/account", {"recvWindow": env["RECV_WINDOW"]})
        log_event("BINANCE_SIGNED_OK", mode="margin", userAssets=len(acc.get("userAssets", [])))
    else:
        acc = _binance_signed_request("GET", "/api/v3/account", {"recvWindow": env["RECV_WINDOW"]})
        log_event("BINANCE_SIGNED_OK", mode="spot", balances=len(acc.get("balances", [])))
