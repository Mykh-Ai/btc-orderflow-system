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
import json
from contextlib import suppress
import math
import hmac
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, List, Tuple

import requests
from urllib.parse import urlencode, urlsplit, urlunsplit
import inspect

from executor_mod.notifications import log_event

_ENV: Optional[Dict[str, Any]] = None
_BINANCE_TIME_OFFSET_MS: int = 0

_fmt_qty = None
_fmt_price = None
_round_qty = None
_intent_log_guard = False
_balance_debug_last: Dict[str, float] = {}


def _caller_context(max_frames: int = 3) -> List[str]:
    frames = []
    for frame in inspect.stack()[2:]:
        module = frame.frame.f_globals.get("__name__", "")
        if module.startswith("executor_mod.binance_api"):
            continue
        frames.append(f"{frame.function}@{frame.filename}:{frame.lineno}")
        if len(frames) >= max_frames:
            break
    return frames


def _validate_params(params: Dict[str, Any], *, endpoint: str, method: str) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    invalid_keys: List[str] = []
    for k, v in params.items():
        if v is None:
            continue
        if not isinstance(k, str):
            invalid_keys.append(repr(k))
            continue
        if k.strip() == "":
            invalid_keys.append(repr(k))
            continue
        if any(ch.isspace() for ch in k) or "&" in k or "=" in k:
            invalid_keys.append(repr(k))
            continue
        clean[k] = v
    if invalid_keys:
        log_event(
            "BINANCE_PARAM_INVALID",
            endpoint=endpoint,
            method=method,
            invalid_keys=invalid_keys,
            param_keys=list(clean.keys()),
            caller_context=_caller_context(),
        )
        raise ValueError(f"Invalid Binance param keys for {method} {endpoint}: {invalid_keys}")
    return clean


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


def _extract_margin_free(account: Any, asset: str, *, is_isolated: bool) -> Optional[float]:
    def _as_float(val: Any) -> Optional[float]:
        try:
            return float(val or 0.0)
        except Exception:
            return None
    if not asset:
        return None
    if not is_isolated:
        assets = account.get("userAssets") if isinstance(account, dict) else None
        if isinstance(assets, list):
            for row in assets:
                if isinstance(row, dict) and str(row.get("asset")).upper() == asset:
                    return _as_float(row.get("free"))
        return None
    assets = None
    if isinstance(account, list):
        assets = account
    elif isinstance(account, dict):
        assets = account.get("assets")
    if isinstance(assets, list):
        for row in assets:
            if not isinstance(row, dict):
                continue
            for leg in ("baseAsset", "quoteAsset"):
                leg_row = row.get(leg)
                if isinstance(leg_row, dict) and str(leg_row.get("asset")).upper() == asset:
                    return _as_float(leg_row.get("free"))
    return None


