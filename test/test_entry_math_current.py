"""Characterize current executor helpers before extraction.

The first four cases adapt test/test_entry_math.py from reference branch
codex/refactor-executor-finalization-v1 at 46c77e5171995ad60739d4941b754f5377260983.
They call current executor.py, not the reference branch's extracted module.
"""
from decimal import Decimal

import pytest

import executor


@pytest.fixture
def configure(monkeypatch):
    # Update the existing mapping and restore it after each case; modules may
    # share its identity. Do not configure or import the old entry_math module.
    def apply(**overrides):
        for key, value in overrides.items():
            monkeypatch.setitem(executor.ENV, key, value)

    apply(ENTRY_OFFSET_USD=0.03, TICK_SIZE=Decimal("0.1"),
          QTY_STEP=Decimal("0.001"), MIN_QTY=Decimal("0.01"),
          MIN_NOTIONAL=10.0, TP_R_LIST=[1, 2])
    return apply


def test_build_entry_price_rounds_directionally_and_keeps_one_tick_gap(configure):
    assert executor.build_entry_price("long", 100.0) == 100.1
    assert executor.build_entry_price("short", 100.0) == 99.9
    configure(ENTRY_OFFSET_USD=0.25)
    assert executor.build_entry_price("long", 100.0) == 100.2
    assert executor.build_entry_price("short", 100.0) == 99.8


def test_notional_to_qty_floors_to_step(configure):
    assert executor.notional_to_qty(3333.33, 100.0) == 0.03
    assert executor.notional_to_qty(0.0, 100.0) == 0.0
    assert executor.notional_to_qty(-1.0, 100.0) == 0.0


def test_validate_qty_true_and_false_paths(configure):
    assert executor.validate_qty(0.01, 1000.0) is True
    assert executor.validate_qty(0.0, 1000.0) is False
    assert executor.validate_qty(0.005, 1000.0) is False
    assert executor.validate_qty(0.01, 999.0) is False


def test_compute_tps_uses_real_risk(configure):
    assert executor.compute_tps(100.0, 95.0, "BUY") == [105.0, 110.0]
    assert executor.compute_tps(100.0, 105.0, "SELL") == [95.0, 90.0]
    assert executor.compute_tps(100.0, 100.0, "BUY") == []


@pytest.mark.parametrize("side,stop,tick,expected", [
    ("BUY", 98.75, "0.1", [101.2, 102.5]),
    ("SELL", 101.25, "0.1", [98.8, 97.5]),
    ("BUY", 98.75, "0.2", [101.2, 102.4]),
    ("SELL", 101.25, "0.2", [98.8, 97.6]),
])
def test_compute_tps_rounds_non_tick_aligned_targets(configure, side, stop, tick, expected):
    configure(TICK_SIZE=Decimal(tick))
    assert executor.compute_tps(100.0, stop, side) == expected


def test_helpers_use_current_configuration_on_each_call(configure):
    assert executor.notional_to_qty(100.0, 1.05) == 0.01
    configure(QTY_STEP=Decimal("0.0001"))
    assert executor.notional_to_qty(100.0, 1.05) == 0.0105
    assert executor.validate_qty(0.01, 1000.0) is True
    configure(MIN_QTY=Decimal("0.02"))
    assert executor.validate_qty(0.01, 1000.0) is False
    configure(MIN_QTY=Decimal("0.01"), MIN_NOTIONAL=11.0)
    assert executor.validate_qty(0.01, 1000.0) is False
    configure(TP_R_LIST=[0.5, 1.5])
    assert executor.compute_tps(100.0, 98.0, "BUY") == [101.0, 103.0]
