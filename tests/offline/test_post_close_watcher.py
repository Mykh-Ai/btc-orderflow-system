from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from scripts.offline.run_post_close_watcher import (
    _load_latest_valid_close,
    _processed_marker,
    run,
)


def _args(tmp_path: Path, trade_file: Path, state_file: Path) -> Namespace:
    return Namespace(
        project_root=str(tmp_path),
        input_root=str(tmp_path / "data"),
        output_root=str(tmp_path / "data" / "archive" / "datasets"),
        trade_outcomes_file=str(trade_file),
        state_file=str(state_file),
        python_bin="/usr/bin/python3",
    )


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _valid_row(*, ts: str = "2026-01-01T00:30:00Z", trade_key: str | None = "TK-1", reason: str = "TP1", side: str = "LONG") -> dict[str, Any]:
    last_closed: dict[str, Any] = {"ts": ts, "reason": reason, "side": side, "mode": "paper", "close_price": 101.0}
    if trade_key is not None:
        last_closed["trade_key"] = trade_key
    return {
        "schema": 2,
        "event": "EXEC_CLOSE",
        "ts": ts,
        "symbol": "BTCUSDC",
        "source": "executor",
        "last_closed": last_closed,
    }


def test_missing_trade_outcomes_file_noop(tmp_path):
    trade_file = tmp_path / "missing.jsonl"
    state_file = tmp_path / "state.json"

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 0
    assert not state_file.exists()


def test_empty_trade_outcomes_file_noop(tmp_path):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    state_file = tmp_path / "state.json"
    _write_lines(trade_file, [])

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 0
    assert not state_file.exists()


def test_malformed_rows_before_valid_row_still_processed(tmp_path, monkeypatch):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    state_file = tmp_path / "state.json"
    _write_lines(trade_file, ["not-json", json.dumps({"foo": "bar"}), json.dumps(_valid_row())])
    calls: list[list[str]] = []

    def fake_run(cmd, check, cwd, env):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scripts.offline.run_post_close_watcher.subprocess.run", fake_run)

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 0
    assert len(calls) == 3
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["last_processed_marker"] == "trade_key:TK-1"


def test_latest_row_already_processed_noop_no_subprocess_calls(tmp_path, monkeypatch):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    row = _valid_row(trade_key="TK-2")
    _write_lines(trade_file, [json.dumps(row)])
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"last_processed_marker": "trade_key:TK-2"}), encoding="utf-8")

    def fail_run(*args, **kwargs):  # pragma: no cover
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr("scripts.offline.run_post_close_watcher.subprocess.run", fail_run)

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 0


def test_new_valid_row_runs_pipeline_in_order(tmp_path, monkeypatch):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    _write_lines(trade_file, [json.dumps(_valid_row(ts="2026-01-02T01:30:00Z", trade_key="TK-3"))])
    state_file = tmp_path / "state.json"
    calls: list[list[str]] = []

    def fake_run(cmd, check, cwd, env):
        calls.append(cmd)
        assert env["PYTHONPATH"] == str(tmp_path)
        assert cwd == tmp_path
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scripts.offline.run_post_close_watcher.subprocess.run", fake_run)

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 0
    assert calls == [
        ["/usr/bin/python3", "scripts/offline/build_phase1_derived.py", "--date", "2026-01-02", "--input-root", str(tmp_path / "data"), "--output-root", str(tmp_path / "data" / "archive" / "datasets")],
        ["/usr/bin/python3", "scripts/offline/build_close_outcomes.py", "--date", "2026-01-02", "--input-root", str(tmp_path / "data"), "--output-root", str(tmp_path / "data" / "archive" / "datasets"), "--trade-outcomes-file", str(trade_file)],
        ["/usr/bin/python3", "-m", "deltascout.delta_analyzer.cli", "--build-review", "--date", "2026-01-02", "--input-root", str(tmp_path / "data" / "archive" / "datasets"), "--output-root", str(tmp_path / "data" / "archive" / "datasets")],
    ]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["last_processed_marker"] == "trade_key:TK-3"
    assert state["last_processed_date"] == "2026-01-02"


@pytest.mark.parametrize("failing_step", [0, 1, 2])
def test_pipeline_failure_does_not_update_state(tmp_path, monkeypatch, failing_step):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    _write_lines(trade_file, [json.dumps(_valid_row(trade_key="TK-4"))])
    state_file = tmp_path / "state.json"
    calls: list[list[str]] = []

    def fake_run(cmd, check, cwd, env):
        idx = len(calls)
        calls.append(cmd)
        if idx == failing_step:
            raise subprocess.CalledProcessError(returncode=7, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scripts.offline.run_post_close_watcher.subprocess.run", fake_run)

    rc = run(_args(tmp_path, trade_file, state_file))

    assert rc == 7
    assert len(calls) == failing_step + 1
    assert not state_file.exists()


def test_trade_key_based_processed_marker_works(tmp_path):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    _write_lines(trade_file, [json.dumps(_valid_row(trade_key="TK-555"))])

    latest = _load_latest_valid_close(trade_file)

    assert latest is not None
    assert _processed_marker(latest) == "trade_key:TK-555"


def test_fallback_processed_marker_works_without_trade_key(tmp_path):
    trade_file = tmp_path / "trade_outcomes.jsonl"
    _write_lines(trade_file, [json.dumps(_valid_row(trade_key=None, ts="2026-01-03T05:45:00Z", reason="sl", side="short"))])

    latest = _load_latest_valid_close(trade_file)

    assert latest is not None
    assert _processed_marker(latest) == "fallback:2026-01-03T05:45:00+00:00|SL|SHORT"
