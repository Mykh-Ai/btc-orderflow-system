import ast
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

import executor_mod.entry_math as entry_math
import executor_mod.risk_math as risk_math


def _configure(**overrides):
    env = {
        "ENTRY_OFFSET_USD": 0.03,
        "TICK_SIZE": Decimal("0.1"),
        "QTY_STEP": Decimal("0.001"),
        "MIN_QTY": Decimal("0.01"),
        "MIN_NOTIONAL": 10.0,
        "SL_PCT": 0.01,
        "SWING_MINS": 50,
        "TP_R_LIST": [1, 2],
        "PLANB_MAX_DEV_R_MULT": 0.5,
        "PLANB_MAX_DEV_USD": 0.0,
        "PLANB_ABORT_IF_PAST_TP1": True,
    }
    env.update(overrides)
    risk_math.configure(env)
    entry_math.configure(env)
    return env


class TestEntryMath(unittest.TestCase):
    def setUp(self):
        self._prev_entry_env = entry_math.ENV
        self._prev_risk_env = risk_math.ENV

    def tearDown(self):
        entry_math.configure(self._prev_entry_env)
        risk_math.configure(self._prev_risk_env)

    def test_build_entry_price_rounds_directionally_and_keeps_one_tick_gap(self):
        _configure(ENTRY_OFFSET_USD=0.03, TICK_SIZE=Decimal("0.1"))
        self.assertEqual(entry_math.build_entry_price("long", 100.0), 100.1)
        self.assertEqual(entry_math.build_entry_price("short", 100.0), 99.9)

        _configure(ENTRY_OFFSET_USD=0.25, TICK_SIZE=Decimal("0.1"))
        self.assertEqual(entry_math.build_entry_price("long", 100.0), 100.2)
        self.assertEqual(entry_math.build_entry_price("short", 100.0), 99.8)

    def test_notional_to_qty_floors_to_step(self):
        _configure(QTY_STEP=Decimal("0.001"))
        self.assertEqual(entry_math.notional_to_qty(3333.33, 100.0), 0.03)
        self.assertEqual(entry_math.notional_to_qty(0.0, 100.0), 0.0)
        self.assertEqual(entry_math.notional_to_qty(-1.0, 100.0), 0.0)

    def test_validate_qty_true_and_false_paths(self):
        _configure(MIN_QTY=Decimal("0.01"), MIN_NOTIONAL=10.0)
        self.assertTrue(entry_math.validate_qty(0.01, 1000.0))
        self.assertFalse(entry_math.validate_qty(0.0, 1000.0))
        self.assertFalse(entry_math.validate_qty(0.005, 1000.0))
        self.assertFalse(entry_math.validate_qty(0.01, 999.0))

    def test_swing_stop_far_uses_agg_high_low(self):
        _configure(SL_PCT=0.01, SWING_MINS=50, TICK_SIZE=Decimal("0.1"))
        df = pd.DataFrame({
            "price": [100, 101, 102, 103, 104],
            "LowPrice": [100, 98, 96, 97, 99],
            "HiPrice": [100, 102, 105, 106, 107],
        })

        self.assertEqual(entry_math.swing_stop_far(df, 4, "BUY", 100.0), 96.0)
        self.assertEqual(entry_math.swing_stop_far(df, 4, "SELL", 100.0), 107.0)

    def test_swing_stop_far_nan_fallbacks_to_price(self):
        _configure(SL_PCT=0.01, SWING_MINS=50, TICK_SIZE=Decimal("0.1"))
        df = pd.DataFrame({
            "price": [100, 101, 102, 103, 104],
            "LowPrice": [float("nan")] * 5,
            "HiPrice": [float("nan")] * 5,
        })

        self.assertEqual(entry_math.swing_stop_far(df, 4, "BUY", 100.0), 99.0)
        self.assertEqual(entry_math.swing_stop_far(df, 4, "SELL", 100.0), 104.0)

    def test_compute_tps_uses_real_risk_and_directional_rounding(self):
        _configure(TP_R_LIST=[1, 2], TICK_SIZE=Decimal("0.1"))
        self.assertEqual(entry_math.compute_tps(100.0, 95.0, "BUY"), [105.0, 110.0])
        self.assertEqual(entry_math.compute_tps(100.0, 105.0, "SELL"), [95.0, 90.0])
        self.assertEqual(entry_math.compute_tps(100.0, 100.0, "BUY"), [])

    def test_planb_market_allowed_allows_within_deviation(self):
        _configure(PLANB_MAX_DEV_R_MULT=0.5, PLANB_MAX_DEV_USD=0.0, PLANB_ABORT_IF_PAST_TP1=True)
        pos = {"side": "LONG", "prices": {"entry": 100.0, "sl": 90.0, "tp1": 120.0}}

        ok, reason, info = entry_math._planb_market_allowed(pos, 104.0)

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(info["risk"], 10.0)
        self.assertEqual(info["dev"], 4.0)
        self.assertEqual(info["max_dev"], 5.0)

    def test_planb_market_allowed_denies_large_deviation_and_past_tp1(self):
        _configure(PLANB_MAX_DEV_R_MULT=0.5, PLANB_MAX_DEV_USD=0.0, PLANB_ABORT_IF_PAST_TP1=True)
        pos = {"side": "LONG", "prices": {"entry": 100.0, "sl": 90.0, "tp1": 120.0}}

        ok, reason, info = entry_math._planb_market_allowed(pos, 106.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "deviation_too_large")
        self.assertEqual(info["dev"], 6.0)

        _configure(PLANB_MAX_DEV_R_MULT=5.0, PLANB_MAX_DEV_USD=0.0, PLANB_ABORT_IF_PAST_TP1=True)
        ok, reason, info = entry_math._planb_market_allowed(pos, 120.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_tp1")
        self.assertEqual(info["tp1"], 120.0)

    def test_planb_market_allowed_bad_prices(self):
        _configure()
        self.assertEqual(entry_math._planb_market_allowed({"prices": {}}, 100.0), (False, "bad_prices", {}))

    def test_module_purity(self):
        source = Path(entry_math.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        self.assertNotIn("executor", imported)
        for forbidden in (
            "binance_api",
            "save_state",
            "load_state",
            "log_event",
            "send_webhook",
            "margin_guard",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
