from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE_URL = "https://data.binance.vision/data/spot"
PARSER_VERSION = "BINANCE_SPOT_KLINES_1M_V0_1"
NORMALIZED_FIELDS = [
    "Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty",
    "IsSynthetic", "AggTrades", "VWAP", "OpenInterest", "FundingRate", "LiqBuyQty", "LiqSellQty",
]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(url: str, *, via_ssh: str | None = None) -> bytes:
    if via_ssh:
        command = ["ssh"]
        if os.name == "nt":
            command.extend(["-F", "NUL"])
        command.extend([via_ssh, "curl", "-fsSL", "--max-time", "60", url])
        return subprocess.check_output(command)
    request = urllib.request.Request(url, headers={"User-Agent": "DeltaScout-offline-research/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def _archive_candidates(symbol: str, interval: str, start: date, end: date) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    cursor = _month_start(start)
    while cursor <= end:
        month_end = _next_month(cursor) - timedelta(days=1)
        if month_end <= end:
            name = f"{symbol}-{interval}-{cursor:%Y-%m}.zip"
            candidates.append(
                {
                    "kind": "monthly",
                    "name": name,
                    "url": f"{BASE_URL}/monthly/klines/{symbol}/{interval}/{name}",
                    "coverage_from": cursor.isoformat(),
                    "coverage_to": month_end.isoformat(),
                }
            )
        else:
            day = max(cursor, start)
            while day <= end:
                name = f"{symbol}-{interval}-{day.isoformat()}.zip"
                candidates.append(
                    {
                        "kind": "daily",
                        "name": name,
                        "url": f"{BASE_URL}/daily/klines/{symbol}/{interval}/{name}",
                        "coverage_from": day.isoformat(),
                        "coverage_to": day.isoformat(),
                    }
                )
                day += timedelta(days=1)
        cursor = _next_month(cursor)
    return candidates


def _timestamp_utc(raw: str) -> datetime:
    value = int(raw)
    divisor = 1_000_000 if value >= 100_000_000_000_000 else 1_000
    return datetime.fromtimestamp(value / divisor, tz=timezone.utc)


def _parse_archive(payload: bytes, *, expected_name: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise RuntimeError(f"expected one CSV in {expected_name}, got {names}")
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8")
            rows: list[dict[str, Any]] = []
            for line_number, values in enumerate(csv.reader(text), start=1):
                if len(values) != 12:
                    raise RuntimeError(f"invalid Binance kline width in {expected_name}:{line_number}")
                ts = _timestamp_utc(values[0])
                if ts.second or ts.microsecond:
                    raise RuntimeError(f"unaligned open time in {expected_name}:{line_number}: {ts.isoformat()}")
                volume = float(values[5])
                taker_buy = float(values[9])
                rows.append(
                    {
                        "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "Open": values[1],
                        "High": values[2],
                        "Low": values[3],
                        "Close": values[4],
                        "Volume": values[5],
                        "BuyQty": values[9],
                        "SellQty": format(max(0.0, volume - taker_buy), ".8f"),
                        "IsSynthetic": "0",
                        "AggTrades": values[8],
                        "VWAP": format(float(values[7]) / volume, ".8f") if volume else values[4],
                        "OpenInterest": "",
                        "FundingRate": "",
                        "LiqBuyQty": "",
                        "LiqSellQty": "",
                    }
                )
    return rows


def acquire(
    *,
    symbol: str,
    interval: str,
    date_from: str,
    date_to: str,
    output_root: Path,
    archives_root: Path | None = None,
    download_via_ssh: str | None = None,
) -> Path:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        raise ValueError("date_to must be on or after date_from")
    archives_root = archives_root or output_root / "archives"
    daily_root = output_root / "daily"
    provenance_root = output_root / "provenance"
    archives_root.mkdir(parents=True, exist_ok=True)
    daily_root.mkdir(parents=True, exist_ok=True)
    provenance_root.mkdir(parents=True, exist_ok=True)

    all_rows: dict[str, dict[str, Any]] = {}
    sources_by_day: dict[str, set[str]] = defaultdict(set)
    archive_records: list[dict[str, Any]] = []
    for item in _archive_candidates(symbol, interval, start, end):
        url = item["url"]
        checksum_url = url + ".CHECKSUM"
        archive_path = archives_root / item["name"]
        checksum_path = archives_root / f"{item['name']}.CHECKSUM"
        reused_local_archive = archive_path.exists() and checksum_path.exists()
        payload = archive_path.read_bytes() if reused_local_archive else _download(url, via_ssh=download_via_ssh)
        checksum_payload = checksum_path.read_bytes() if reused_local_archive else _download(checksum_url, via_ssh=download_via_ssh)
        expected_sha = checksum_payload.decode("utf-8-sig").strip().split()[0].lower()
        actual_sha = _sha256(payload)
        if actual_sha != expected_sha:
            raise RuntimeError(f"checksum mismatch for {item['name']}: expected={expected_sha} actual={actual_sha}")
        archive_path.write_bytes(payload)
        checksum_path.write_bytes(checksum_payload)
        parsed = _parse_archive(payload, expected_name=item["name"])
        accepted = 0
        for row in parsed:
            day = str(row["Timestamp"])[:10]
            if date_from <= day <= date_to:
                key = str(row["Timestamp"])
                if key in all_rows and all_rows[key] != row:
                    raise RuntimeError(f"conflicting duplicate spot minute={key}")
                all_rows[key] = row
                sources_by_day[day].add(item["name"])
                accepted += 1
        archive_records.append(
            {
                **item,
                "checksum_url": checksum_url,
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "bytes": len(payload),
                "archive_rows": len(parsed),
                "accepted_rows": accepted,
                "local_archive": str(archive_path),
                "local_checksum": str(checksum_path),
                "reused_local_archive": reused_local_archive,
            }
        )

    rows_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timestamp in sorted(all_rows):
        rows_by_day[timestamp[:10]].append(all_rows[timestamp])
    quality_rows: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        rows = rows_by_day.get(day, [])
        path = daily_root / f"{day}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=NORMALIZED_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        timestamps = [datetime.fromisoformat(str(row["Timestamp"])).replace(tzinfo=timezone.utc) for row in rows]
        unique = len(set(timestamps))
        expected = 1440
        quality_rows.append(
            {
                "date_utc": day,
                "row_count": len(rows),
                "unique_minutes": unique,
                "expected_minutes": expected,
                "missing_minutes": expected - unique,
                "duplicate_minutes": len(rows) - unique,
                "first_open_time_utc": timestamps[0].isoformat() if timestamps else "",
                "last_open_time_utc": timestamps[-1].isoformat() if timestamps else "",
                "source_archives": "|".join(sorted(sources_by_day.get(day, set()))),
                "normalized_sha256": _sha256(path.read_bytes()),
            }
        )
        cursor += timedelta(days=1)

    quality_path = provenance_root / "daily_quality.csv"
    with quality_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(quality_rows[0]))
        writer.writeheader()
        writer.writerows(quality_rows)
    manifest = {
        "schema": "binance_spot_execution_feed_v0_1",
        "parser_version": PARSER_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market": "Binance Spot",
        "symbol": symbol,
        "interval": interval,
        "timestamp_semantics": "UTC kline open time; Binance Vision spot timestamps >=2025 parsed as microseconds",
        "requested_date_from": date_from,
        "requested_date_to": date_to,
        "normalized_daily_root": str(daily_root),
        "official_source": "https://github.com/binance/binance-public-data",
        "archives": archive_records,
        "daily_quality_path": str(quality_path),
        "daily_quality_sha256": _sha256(quality_path.read_bytes()),
        "total_rows": len(all_rows),
        "days": len(quality_rows),
        "days_with_gaps": sum(int(row["missing_minutes"]) > 0 for row in quality_rows),
    }
    manifest_path = provenance_root / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acquire official Binance Spot 1m klines for offline execution replay")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--archives-root", type=Path)
    parser.add_argument("--download-via-ssh", help="Fetch public archives through an SSH host without writing on that host")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = acquire(
        symbol=args.symbol.upper(),
        interval=args.interval,
        date_from=args.date_from,
        date_to=args.date_to,
        output_root=args.output_root,
        archives_root=args.archives_root,
        download_via_ssh=args.download_via_ssh,
    )
    print(f"manifest={manifest}")


if __name__ == "__main__":
    main()
