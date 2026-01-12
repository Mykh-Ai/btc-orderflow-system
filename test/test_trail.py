import tempfile
import unittest

import executor_mod.trail as trail


class TestTrailModule(unittest.TestCase):
    def setUp(self) -> None:
        # Preserve module globals to avoid leaking state between tests (or other test modules).
        self._old_env = trail.ENV
        self._old_read_tail_lines = trail.read_tail_lines
        self._tmp_paths: list[str] = []

    def tearDown(self) -> None:
        trail.ENV = self._old_env
        trail.read_tail_lines = self._old_read_tail_lines
        import os
        for p in self._tmp_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _configure_with_file(self, env: dict) -> None:
        def _rtl(path: str, n: int) -> list[str]:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                lines = f.readlines()
            if n <= 0:
                return []
            return lines[-n:]
        trail.configure(env, _rtl)

    def _write_agg_csv(self, rows: list[list[str]], header: list[str] | None = None) -> str:
        header = header or trail.AGG_HEADER_V2
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, newline="")
        with tmp as f:
            f.write(",".join(header) + "\n")
            for row in rows:
                f.write(",".join(row) + "\n")
        self._tmp_paths.append(tmp.name)
        return tmp.name

    def test_read_last_close_prices_returns_parsed_closes(self) -> None:
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "100.0", "101.0", "101.5", "99.5"],
            ["2025-01-01 00:01:00", "1", "0.1", "0.1", "0.1", "0", "102.0", "102.0", "102.5", "101.5"],
            ["2025-01-01 00:02:00", "1", "0.1", "0.1", "0.1", "0", "103.0", "103.0", "103.5", "102.5"],
        ]
        path = self._write_agg_csv(rows)
        self._configure_with_file({"QTY_STEP": None})
        closes = trail._read_last_close_prices_from_agg_csv(path, 2)
        self.assertEqual(closes, [102.0, 103.0])

    def test_read_last_close_prices_n_rows_le_zero(self) -> None:
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "100.0", "101.0", "101.5", "99.5"],
            ["2025-01-01 00:01:00", "1", "0.1", "0.1", "0.1", "0", "102.0", "102.0", "102.5", "101.5"],
        ]
        path = self._write_agg_csv(rows)
        self._configure_with_file({"QTY_STEP": None})
        self.assertEqual(trail._read_last_close_prices_from_agg_csv(path, 0), [])
        self.assertEqual(trail._read_last_close_prices_from_agg_csv(path, -1), [])

    def test_read_last_close_prices_malformed_rows_are_skipped(self) -> None:
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "100.0", "101.0", "101.5", "99.5"],
            ["2025-01-01 00:01:00", "1", "0.1", "0.1", "0.1", "0", "102.0", "bad", "102.5", "101.5"],
        ]
        path = self._write_agg_csv(rows)
        self._configure_with_file({"QTY_STEP": None})
        closes = trail._read_last_close_prices_from_agg_csv(path, 10)
        self.assertEqual(closes, [101.0])

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
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "10.0", "10.0", "10.1", "9.9"],
            ["2025-01-01 00:01:00", "1", "0.1", "0.1", "0.1", "0", "9.0", "9.0", "9.1", "8.9"],
            ["2025-01-01 00:02:00", "1", "0.1", "0.1", "0.1", "0", "8.0", "8.0", "8.1", "7.9"],
            ["2025-01-01 00:03:00", "1", "0.1", "0.1", "0.1", "0", "9.0", "9.0", "9.1", "8.9"],
            ["2025-01-01 00:04:00", "1", "0.1", "0.1", "0.1", "0", "10.0", "10.0", "10.1", "9.9"],
        ]
        path = self._write_agg_csv(rows)
        env = {
            "AGG_CSV": path,
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_file(env)
        pos = {"side": "LONG"}
        stop = trail._trail_desired_stop_from_agg(pos)
        self.assertEqual(stop, 7.4)

    def test_trail_desired_stop_short(self) -> None:
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "1.0", "1.0", "1.1", "0.9"],
            ["2025-01-01 00:01:00", "1", "0.1", "0.1", "0.1", "0", "2.0", "2.0", "2.1", "1.9"],
            ["2025-01-01 00:02:00", "1", "0.1", "0.1", "0.0", "0.1", "3.0", "3.5", "3.6", "3.4"],
            ["2025-01-01 00:03:00", "1", "0.1", "0.1", "0.0", "0.1", "2.0", "2.0", "2.1", "1.9"],
            ["2025-01-01 00:04:00", "1", "0.1", "0.1", "0.0", "0.1", "1.0", "1.0", "1.1", "0.9"],
        ]
        path = self._write_agg_csv(rows)
        env = {
            "AGG_CSV": path,
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_file(env)
        pos = {"side": "SHORT"}
        stop = trail._trail_desired_stop_from_agg(pos)
        self.assertEqual(stop, 4.1)

    def test_trail_desired_stop_no_path(self) -> None:
        rows = [
            ["2025-01-01 00:00:00", "1", "0.1", "0.1", "0.1", "0", "10.0", "10.0", "10.1", "9.9"],
        ]
        self._write_agg_csv(rows)
        env = {
            "AGG_CSV": "",
            "TRAIL_SWING_LOOKBACK": 50,
            "TRAIL_SWING_LR": 2,
            "TRAIL_SWING_BUFFER_USD": 0.5,
        }
        self._configure_with_file(env)
        pos = {"side": "LONG"}
        self.assertIsNone(trail._trail_desired_stop_from_agg(pos))

if __name__ == "__main__":
    unittest.main()
