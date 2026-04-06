#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from datetime import datetime, timezone


def _parse_utc_timestamp(raw: Any) -> datetime:
    if raw is None:
        raise ValueError("missing timestamp")
    text = str(raw).strip()
    if not text:
        raise ValueError("missing timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _iter_jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except Exception as exc:
                print(f"watcher skip malformed row path={path} line={line_no} error={exc}", file=sys.stderr)


def _extract_close_record(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    last_closed = row.get("last_closed")
    if not isinstance(last_closed, dict) or not last_closed:
        return None
    close_ts = last_closed.get("ts") or last_closed.get("closed_at") or row.get("ts")
    try:
        _parse_utc_timestamp(close_ts)
    except ValueError:
        return None
    return {
        "schema": row.get("schema"),
        "event": row.get("event"),
        "record_ts": row.get("ts"),
        "symbol": row.get("symbol"),
        "source": row.get("source"),
        "close": last_closed,
    }


def _load_latest_valid_close(trade_outcomes_file: Path) -> dict[str, Any] | None:
    if not trade_outcomes_file.exists():
        print(f"watcher no-op missing trigger file: {trade_outcomes_file}")
        return None

    latest: dict[str, Any] | None = None
    latest_ts = None
    for _, row in _iter_jsonl_rows(trade_outcomes_file):
        close_record = _extract_close_record(row)
        if not close_record:
            continue
        try:
            candidate_ts = _parse_utc_timestamp(
                close_record["close"].get("ts") or close_record["close"].get("closed_at") or close_record.get("record_ts")
            )
        except ValueError:
            continue
        if latest is None or candidate_ts >= latest_ts:
            latest = close_record
            latest_ts = candidate_ts

    if latest is None:
        print(f"watcher no-op no valid close rows found in {trade_outcomes_file}")
    return latest


def _normalized_marker_fields(close_row: dict[str, Any]) -> tuple[str, str, str]:
    close = close_row["close"]
    ts = _parse_utc_timestamp(close.get("ts") or close.get("closed_at") or close_row.get("record_ts"))
    reason = str(close.get("reason") or close.get("close_reason") or "").strip().upper()
    side = str(close.get("side") or "").strip().upper()
    return ts.isoformat(), reason, side


def _processed_marker(close_row: dict[str, Any]) -> str:
    close = close_row["close"]
    trade_key = str(close.get("trade_key") or "").strip()
    if trade_key:
        return f"trade_key:{trade_key}"
    ts, reason, side = _normalized_marker_fields(close_row)
    return f"fallback:{ts}|{reason}|{side}"


def _target_date(close_row: dict[str, Any]) -> str:
    ts, _, _ = _normalized_marker_fields(close_row)
    return ts[:10]


def _load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text(encoding="utf-8"))


def _write_state(state_file: Path, marker: str, close_row: dict[str, Any], target_date: str) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    close = close_row["close"]
    state = {
        "last_processed_marker": marker,
        "last_processed_trade_key": close.get("trade_key"),
        "last_processed_close_ts": close.get("ts") or close.get("closed_at") or close_row.get("record_ts"),
        "last_processed_reason": close.get("reason") or close.get("close_reason"),
        "last_processed_side": close.get("side"),
        "last_processed_date": target_date,
        "last_processed_record_ts": close_row.get("record_ts"),
    }
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"watcher state update success file={state_file} marker={marker}")


def _run_step(name: str, cmd: list[str], project_root: Path, pythonpath: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath
    print(f"watcher step start name={name} cmd={' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=project_root, env=env)
    print(f"watcher step success name={name}")


def run(args: argparse.Namespace) -> int:
    trade_outcomes_file = Path(args.trade_outcomes_file)
    state_file = Path(args.state_file)
    project_root = Path(args.project_root)
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)

    print(f"watcher start trigger={trade_outcomes_file} state={state_file}")
    latest_close = _load_latest_valid_close(trade_outcomes_file)
    if latest_close is None:
        return 0

    marker = _processed_marker(latest_close)
    target_date = _target_date(latest_close)
    close = latest_close["close"]
    print(
        "watcher latest close "
        f"trade_key={close.get('trade_key')} timestamp={close.get('ts') or close.get('closed_at') or latest_close.get('record_ts')} date={target_date} marker={marker}"
    )

    state = _load_state(state_file)
    if state.get("last_processed_marker") == marker:
        print(f"watcher no-op already processed marker={marker}")
        return 0

    python_bin = args.python_bin
    feed_root = args.feed_root
    steps = [
        (
            "build_phase1_derived",
            [python_bin, "scripts/offline/build_phase1_derived.py", "--date", target_date, "--input-root", str(input_root), "--output-root", str(output_root), "--feed-root", feed_root],
        ),
        (
            "build_close_outcomes",
            [
                python_bin,
                "scripts/offline/build_close_outcomes.py",
                "--date",
                target_date,
                "--input-root",
                str(input_root),
                "--output-root",
                str(output_root),
                "--trade-outcomes-file",
                str(trade_outcomes_file),
            ],
        ),
        (
            "build_events_context",
            [
                python_bin,
                "-m",
                "deltascout.delta_analyzer.cli",
                "--archive-glob",
                str(input_root / "archive" / "deltascout" / f"{target_date}.jsonl"),
                "--feed-glob",
                str(Path(feed_root) / f"{target_date}.csv"),
                "--date",
                target_date,
                "--output-root",
                str(output_root),
            ],
        ),
        (
            "delta_analyzer_review",
            [
                python_bin,
                "-m",
                "deltascout.delta_analyzer.cli",
                "--build-review",
                "--date",
                target_date,
                "--input-root",
                str(output_root),
                "--output-root",
                str(output_root),
            ],
        ),
    ]

    try:
        for name, cmd in steps:
            _run_step(name, cmd, project_root=project_root, pythonpath=str(project_root))
    except subprocess.CalledProcessError as exc:
        print(f"watcher failure step={name} exit_code={exc.returncode}", file=sys.stderr)
        return exc.returncode or 1

    _write_state(state_file, marker, latest_close, target_date)
    print(f"watcher success date={target_date} marker={marker}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DeltaScout post-close research pipeline once for the latest new close event.")
    parser.add_argument("--project-root", default="/root/volume-alert", help="Project root used as subprocess cwd and PYTHONPATH.")
    parser.add_argument("--input-root", default="/root/volume-alert/data", help="Input root for offline builders.")
    parser.add_argument("--output-root", default="/root/volume-alert/data/archive/datasets", help="Dataset output root for offline builders and review build.")
    parser.add_argument("--trade-outcomes-file", default="/root/volume-alert/data/state/trade_outcomes.jsonl", help="Canonical append-only close/outcome journal.")
    parser.add_argument("--state-file", default="/root/volume-alert/data/state/post_close_watcher_state.json", help="Watcher state file updated only after full success.")
    parser.add_argument("--feed-root", default="/opt/aitrader/feed", help="External feed root containing enriched YYYY-MM-DD.csv files.")
    parser.add_argument("--python-bin", default="/opt/aitrader/.venv/bin/python", help="Python interpreter used for subprocess pipeline steps.")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
