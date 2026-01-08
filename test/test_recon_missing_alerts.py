import pathlib
import unittest


class TestReconMissingAlerts(unittest.TestCase):
    def test_executor_recon_missing_wiring(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        txt = (root / "executor.py").read_text(encoding="utf-8")
        self.assertIn("RECON_ORDER_MISSING", txt)
        self.assertIn("binance_api.get_order", txt)
        self.assertNotIn("tp2_done = True", txt)


if __name__ == "__main__":
    unittest.main()
