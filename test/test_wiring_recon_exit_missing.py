import pathlib
import unittest


class TestWiringReconExitMissing(unittest.TestCase):
    def test_executor_has_recon_exit_missing_event(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        executor_txt = (root / "executor.py").read_text(encoding="utf-8")
        reconciliation_txt = (root / "executor_mod" / "reconciliation.py").read_text(encoding="utf-8")
        self.assertIn("reconciliation.sync_from_binance", executor_txt)
        self.assertIn("RECON_ORDER_MISSING", reconciliation_txt)
        self.assertIn("RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE", reconciliation_txt)
        self.assertIn("RECON_ORDER_UNKNOWN", reconciliation_txt)
        self.assertIn("binance_api.get_order", reconciliation_txt)


if __name__ == "__main__":
    unittest.main()
