from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import BacktestContractError, FeedBar


RECOVERY_START = datetime(2026, 4, 23, 17, 5, tzinfo=timezone.utc)
RECOVERY_END = datetime(2026, 5, 6, 22, 51, tzinfo=timezone.utc)
REQUIRED_COLUMNS = {
    "Timestamp",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "BuyQty",
    "SellQty",
    "IsSynthetic",
}
OPTIONAL_COLUMNS = (
    "AggTrades",
    "VWAP",
    "OpenInterest",
    "FundingRate",
    "LiqBuyQty",
    "LiqSellQty",
)


def parse_feed_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BacktestContractError(f"unparseable feed timestamp={text!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any, *, field: str, path: Path, row_number: int) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BacktestContractError(f"invalid {field} at {path}:{row_number}") from exc
    if not math.isfinite(result):
        raise BacktestContractError(f"non-finite {field} at {path}:{row_number}")
    return result


def _optional_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_quality_sidecar(root: Path | None) -> dict[datetime, str]:
    quality: dict[datetime, str] = {}
    if root is None or not root.exists():
        return quality
    for path in sorted(root.glob("recovery_quality_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"Timestamp", "RecoveryClass"}.issubset(reader.fieldnames or []):
                raise BacktestContractError(f"invalid recovery quality schema in {path}")
            for row_number, row in enumerate(reader, start=2):
                ts = parse_feed_timestamp(row.get("Timestamp"))
                value = str(row.get("RecoveryClass") or "").strip()
                if not value:
                    raise BacktestContractError(f"empty RecoveryClass at {path}:{row_number}")
                if ts in quality and quality[ts] != value:
                    raise BacktestContractError(f"conflicting recovery quality for {ts.isoformat()}")
                quality[ts] = value
    return quality


def load_feed(
    feed_root: Path,
    *,
    date_from: str,
    date_to: str,
    quality_sidecar_root: Path | None = None,
    feed_role: str = "signal_enriched",
) -> list[FeedBar]:
    if feed_role not in {"signal_enriched", "official_spot_execution"}:
        raise BacktestContractError(f"unsupported feed_role={feed_role}")
    quality = load_quality_sidecar(quality_sidecar_root)
    bars: list[FeedBar] = []
    seen: set[datetime] = set()
    paths = [path for path in sorted(feed_root.glob("*.csv")) if date_from <= path.stem <= date_to]
    if not paths:
        raise BacktestContractError(f"no feed CSV files for {date_from}..{date_to} under {feed_root}")
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
            if missing:
                raise BacktestContractError(f"missing feed columns={sorted(missing)} in {path}")
            for row_number, row in enumerate(reader, start=2):
                ts = parse_feed_timestamp(row.get("Timestamp"))
                if ts in seen:
                    raise BacktestContractError(f"duplicate feed minute={ts.isoformat()} at {path}:{row_number}")
                seen.add(ts)
                open_price = _number(row.get("Open"), field="Open", path=path, row_number=row_number)
                high = _number(row.get("High"), field="High", path=path, row_number=row_number)
                low = _number(row.get("Low"), field="Low", path=path, row_number=row_number)
                close = _number(row.get("Close"), field="Close", path=path, row_number=row_number)
                if low > min(open_price, close) or high < max(open_price, close) or low > high:
                    raise BacktestContractError(f"invalid OHLC ordering at {path}:{row_number}")
                synthetic = str(row.get("IsSynthetic") or "").strip().lower() in {"1", "true", "yes"}
                recovery_overlap = feed_role == "signal_enriched" and RECOVERY_START <= ts <= RECOVERY_END
                if feed_role == "official_spot_execution":
                    if synthetic:
                        raise BacktestContractError(f"official spot execution row cannot be synthetic at {path}:{row_number}")
                    quality_class = "BINANCE_SPOT_OFFICIAL"
                else:
                    quality_class = quality.get(ts)
                    if recovery_overlap and not quality_class:
                        raise BacktestContractError(f"missing recovery quality sidecar row for {ts.isoformat()}")
                    if not quality_class:
                        quality_class = "SYNTHETIC_UNTRUSTED" if synthetic else "REAL_ENRICHED"
                bars.append(
                    FeedBar(
                        ts=ts,
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                        volume=_number(row.get("Volume"), field="Volume", path=path, row_number=row_number),
                        buy_qty=_number(row.get("BuyQty"), field="BuyQty", path=path, row_number=row_number),
                        sell_qty=_number(row.get("SellQty"), field="SellQty", path=path, row_number=row_number),
                        is_synthetic=synthetic,
                        feed_quality_class=quality_class,
                        recovery_overlap=recovery_overlap,
                        source_path=str(path),
                        row_number=row_number,
                        optional={name: _optional_number(row.get(name)) for name in OPTIONAL_COLUMNS},
                    )
                )
    bars.sort(key=lambda bar: bar.ts)
    for previous, current in zip(bars, bars[1:]):
        if current.ts <= previous.ts:
            raise BacktestContractError("feed timestamps are not strictly monotonic")
    return bars


def quality_counts(bars: list[FeedBar]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bar in bars:
        counts[bar.feed_quality_class] = counts.get(bar.feed_quality_class, 0) + 1
    return dict(sorted(counts.items()))
