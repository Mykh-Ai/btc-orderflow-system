import unittest

import executor_mod.trail as trail


class TestTrailModule(unittest.TestCase):
    def setUp(self) -> None:
        # Preserve module globals to avoid leaking state between tests (or other test modules).
        self._old_env = trail.ENV
        self._old_read_tail_lines = trail.read_tail_lines

    def tearDown(self) -> None:
        trail.ENV = self._old_env
        trail.read_tail_lines = self._old_read_tail_lines

    def _configure_with_lines(self, env: dict, lines: list[str]) -> None:
        def _rtl(_path: str, _n: int) -> list[str]:
            return list(lines)
        trail.configure(env, _rtl)

    def test_read_last_close_prices_returns_parsed_closes(self) -> None:
        lines = [
            "noise line\n",
            "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n",
            "2025-01-01 00:00:00,1,0.1,0.1,0.1,0,100.0,101.0\n",
            "2025-01-01 00:01:00,1,0.1,0.1,0.1,0,102.0\n",  # no ClosePrice -> fallback to AvgPrice
            "2025-01-01 00:02:00,1,0.1,0.1,0.1,0,103.0,abc\n",  # invalid -> skipped
        ]
        self._configure_with_lines({"QTY_STEP": None}, lines)
        closes = trail._read_last_close_prices_from_agg_csv("dummy.csv", 10)
        self.assertEqual(closes, [101.0, 102.0])

    def test_read_last_close_prices_n_rows_le_zero(self) -> None:
        self._configure_with_lines({"QTY_STEP": None}, ["Timestamp,...\n"])
        self.assertEqual(trail._read_last_close_prices_from_agg_csv("dummy.csv", 0), [])
        self.assertEqual(trail._read_last_close_prices_from_agg_csv("dummy.csv", -1), [])

    def test_find_last_fractal_swing_low(self) -> None:
        series = [10.0, 9.0, 8.0, 9.0, 10.0]
        swing = trail._find_last_fractal_swing(series, lr=2, kind="low")
        self.assertEqual(swing, 8.0)

    def test_find_last_fractal_swing_high(self) -> None:
        series = [1.0, 2.0, 3.0, 2.0, 1.0]
        swing = trail._find_last_fractal_swing(series, lr=2, kind="high")
        self.assertEqual(swing, 3.0)

    def test_find_last_fractal_swing_lr_clamped_to_1(self) -> None:
        # lr < 1 should be clamped to 1 (as in code)
        series = [2.0, 1.0, 2.0]
        swing = trail._find_last_fractal_swing(series, lr=0, kind="low")
        self.assertEqual(swing, 1.0)

    def test_trail_desired_stop_long(self) -> None:
        lines = [
            "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n",
            "2025-01-01 00:00:00,1,0.1,0.1,0.1,0,10.0,10.0\n",
            "2025-01-01 00:01:00,1,0.1,0.1,0.1,0,9.0,9.0\n",
            "2025-01-01 00:02:00,1,0.1,0.1,0.1,0,8.0,8.0\n",
            "2025-01-01 00:03:00,1,0.1,0.1,0.1,0,9.0,9.0\n",
            "2025-01-01 00:04:00,1,0.1,0.1,0.1,0,10.0,10.0\n",
        ]
        env = {
            "AGG_CSV": "dummy.csv",
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_lines(env, lines)
        pos = {"side": "LONG"}
        stop = trail._trail_desired_stop_from_agg(pos)
        self.assertEqual(stop, 7.5)

    def test_trail_desired_stop_short(self) -> None:
        lines = [
            "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n",
            "2025-01-01 00:00:00,1,0.1,0.1,0.1,0,1.0,1.0\n",
            "2025-01-01 00:01:00,1,0.1,0.1,0.1,0,2.0,2.0\n",
            "2025-01-01 00:02:00,1,0.1,0.1,0.0,0.1,3.0,3.5\n",
            "2025-01-01 00:03:00,1,0.1,0.1,0.0,0.1,2.0,2.0\n",
            "2025-01-01 00:04:00,1,0.1,0.1,0.0,0.1,1.0,1.0\n",
        ]
        env = {
            "AGG_CSV": "dummy.csv",
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_lines(env, lines)
        pos = {"side": "SHORT"}
        stop = trail._trail_desired_stop_from_agg(pos)
        self.assertEqual(stop, 4)

    def test_trail_desired_stop_no_path(self) -> None:
        lines = [
            "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice\n",
            "2025-01-01 00:00:00,1,0.1,0.1,0.1,0,10.0,10.0\n",
        ]
        env = {
            "AGG_CSV": "",
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_lines(env, lines)
        pos = {"side": "LONG"}
        self.assertIsNone(trail._trail_desired_stop_from_agg(pos))

if __name__ == "__main__":
    unittest.main()