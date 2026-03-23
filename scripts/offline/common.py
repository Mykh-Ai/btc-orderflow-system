from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


class OfflineBuildError(RuntimeError):
    """Fail-loud error for deterministic offline builders."""


def _parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise OfflineBuildError(f"missing input file: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as exc:
                raise OfflineBuildError(f"invalid jsonl at {path}:{i}: {exc}") from exc
    return rows


def write_dataframe(df: pd.DataFrame, out_base: Path) -> Path:
    """Write parquet if available; fallback to CSV when parquet engine missing."""
    out_base.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path = out_base.with_suffix(".parquet")
        df.to_parquet(out_path, index=False)
        return out_path
    except Exception:
        out_path = out_base.with_suffix(".csv")
        df.to_csv(out_path, index=False)
        return out_path


def sort_and_order(df: pd.DataFrame, sort_cols: Iterable[str], col_order: Iterable[str]) -> pd.DataFrame:
    cols = [c for c in col_order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    out = df.copy()
    if sort_cols:
        present = [c for c in sort_cols if c in out.columns]
        if present:
            out = out.sort_values(present, kind="mergesort").reset_index(drop=True)
    return out[cols + rest]


def load_feed(feed_path: Path) -> pd.DataFrame:
    if not feed_path.exists():
        raise OfflineBuildError(f"missing feed file: {feed_path}")
    df = pd.read_csv(feed_path)
    required = [
        "Timestamp",
        "BuyQty",
        "SellQty",
        "AvgPrice",
        "ClosePrice",
    ]
    miss = [c for c in required if c not in df.columns]
    if miss:
        raise OfflineBuildError(f"feed missing columns {miss} in {feed_path}")
    df = df.copy()
    df["ts"] = _parse_ts(df["Timestamp"])
    if df["ts"].isna().any():
        raise OfflineBuildError(f"feed contains invalid Timestamp rows in {feed_path}")
    df["delta"] = pd.to_numeric(df["BuyQty"], errors="coerce") - pd.to_numeric(df["SellQty"], errors="coerce")
    df["price"] = pd.to_numeric(df["ClosePrice"], errors="coerce").fillna(pd.to_numeric(df["AvgPrice"], errors="coerce"))
    if df["delta"].isna().any() or df["price"].isna().any():
        raise OfflineBuildError("feed contains non-numeric BuyQty/SellQty/price values")
    return df.sort_values(["ts"], kind="mergesort").reset_index(drop=True)
