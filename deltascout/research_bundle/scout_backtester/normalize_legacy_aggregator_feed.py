from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


INPUT_COLUMNS = {
    "Timestamp",
    "Trades",
    "TotalQty",
    "BuyQty",
    "SellQty",
    "AvgPrice",
    "ClosePrice",
    "HiPrice",
    "LowPrice",
}

OUTPUT_COLUMNS = [
    "Timestamp",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "AggTrades",
    "BuyQty",
    "SellQty",
    "VWAP",
    "OpenInterest",
    "FundingRate",
    "LiqBuyQty",
    "LiqSellQty",
    "IsSynthetic",
]

QUALITY_COLUMNS = [
    "date_utc",
    "row_count",
    "unique_minutes",
    "expected_minutes",
    "missing_minutes",
    "duplicate_minutes",
    "first_open_time_utc",
    "last_open_time_utc",
    "source_file",
    "normalized_sha256",
]


def _parse_timestamp(value: str, source_timezone: ZoneInfo) -> datetime:
    parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    localized = parsed.replace(tzinfo=source_timezone, fold=0)
    result = localized.astimezone(timezone.utc)
    if result.astimezone(source_timezone).replace(tzinfo=None) != parsed:
        raise ValueError(f"nonexistent or ambiguous legacy timestamp={value!r}")
    # The legacy minute loop occasionally stamped a completed aggregation at
    # xx:xx:59 (and very rarely xx:xx:01/02). Assign it to the nearest minute,
    # matching the minute-key semantics used by DeltaScout and Executor.
    if result.second >= 30:
        result += timedelta(minutes=1)
    return result.replace(second=0, microsecond=0)


def _number(row: dict[str, str], field: str, path: Path, row_number: int) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} at {path}:{row_number}") from exc


def _price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_legacy_aggregator_feed(
    input_root: Path,
    output_root: Path,
    *,
    date_from: str,
    date_to: str,
    source_timezone: str = "Europe/Bratislava",
) -> tuple[int, int]:
    daily_root = output_root / "daily"
    provenance_root = output_root / "provenance"
    daily_root.mkdir(parents=True, exist_ok=True)
    provenance_root.mkdir(parents=True, exist_ok=True)

    paths = [
        path
        for path in sorted(input_root.glob("*.csv"))
        if date_from <= path.stem <= date_to
    ]
    if not paths:
        raise ValueError(f"no legacy feed files for {date_from}..{date_to} under {input_root}")

    zone = ZoneInfo(source_timezone)
    source_rows: list[tuple[datetime, dict[str, str], Path, int]] = []
    seen_source_minutes: set[datetime] = set()
    duplicate_source_minutes = 0

    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = INPUT_COLUMNS.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"missing legacy columns={sorted(missing)} in {path}")
            for row_number, row in enumerate(reader, start=2):
                ts = _parse_timestamp(row["Timestamp"], zone)
                if ts in seen_source_minutes:
                    duplicate_source_minutes += 1
                    continue
                seen_source_minutes.add(ts)
                source_rows.append((ts, row, path, row_number))

    source_rows.sort(key=lambda item: item[0])
    previous_close: float | None = None
    rows_by_utc_day: dict[str, list[dict[str, str]]] = {}
    source_files_by_utc_day: dict[str, set[str]] = {}

    for ts, row, path, row_number in source_rows:
        close = _number(row, "ClosePrice", path, row_number)
        raw_high = _number(row, "HiPrice", path, row_number)
        raw_low = _number(row, "LowPrice", path, row_number)
        open_price = close if previous_close is None else previous_close
        high = max(raw_high, open_price, close)
        low = min(raw_low, open_price, close)
        utc_day = ts.date().isoformat()
        rows_by_utc_day.setdefault(utc_day, []).append(
            {
                "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "Open": _price(open_price),
                "High": _price(high),
                "Low": _price(low),
                "Close": _price(close),
                "Volume": row["TotalQty"],
                "AggTrades": row["Trades"],
                "BuyQty": row["BuyQty"],
                "SellQty": row["SellQty"],
                "VWAP": row["AvgPrice"],
                "OpenInterest": "",
                "FundingRate": "",
                "LiqBuyQty": "",
                "LiqSellQty": "",
                "IsSynthetic": "0",
            }
        )
        source_files_by_utc_day.setdefault(utc_day, set()).add(str(path))
        previous_close = close

    quality_rows: list[dict[str, str | int]] = []
    total_rows = 0

    for utc_day, output_rows in sorted(rows_by_utc_day.items()):
        timestamps = [
            datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            for row in output_rows
        ]
        output_path = daily_root / f"{utc_day}.csv"
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(output_rows)

        expected_minutes = 0
        if timestamps:
            expected_minutes = int((timestamps[-1] - timestamps[0]) / timedelta(minutes=1)) + 1
        quality_rows.append(
            {
                "date_utc": utc_day,
                "row_count": len(output_rows),
                "unique_minutes": len(timestamps),
                "expected_minutes": expected_minutes,
                "missing_minutes": max(0, expected_minutes - len(timestamps)),
                "duplicate_minutes": duplicate_source_minutes,
                "first_open_time_utc": timestamps[0].isoformat() if timestamps else "",
                "last_open_time_utc": timestamps[-1].isoformat() if timestamps else "",
                "source_file": "|".join(sorted(source_files_by_utc_day[utc_day])),
                "normalized_sha256": _sha256(output_path),
            }
        )
        total_rows += len(output_rows)

    quality_path = provenance_root / "daily_quality.csv"
    with quality_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUALITY_COLUMNS)
        writer.writeheader()
        writer.writerows(quality_rows)

    return len(paths), total_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize the archived legacy Binance Spot aggregator feed for Scout replay"
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--source-timezone", default="Europe/Bratislava")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    files, rows = normalize_legacy_aggregator_feed(
        args.input_root,
        args.output_root,
        date_from=args.date_from,
        date_to=args.date_to,
        source_timezone=args.source_timezone,
    )
    print(f"normalized_files={files}")
    print(f"normalized_rows={rows}")
    print(f"daily_root={args.output_root / 'daily'}")


if __name__ == "__main__":
    main()
