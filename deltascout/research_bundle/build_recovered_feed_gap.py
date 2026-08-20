from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_START = "2026-04-23 17:05:00"
DEFAULT_END = "2026-05-06 22:51:00"

SHI_COLUMNS = [
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
    "Timestamp",
    "Day",
    "OutputAction",
    "RecoveryClass",
    "PriceSource",
    "OiSource",
    "FundingSource",
    "LiqSource",
    "OriginalClass",
    "OriginalClose",
    "RecoveredClose",
    "Notes",
]


@dataclass(frozen=True)
class BuildStats:
    output_root: Path
    quality_path: Path
    report_path: Path
    daily_files: int
    output_rows: int
    quality_rows: int
    class_counts: Counter[str]


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _date_range(start: datetime, end: datetime) -> list[str]:
    days: list[str] = []
    current = start.date()
    while current <= end.date():
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _read_csv_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return {row["Timestamp"]: row for row in csv.DictReader(fh)}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _float(row: dict[str, str] | None, key: str) -> float | None:
    if not row:
        return None
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int_text(value: float | None) -> str:
    if value is None:
        return "0"
    return str(int(value))


def _price_text(value: float | None) -> str:
    if value is None:
        return "0.00"
    return f"{value:.2f}"


def _qty_text(value: float | None) -> str:
    if value is None:
        return "0.000000"
    return f"{value:.6f}"


def _rate_text(value: float | None) -> str:
    if value is None:
        return "0.00000000"
    return f"{value:.8f}"


def _is_synthetic(row: dict[str, str] | None) -> bool:
    if not row:
        return False
    return row.get("IsSynthetic") in {"1", "1.0", "true", "True"}


def _original_class(row: dict[str, str] | None) -> str:
    if not row:
        return "missing"
    volume = _float(row, "Volume") or 0.0
    close = _float(row, "Close") or 0.0
    if _is_synthetic(row):
        if volume == 0.0 and close == 0.0:
            return "broken_zero_synthetic"
        if volume == 0.0:
            return "flat_synthetic"
        return "synthetic"
    return "real_enriched"


def _should_recover(ts: datetime, shi_row: dict[str, str] | None, start: datetime, end: datetime) -> bool:
    if ts < start or ts > end:
        return False
    if shi_row is None:
        return True
    if _is_synthetic(shi_row):
        return True
    if (_float(shi_row, "Volume") or 0.0) <= 0.0:
        return True
    if (_float(shi_row, "Close") or 0.0) <= 0.0:
        return True
    return False


def _copy_shi_row(row: dict[str, str]) -> dict[str, str]:
    return {column: row.get(column, "") for column in SHI_COLUMNS}


def _nearest_enrichment(
    ts: str,
    shi_rows: dict[str, dict[str, str]],
    previous_enriched: dict[str, str] | None,
) -> tuple[float | None, str, float | None, str]:
    row = shi_rows.get(ts)
    if row:
        oi = _float(row, "OpenInterest")
        funding = _float(row, "FundingRate")
        oi_source = "shi_rest_same_ts" if oi is not None else "missing"
        funding_source = "shi_stale_or_same_ts_untrusted" if funding is not None else "missing"
        return oi, oi_source, funding, funding_source

    if previous_enriched:
        oi = _float(previous_enriched, "OpenInterest")
        funding = _float(previous_enriched, "FundingRate")
        oi_source = "shi_rest_ffill" if oi is not None else "missing"
        funding_source = "shi_funding_ffill_untrusted" if funding is not None else "missing"
        return oi, oi_source, funding, funding_source

    return None, "missing", None, "missing"


