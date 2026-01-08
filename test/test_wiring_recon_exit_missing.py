import pathlib
import unittest


class TestWiringReconExitMissing(unittest.TestCase):
    def test_executor_has_recon_exit_missing_event(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        txt = (root / "executor.py").read_text(encoding="utf-8")
        self.assertIn("RECON_EXIT_MISSING", txt)


if __name__ == "__main__":
    unittest.main()
