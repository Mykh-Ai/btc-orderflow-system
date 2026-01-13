import importlib
import os
import sys
import types
import unittest

class Column:
    def __init__(self, data):
        self._data = data

    def min(self):
        return min(self._data) if self._data else float("nan")

    def max(self):
        return max(self._data) if self._data else float("nan")


class _ILoc:
    def __init__(self, df):
        self._df = df

    def __getitem__(self, slc):
        if isinstance(slc, slice):
            data = {k: v[slc] for k, v in self._df._data.items()}
            return MiniDF(data)
        raise TypeError("Only slicing supported")


class MiniDF:
    def __init__(self, data):
        self._data = data
        self.iloc = _ILoc(self)

    def __len__(self):
        if not self._data:
            return 0
        return len(next(iter(self._data.values())))

    def __getitem__(self, key):
        return Column(self._data[key])

    @property
    def empty(self):
        return len(self) == 0


def load_buyer():
    repo_root = os.path.abspath(os.path.dirname(__file__))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.SimpleNamespace(DataFrame=object, read_csv=None)
    if "requests" not in sys.modules:
        sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None)
    os.environ.setdefault("QTY_USD", "100")
    os.environ.setdefault("ENTRY_OFFSET_USD", "0.2")
    os.environ.setdefault("SL_PCT", "0.1")
    os.environ.setdefault("TP_SPLIT", "0.5,0.5")
    os.environ.setdefault("TICK_SIZE", "1")
    os.environ.setdefault("QTY_STEP", "0.1")
    module_name = "buyer.buyer"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


class BuyerRiskMathTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_buyer()

    def test_entry_rounding_directional(self):
        entry_long = self.mod.build_entry_price("long", 100.0)
        entry_short = self.mod.build_entry_price("short", 100.0)
        self.assertEqual(entry_long, 100.0)
        self.assertEqual(entry_short, 100.0)

    def test_swing_stop_hi_low_far(self):
        df = MiniDF(
            {
                "LowPrice": [95.0, 90.0, 85.0],
                "HiPrice": [105.0, 110.0, 120.0],
                "low": [95.0, 90.0, 85.0],
                "hi": [105.0, 110.0, 120.0],
            }
        )
        sl_long = self.mod._swing_stop(df, 2, "BUY", 100.0)
        sl_short = self.mod._swing_stop(df, 2, "SELL", 100.0)
        self.assertEqual(sl_long, 85.0)
        self.assertEqual(sl_short, 120.0)

    def test_swing_stop_lookback_240(self):
        rows = 300
        lows = [50.0] * 60 + [100.0] * (rows - 60)
        highs = [150.0] * 60 + [120.0] * (rows - 60)
        df = MiniDF(
            {
                "LowPrice": lows,
                "HiPrice": highs,
                "low": lows,
                "hi": highs,
            }
        )
        sl_long = self.mod._swing_stop(df, rows - 1, "BUY", 100.0)
        sl_short = self.mod._swing_stop(df, rows - 1, "SELL", 100.0)
        self.assertEqual(sl_long, 90.0)
        self.assertEqual(sl_short, 120.0)

    def test_compute_tps_rounding_and_ordering(self):
        tps_long = self.mod._compute_tps(100.0, 99.0, "BUY")
        tps_short = self.mod._compute_tps(100.0, 101.0, "SELL")
        self.assertEqual(tps_long, [101.0, 102.0])
        self.assertEqual(tps_short, [99.0, 98.0])
        self.assertGreater(tps_long[1], tps_long[0])
        self.assertLess(tps_short[1], tps_short[0])


if __name__ == "__main__":
    unittest.main()
