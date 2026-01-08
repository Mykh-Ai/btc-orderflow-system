import pathlib
import unittest


class TestWiringMarketData(unittest.TestCase):
    def test_executor_wires_market_data(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        txt = (root / "executor.py").read_text(encoding="utf-8")
        self.assertIn("market_data.configure(ENV)", txt)


if __name__ == "__main__":
    unittest.main()