def _log_order_intent(endpoint: str, method: str, params: Dict[str, Any], error_text: str) -> None:
    global _intent_log_guard
    if _intent_log_guard:
        return
    _intent_log_guard = True
    try:
        env = _env()
        symbol = params.get("symbol") or env.get("SYMBOL")
        side = params.get("side")
        order_type = params.get("type")
        qty = params.get("quantity")
        price = params.get("price")
        stop_price = params.get("stopPrice")
        tif = params.get("timeInForce")
        side_effect = params.get("sideEffectType")
        is_isolated = params.get("isIsolated") or env.get("MARGIN_ISOLATED")
        trade_mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
        notional = None
        try:
            if price is not None and qty is not None:
                notional = float(price) * float(qty)
        except Exception:
            notional = None
        base_asset, quote_asset = _split_symbol_assets(symbol)
        log_event(
            "ORDER_INTENT",
            endpoint=endpoint,
            method=method,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=qty,
            price=price,
            stopPrice=stop_price,
            timeInForce=tif,
            notional_est=notional,
            trade_mode=trade_mode,
            is_isolated=is_isolated,
            side_effect=side_effect,
            base_asset=base_asset,
            quote_asset=quote_asset,
            error=error_text,
            caller_context=_caller_context(),
        )
        debug = env.get("BINANCE_DEBUG_PARAMS")
        if debug:
            key = f"{symbol}:{params.get('newClientOrderId') or params.get('clientOrderId') or params.get('orderId') or 'na'}"
            now_s = time.time()
            min_iv = float(env.get("BINANCE_DEBUG_BALANCE_MIN_SEC", 30))
            last_s = _balance_debug_last.get(key, 0.0)
            if now_s - last_s >= min_iv:
                _balance_debug_last[key] = now_s
                if trade_mode == "margin":
                    try:
                        iso_bool = str(is_isolated or "FALSE").strip().upper() in ("TRUE", "1", "YES", "Y", "ON")
                        account = margin_account(is_isolated=iso_bool, symbols=symbol if iso_bool else None)
                        base_free = _extract_margin_free(account, base_asset, is_isolated=iso_bool)
                        quote_free = _extract_margin_free(account, quote_asset, is_isolated=iso_bool)
                        log_event(
                            "ORDER_BALANCE_SNAPSHOT",
                            symbol=symbol,
                            trade_mode=trade_mode,
                            is_isolated=iso_bool,
                            base_asset=base_asset,
                            quote_asset=quote_asset,
                            base_free=base_free,
                            quote_free=quote_free,
                        )
                    except Exception as exc:
                        log_event("ORDER_BALANCE_SNAPSHOT_ERROR", symbol=symbol, error=str(exc))
                else:
                    log_event("ORDER_BALANCE_SNAPSHOT_SKIP", symbol=symbol, reason="spot_account_unavailable")
    finally:
        _intent_log_guard = False


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


def _fmt_amount_no_sci(amount: Any) -> str:
    if amount is None:
        raise ValueError("amount is None")
    try:
        d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"bad amount: {amount!r}") from exc
    s = format(d, "f").strip()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s == "" or s == "-0":
        s = "0"
    return s


# ===================== HTTP reliability helpers =====================
# These helpers implement retry/backoff/failover for transient CloudFront 503s and timeouts.


def _env_bases() -> List[str]:
    """Return list of Binance API base URLs from env or defaults.

    Env var BINANCE_API_BASES can be comma-separated full URLs.
    Default: api.binance.com, api1.binance.com, api2.binance.com, api3.binance.com
    """
    env = _env()
    custom = env.get("BINANCE_API_BASES")
    if custom:
        return [b.strip() for b in str(custom).split(",") if b.strip()]
    return [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    ]