def _recover_row(
    ts: str,
    legacy_row: dict[str, str],
    shi_row: dict[str, str] | None,
    previous_close: float | None,
    previous_enriched: dict[str, str] | None,
    shi_rows: dict[str, dict[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    close = _float(legacy_row, "ClosePrice")
    high = _float(legacy_row, "HiPrice")
    low = _float(legacy_row, "LowPrice")
    open_price = previous_close if previous_close is not None else close

    high_candidates = [value for value in (high, open_price, close) if value is not None]
    low_candidates = [value for value in (low, open_price, close) if value is not None]
    high = max(high_candidates) if high_candidates else close
    low = min(low_candidates) if low_candidates else close

    oi, oi_source, funding, funding_source = _nearest_enrichment(ts, shi_rows, previous_enriched)
    output = {
        "Timestamp": ts,
        "Open": _price_text(open_price),
        "High": _price_text(high),
        "Low": _price_text(low),
        "Close": _price_text(close),
        "Volume": _qty_text(_float(legacy_row, "TotalQty")),
        "AggTrades": _int_text(_float(legacy_row, "Trades")),
        "BuyQty": _qty_text(_float(legacy_row, "BuyQty")),
        "SellQty": _qty_text(_float(legacy_row, "SellQty")),
        "VWAP": _price_text(_float(legacy_row, "AvgPrice")),
        "OpenInterest": _price_text(oi),
        "FundingRate": _rate_text(funding),
        "LiqBuyQty": "0.000000",
        "LiqSellQty": "0.000000",
        "IsSynthetic": "0",
    }
    quality = {
        "Timestamp": ts,
        "Day": ts[:10],
        "OutputAction": "recovered_from_legacy",
        "RecoveryClass": "PRICE_VOLUME_OI_RECOVERED" if oi_source != "missing" else "PRICE_VOLUME_RECOVERED",
        "PriceSource": "legacy_volume_alert_archive",
        "OiSource": oi_source,
        "FundingSource": funding_source,
        "LiqSource": "missing_forceOrder_ws_gap",
        "OriginalClass": _original_class(shi_row),
        "OriginalClose": "" if not shi_row else shi_row.get("Close", ""),
        "RecoveredClose": output["Close"],
        "Notes": "IsSynthetic=0 because price/volume/delta are recovered from real legacy archive; see sidecar for degraded enriched fields.",
    }
    return output, quality


def build_recovered_feed_gap(
    legacy_root: Path,
    shi_root: Path,
    output_root: Path,
    quality_root: Path,
    start: datetime,
    end: datetime,
    mirror_output_root: Path | None = None,
) -> BuildStats:
    days = _date_range(start, end)
    quality_rows: list[dict[str, str]] = []
    class_counts: Counter[str] = Counter()
    output_rows = 0
    daily_files = 0

    previous_close: float | None = None
    previous_enriched: dict[str, str] | None = None

    for day in days:
        shi_rows = _read_csv_map(shi_root / f"{day}.csv")
        legacy_rows = _read_csv_map(legacy_root / f"{day}.csv")
        timestamps = sorted(set(shi_rows) | set(legacy_rows), key=_parse_ts)
        day_out: list[dict[str, str]] = []

        for ts in timestamps:
            ts_dt = _parse_ts(ts)
            shi_row = shi_rows.get(ts)
            legacy_row = legacy_rows.get(ts)

            if _should_recover(ts_dt, shi_row, start, end):
                if legacy_row is None:
                    quality = {
                        "Timestamp": ts,
                        "Day": day,
                        "OutputAction": "excluded",
                        "RecoveryClass": "MISSING_LEGACY_SOURCE",
                        "PriceSource": "missing",
                        "OiSource": "missing",
                        "FundingSource": "missing",
                        "LiqSource": "missing",
                        "OriginalClass": _original_class(shi_row),
                        "OriginalClose": "" if not shi_row else shi_row.get("Close", ""),
                        "RecoveredClose": "",
                        "Notes": "No legacy row available; output row omitted.",
                    }
                    quality_rows.append(quality)
                    class_counts[quality["RecoveryClass"]] += 1
                    continue
                out_row, quality = _recover_row(
                    ts,
                    legacy_row,
                    shi_row,
                    previous_close,
                    previous_enriched,
                    shi_rows,
                )
                day_out.append(out_row)
                quality_rows.append(quality)
                class_counts[quality["RecoveryClass"]] += 1
            elif shi_row is not None:
                out_row = _copy_shi_row(shi_row)
                day_out.append(out_row)
                recovery_class = "REAL_ENRICHED" if not _is_synthetic(shi_row) else "SYNTHETIC_PRESERVED_OUTSIDE_GAP"
                quality_rows.append(
                    {
                        "Timestamp": ts,
                        "Day": day,
                        "OutputAction": "preserved_original",
                        "RecoveryClass": recovery_class,
                        "PriceSource": "aitrader_shi_feed",
                        "OiSource": "aitrader_shi_feed",
                        "FundingSource": "aitrader_shi_feed",
                        "LiqSource": "aitrader_shi_feed",
                        "OriginalClass": _original_class(shi_row),
                        "OriginalClose": shi_row.get("Close", ""),
                        "RecoveredClose": shi_row.get("Close", ""),
                        "Notes": "Outside recovery window or already real enriched.",
                    }
                )
                class_counts[recovery_class] += 1
            else:
                continue

            close_value = _float(day_out[-1], "Close") if day_out else None
            if close_value is not None:
                previous_close = close_value
            if shi_row is not None:
                previous_enriched = shi_row

        if day_out:
            _write_csv(output_root / f"{day}.csv", SHI_COLUMNS, day_out)
            if mirror_output_root is not None:
                _write_csv(mirror_output_root / f"{day}.csv", SHI_COLUMNS, day_out)
            output_rows += len(day_out)
            daily_files += 1

    scope_id = f"{start:%Y-%m-%d_%H%M}_to_{end:%Y-%m-%d_%H%M}"
    quality_path = quality_root / f"recovery_quality_{scope_id}.csv"
    report_path = quality_root / f"recovery_report_{scope_id}.md"
    _write_csv(quality_path, QUALITY_COLUMNS, quality_rows)
    _write_report(report_path, start, end, output_root, mirror_output_root, output_rows, daily_files, class_counts)

    return BuildStats(
        output_root=output_root,
        quality_path=quality_path,
        report_path=report_path,
        daily_files=daily_files,
        output_rows=output_rows,
        quality_rows=len(quality_rows),
        class_counts=class_counts,
    )


def _write_report(
    path: Path,
    start: datetime,
    end: datetime,
    output_root: Path,
    mirror_output_root: Path | None,
    output_rows: int,
    daily_files: int,
    class_counts: Counter[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Recovered Feed Gap Report",
        "",
        f"- Recovery window: `{start:%Y-%m-%d %H:%M:%S}` to `{end:%Y-%m-%d %H:%M:%S}` UTC",
        f"- Output root: `{output_root}`",
        f"- Mirror output root: `{mirror_output_root}`" if mirror_output_root else "- Mirror output root: none",
        f"- Daily files written: {daily_files}",
        f"- Output rows written: {output_rows}",
        "",
        "## Recovery Classes",
        "",
    ]
    for key, count in class_counts.most_common():
        lines.append(f"- `{key}`: {count}")
    lines.extend(
        [
            "",
            "## Field Provenance",
            "",
            "- Price/OHLCV/trades/buy/sell/VWAP inside the gap come from legacy `/root/volume-alert/data/archive/feed`.",
            "- OpenInterest is copied from available `shi` rows when present, otherwise forward-filled from the latest `shi` row.",
            "- FundingRate is copied or forward-filled only to satisfy the strict raw schema and is marked untrusted in the quality sidecar during the WS gap.",
            "- Liquidation fields are set to zero during recovered rows because historical `forceOrder` stream data was not archived in the legacy feed.",
            "- `IsSynthetic=0` on recovered rows because price/volume/delta are reconstructed from real legacy market rows; use the sidecar for degraded enriched-field filtering.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = _default_project_root()
    material = root / "deltascout" / "research_material"
    parser = argparse.ArgumentParser(description="Build recovered SHI-compatible feed files for the Binance WS gap.")
    parser.add_argument("--legacy-root", type=Path, default=material / "source_archives" / "legacy_volume_alert_feed")
    parser.add_argument("--shi-root", type=Path, default=material / "source_archives" / "aitrader_shi_feed")
    parser.add_argument("--output-root", type=Path, default=material / "recovered_feed")
    parser.add_argument("--quality-root", type=Path, default=material / "recovery_reports")
    parser.add_argument("--mirror-output-root", type=Path, default=None)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_recovered_feed_gap(
        legacy_root=args.legacy_root,
        shi_root=args.shi_root,
        output_root=args.output_root,
        quality_root=args.quality_root,
        mirror_output_root=args.mirror_output_root,
        start=_parse_ts(args.start),
        end=_parse_ts(args.end),
    )
    print(f"daily_files={result.daily_files}")
    print(f"output_rows={result.output_rows}")
    print(f"quality_rows={result.quality_rows}")
    print(f"output_root={result.output_root}")
    print(f"quality_path={result.quality_path}")
    print(f"report_path={result.report_path}")
    print("class_counts=" + ", ".join(f"{key}:{value}" for key, value in result.class_counts.most_common()))


if __name__ == "__main__":
    main()
