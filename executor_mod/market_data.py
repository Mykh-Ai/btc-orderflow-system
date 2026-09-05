#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market_data.py
Market data utilities extracted from executor.py.
Hard rule: moved functions below are verbatim copies from executor.py.
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Any, Dict
import pandas as pd

ENV: Dict[str, Any] = {}


def configure(env: Dict[str, Any]) -> None:
    global ENV
    ENV = env


def load_df_sorted() -> pd.DataFrame:
    # Robust loader: returns empty DF on schema issues.
    if not os.path.exists(ENV["AGG_CSV"]):
        return pd.DataFrame()

    df = pd.read_csv(ENV["AGG_CSV"])
    df.columns = [(c or "").replace("\ufeff", "").strip() for c in df.columns]

    if "Timestamp" not in df.columns:
        return pd.DataFrame()
    # Normalize timestamp for easy lookup (tolerate different formats)
    try:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True).dt.tz_convert(None)
    except Exception:
        return pd.DataFrame()

    # Ensure we have a numeric price column (ClosePrice/AvgPrice-derived).
    if "ClosePrice" in df.columns:
        price_col = "ClosePrice"
    elif "AvgPrice" in df.columns:
        price_col = "AvgPrice"
    elif "Close" in df.columns:
        price_col = "Close"
    else:
        return pd.DataFrame()

    try:
        def _numeric_series(name: str) -> pd.Series:
            if name not in df.columns:
                return pd.Series(float("nan"), index=df.index, dtype="float64")
            return pd.to_numeric(df[name], errors="coerce")

        close_raw = pd.to_numeric(df[price_col], errors="coerce")
        high_raw = _numeric_series("HiPrice")
        low_raw = _numeric_series("LowPrice")
        volume_raw = _numeric_series("TotalQty")
        trades_raw = _numeric_series("Trades")
        df["price"] = close_raw
    except Exception:
        return pd.DataFrame()

    # Preserve untouched numeric inputs for Executor V8 structural-stop selection.
    # Legacy consumers continue to use price/HiPrice/LowPrice below.
    df["close_usdt"] = close_raw
    df["high_usdt"] = high_raw
    df["low_usdt"] = low_raw
    df["volume_1m"] = volume_raw
    df["swing_row_real"] = (
        close_raw.notna()
        & high_raw.notna()
        & low_raw.notna()
        & volume_raw.notna()
        & trades_raw.notna()
        & (close_raw > 0)
        & (high_raw > 0)
        & (low_raw > 0)
        & (volume_raw > 0)
        & (trades_raw > 0)
        & (high_raw >= low_raw)
    )

    # Hi/Low (optional in v2 schema). If missing, fall back to price.

    if "HiPrice" in df.columns:
        df["HiPrice"] = pd.to_numeric(df["HiPrice"], errors="coerce")
    else:
        df["HiPrice"] = df["price"]

    if "LowPrice" in df.columns:
        df["LowPrice"] = pd.to_numeric(df["LowPrice"], errors="coerce")
    else:
        df["LowPrice"] = df["price"]

    df["HiPrice"] = df["HiPrice"].fillna(df["price"])
    df["LowPrice"] = df["LowPrice"].fillna(df["price"])

    df = df.dropna(subset=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)
    # Keep invalid price rows in the one-minute sequence but prevent them from
    # defining or confirming a structural swing.
    df["price"] = df["price"].ffill()
    df = df.dropna(subset=["price"])
    return df


def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    # normalize to minute resolution; be tolerant to tz formats
    try:
        target = pd.to_datetime(ts, utc=True, errors="coerce")
        if pd.isna(target):
            return len(df) - 1
        target = target.tz_convert(None).floor("min")
    except Exception:
        return len(df) - 1

    try:
        series = pd.to_datetime(df["Timestamp"], utc=True, errors="coerce")
        series = series.dt.tz_convert(None).dt.floor("min")
        m = df.index[series == target]
        return int(m[0]) if len(m) else len(df) - 1
    except Exception:
        return len(df) - 1



def latest_price(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return float("nan")
    return float(df.iloc[-1]["price"])