def _swap_base(url: str, base: str) -> str:
    """Replace scheme+netloc of url with base while keeping path/query/fragment."""
    parsed = urlsplit(url)
    base_parsed = urlsplit(base)
    return urlunsplit((base_parsed.scheme, base_parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _http_timeout() -> Tuple[float, float]:
    """Return (connect_timeout, read_timeout) tuple.

    Connect timeout fixed at 3s; read timeout from env (default 15s).
    """
    env = _env()
    connect_timeout = 3.0
    try:
        read_timeout = float(env.get("BINANCE_HTTP_READ_TIMEOUT_SEC", 15))
    except (ValueError, TypeError):
        read_timeout = 15.0
    if read_timeout <= 0:
        read_timeout = 15.0
    return (connect_timeout, read_timeout)


def _do_request(method: str, url: str, *, headers: Dict[str, Any], req_params: Dict[str, Any]) -> requests.Response:
    """Execute HTTP request with retry/backoff/failover across multiple Binance API hosts.

    Strategy:
    - Try each base in _env_bases()
    - For each base, attempt with delays [0.0, 0.3, 1.0, 2.0] (4 attempts total)
    - Treat HTTP 429/500/502/503/504 as transient (retry)
    - Catch Timeout and ConnectionError as transient (retry/failover)
    - On success (non-transient status), return Response immediately
    - If all attempts fail, raise last exception
    """
    method = str(method).strip().upper()
    bases = _env_bases()
    timeout = _http_timeout()
    delays = [0.0, 0.3, 1.0, 2.0]
    transient_statuses = {429, 500, 502, 503, 504}

    last_exception: Optional[Exception] = None
    last_status: Optional[int] = None
    last_text: Optional[str] = None

    for base in bases:
        swapped_url = _swap_base(url, base)
        for delay in delays:
            if delay > 0.0:
                time.sleep(delay)

            try:
                if method == "POST":
                    r = requests.post(swapped_url, headers=headers, params=req_params, timeout=timeout)
                elif method == "GET":
                    r = requests.get(swapped_url, headers=headers, params=req_params, timeout=timeout)
                elif method == "DELETE":
                    r = requests.delete(swapped_url, headers=headers, params=req_params, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # Success or non-transient error: return immediately
                if r.status_code not in transient_statuses:
                    return r

                # Transient status: record and continue retrying
                last_status = r.status_code
                last_text = r.text
                last_exception = None

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = e
                last_status = None
                last_text = None
                # Continue to next retry or next base

    # All attempts exhausted: raise last error
    if last_exception:
        raise last_exception
    if last_status:
        raise RuntimeError(f"Binance API exhausted all retries: last status {last_status}, text: {last_text}")
    raise RuntimeError("Binance API exhausted all retries with no response")


# ===================== Signed/Public requests =====================

def _sanitize_log_params(params: Dict[str, Any]) -> Dict[str, Any]:
    redacted = {}
    for k, v in params.items():
        key = str(k)
        if key in ("signature", "X-MBX-APIKEY", "api_key", "api_secret", "apikey"):
            continue
        redacted[key] = v
    return redacted


def _binance_error_code(body_text: str) -> Optional[int]:
    if not body_text:
        return None
    try:
        payload = json.loads(body_text)
    except Exception:
        return None
    if isinstance(payload, dict):
        code = payload.get("code")
        if isinstance(code, int):
            return code
        with suppress(Exception):
            return int(code)
    return None


def _sanitize_margin_params(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not str(endpoint).startswith("/sapi/v1/margin/"):
        return params
    cleaned = dict(params)
    for key in ("symbol", "asset"):
        val = cleaned.get(key)
        if isinstance(val, str):
            cleaned[key] = val.strip().upper()
    symbols = cleaned.get("symbols")
    if symbols is None:
        return cleaned
    if isinstance(symbols, (list, tuple)):
        parts = [str(s) for s in symbols]
    else:
        parts = str(symbols).split(",")
    sym_parts = [p.strip().upper() for p in parts if p.strip()]
    if sym_parts:
        cleaned["symbols"] = ",".join(sym_parts)
    else:
        cleaned.pop("symbols", None)
    return cleaned


def _binance_signed_request(method: str, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    env = _env()
    api_key = env["BINANCE_API_KEY"]
    api_secret = env["BINANCE_API_SECRET"]
    base_url = env["BINANCE_BASE_URL"]
    if not api_key or not api_secret:
        raise RuntimeError("Binance API key/secret missing")

    params = _validate_params(dict(params), endpoint=endpoint, method=method)
    params = _sanitize_margin_params(endpoint, params)
    normalized: Dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, str):
            normalized[k] = v.strip()
        else:
            normalized[k] = v
    params = normalized
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

    r = _do_request(method, url, headers=headers, req_params=req_params)

    if r.status_code != 200:
        text = r.text or ""
        debug = env.get("BINANCE_DEBUG_PARAMS")
        if debug:
            code = _binance_error_code(text)
            if code == -1100:
                log_event(
                    "BINANCE_REQ_FAIL",
                    method=method,
                    endpoint=endpoint,
                    params=_sanitize_log_params(req_params),
                    status=r.status_code,
                    body=text,
                )
        if '"code":-2010' in text or '"code": -2010' in text:
            _log_order_intent(endpoint, method, params, text)
        raise RuntimeError(f"Binance API error: {r.status_code} {text}")
    return r.json()


def binance_public_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Public GET without signature (used for rare Plan B guards / sanity checks)."""
    env = _env()
    base_url = env["BINANCE_BASE_URL"]
    url = base_url + endpoint
    req_params = _validate_params(params or {}, endpoint=endpoint, method="GET")
    r = _do_request("GET", url, headers={}, req_params=req_params)
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
    """Fail-safe: close a live position by MARKET (best effort).

    In spot mode we use place_spot_market().
    In margin mode we must use place_order_raw() so margin parameters (isIsolated/sideEffectType/autoRepayAtCancel)
    are injected consistently.
    """
    exit_side = "SELL" if str(pos_side).upper() == "LONG" else "BUY"
    if not client_id:
        client_id = f"EX_FLAT_{int(time.time())}"

    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        # Margin MARKET close (best effort). Uses current margin policy via place_order_raw().
        return place_order_raw({
            "symbol": symbol,
            "side": exit_side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": client_id,
        })

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


def get_order(symbol: str, order_id: int) -> Dict[str, Any]:
    return check_order_status(symbol, order_id)


def get_order_by_client_id(symbol: str, orig_client_order_id: str) -> Dict[str, Any]:
    """Fetch order by origClientOrderId (for idempotent placement attach)."""
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        return _binance_signed_request(
            "GET",
            "/sapi/v1/margin/order",
            {"symbol": symbol, "isIsolated": _tf(env.get("MARGIN_ISOLATED", "FALSE")), "origClientOrderId": orig_client_order_id},
        )
    return _binance_signed_request("GET", "/api/v3/order", {"symbol": symbol, "origClientOrderId": orig_client_order_id})


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


def open_orders(symbol: Optional[str]) -> List[Dict[str, Any]]:
    """Return open orders for symbol in current TRADE_MODE."""
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    symbol_norm = str(symbol or "").strip().upper()
    symbol_val = symbol_norm if symbol_norm else None
    if mode == "margin":
        is_isolated = _tf(env.get("MARGIN_ISOLATED", "FALSE"))
        params: Dict[str, Any] = {"isIsolated": is_isolated}
        if symbol_val:
            params["symbol"] = symbol_val
        j = _binance_signed_request("GET", "/sapi/v1/margin/openOrders", params)
        return list(j) if isinstance(j, list) else []
    params_spot: Dict[str, Any] = {}
    if symbol_val:
        params_spot["symbol"] = symbol_val
    j = _binance_signed_request("GET", "/api/v3/openOrders", params_spot)
    return list(j) if isinstance(j, list) else []


def my_trades(
    symbol: str,
    *,
    order_id: Optional[int] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return account trades for a symbol.

    Spot:   GET /api/v3/myTrades
    Margin: GET /sapi/v1/margin/myTrades
    """
    env = _env()
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    params: Dict[str, Any] = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = int(order_id)
    if start_time is not None:
        params["startTime"] = int(start_time)
    if end_time is not None:
        params["endTime"] = int(end_time)
    if limit is not None:
        params["limit"] = int(limit)

    if mode == "margin":
        params["isIsolated"] = _tf(env.get("MARGIN_ISOLATED", "FALSE"))
        j = _binance_signed_request("GET", "/sapi/v1/margin/myTrades", params)
        return list(j) if isinstance(j, list) else []

    j = _binance_signed_request("GET", "/api/v3/myTrades", params)
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


def get_margin_debt_snapshot(*, symbol: Optional[str] = None, is_isolated: Optional[bool] = None) -> Dict[str, Any]:
    """Exchange-truth debt snapshot for I13.

    Returns:
      {"has_debt": bool, "details": dict, "details_v2": dict, "endpoint": str}

    Notes:
    - Cross uses /sapi/v1/margin/account
    - Isolated uses /sapi/v1/margin/isolated/account?symbols=SYMBOL
    - We treat (borrowed + interest) > 0 as "debt".
    """
    env = _env()
    if (env.get("TRADE_MODE") or "").lower() != "margin":
        raise RuntimeError("get_margin_debt_snapshot() called while TRADE_MODE is not 'margin'")

    if is_isolated is None:
        iso_bool = (_tf(env.get("MARGIN_ISOLATED", "FALSE")) == "TRUE")
    elif isinstance(is_isolated, bool):
        iso_bool = is_isolated
    else:
        # tolerate string/int inputs defensively
        iso_bool = (_tf(is_isolated) == "TRUE")
    sym = symbol if symbol is not None else (env.get("SYMBOL") if iso_bool else None)
    if iso_bool and not sym:
        raise RuntimeError("get_margin_debt_snapshot(): isolated requires symbol")

    endpoint = "/sapi/v1/margin/isolated/account" if iso_bool else "/sapi/v1/margin/account"

    acc = margin_account(is_isolated=iso_bool, symbols=sym if iso_bool else None)

    def _f(x: Any) -> float:
        with suppress(Exception):
            return float(x)
        return 0.0

    debts = []
    legacy_details: Dict[str, float] = {}
    total = 0.0
    try:
        eps = float(env.get("MARGIN_DEBT_EPS", 0.0))
    except Exception:
        eps = 0.0

    if not iso_bool:
        # Cross: acc["userAssets"] is a list of dicts with borrowed/interest.
        uas = acc.get("userAssets", []) if isinstance(acc, dict) else []
        if isinstance(uas, list):
            for row in uas:
                if not isinstance(row, dict):
                    continue
                asset = row.get("asset")
                borrowed = _f(row.get("borrowed", 0.0))
                interest = _f(row.get("interest", 0.0))
                liab = borrowed + interest
                if liab > eps:
                    debts.append({"asset": asset, "borrowed": borrowed, "interest": interest, "liability": liab})
                    if asset:
                        legacy_details[asset] = liab
                    total += liab
    else:
        # Isolated: acc["assets"] is list; each element has baseAsset/quoteAsset dicts.
        if isinstance(acc, list):
            assets = acc
        elif isinstance(acc, dict):
            assets = acc.get("assets", [])
        else:
            assets = []
        if isinstance(assets, list):
            for a in assets:
                if not isinstance(a, dict):
                    continue
                for leg_name in ("baseAsset", "quoteAsset"):
                    leg = a.get(leg_name)
                    if not isinstance(leg, dict):
                        continue
                    asset = leg.get("asset")
                    borrowed = _f(leg.get("borrowed", 0.0))
                    interest = _f(leg.get("interest", 0.0))
                    liab = borrowed + interest
                    if liab > eps:
                        debts.append(
                            {
                                "symbol": a.get("symbol") or sym,
                                "asset": asset,
                                "borrowed": borrowed,
                                "interest": interest,
                                "liability": liab,
                            }
                        )
                        sym_key = a.get("symbol") or sym
                        if sym_key and asset:
                            legacy_details[f"{sym_key}:{asset}"] = liab
                        total += liab

    details_v2 = {
        "is_isolated": iso_bool,
        "symbol": sym if iso_bool else None,
        "params": {"symbols": sym} if iso_bool else {},
        "debts": debts,
        "total_liability": total,
    }
    return {
        "has_debt": bool(legacy_details),
        "details": legacy_details,
        "details_v2": details_v2,
        "endpoint": endpoint,
    }


def margin_borrow(asset: str, amount: Any, *, is_isolated: Optional[bool] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Manual borrow (if you do NOT rely on sideEffectType auto-borrow)."""
    env = _env()
    iso = _tf(is_isolated if is_isolated is not None else env.get("MARGIN_ISOLATED", "FALSE"))
    sym = symbol or env.get("SYMBOL")
    asset_s = str(asset).strip().upper()
    sym_s = str(sym or "").strip().upper() if sym else sym
    p: Dict[str, Any] = {
        "asset": asset_s,
        "amount": _fmt_amount_no_sci(amount),
        "type": "BORROW",
        "isIsolated": iso,
    }
    if iso == "TRUE":
        if not sym_s:
            raise RuntimeError("margin_borrow(): isolated borrow requires symbol")
        p["symbol"] = sym_s
    return _binance_signed_request("POST", "/sapi/v1/margin/borrow-repay", p)


def margin_repay(asset: str, amount: Any, *, is_isolated: Optional[bool] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Manual repay (if you do NOT rely on sideEffectType auto-repay)."""
    env = _env()
    iso = _tf(is_isolated if is_isolated is not None else env.get("MARGIN_ISOLATED", "FALSE"))
    sym = symbol or env.get("SYMBOL")
    asset_s = str(asset).strip().upper()
    sym_s = str(sym or "").strip().upper() if sym else sym
    p: Dict[str, Any] = {
        "asset": asset_s,
        "amount": _fmt_amount_no_sci(amount),
        "type": "REPAY",
        "isIsolated": iso,
    }
    if iso == "TRUE":
        if not sym_s:
            raise RuntimeError("margin_repay(): isolated repay requires symbol")
        p["symbol"] = sym_s
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
