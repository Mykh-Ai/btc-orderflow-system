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
    df.columns = [c.strip() for c in df.columns]

    if "Timestamp" not in df.columns:
        return pd.DataFrame()
    # Normalize timestamp for easy lookup (tolerate different formats)
    try:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True).dt.tz_convert(None)
    except Exception:
        return pd.DataFrame()

    # Ensure we have a numeric price column
    if "ClosePrice" in df.columns:
        price_col = "ClosePrice"
    elif "AvgPrice" in df.columns:
        price_col = "AvgPrice"
    elif "Close" in df.columns:
        price_col = "Close"
    else:
        return pd.DataFrame()

    try:
        df["price"] = pd.to_numeric(df[price_col], errors="coerce")
    except Exception:
        return pd.DataFrame()

    df = df.dropna(subset=["Timestamp", "price"])
    df = df.sort_values("Timestamp").reset_index(drop=True)
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