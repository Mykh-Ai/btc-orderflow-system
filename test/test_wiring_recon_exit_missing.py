import pathlib
import unittest


class TestWiringReconExitMissing(unittest.TestCase):
    def test_executor_has_recon_exit_missing_event(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        txt = (root / "executor.py").read_text(encoding="utf-8")
        # Event name evolved: RECON_EXIT_MISSING -> RECON_ORDER_MISSING (+ others)
        candidates = (
            "RECON_EXIT_MISSING",                 # legacy
            "RECON_ORDER_MISSING",                # current
            "RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE",  # visibility (no auto-repair)
            "RECON_ORDER_UNKNOWN",                # exchange ambiguity
        )
        self.assertTrue(
            any(c in txt for c in candidates),
            f"None of expected recon events found in executor.py: {candidates}",
        )


if __name__ == "__main__":
    unittest.main()
