import unittest
from pathlib import Path


class TestExecutorInvariantsWiring(unittest.TestCase):
    def test_executor_has_invariants_configure_and_run(self):
        repo_root = Path(__file__).resolve().parents[1]
        executor_py = repo_root / "executor.py"
        self.assertTrue(executor_py.exists(), f"Missing executor.py at {executor_py}")

        src = executor_py.read_text(encoding="utf-8", errors="replace")

        self.assertIn("invariants.configure", src)
        self.assertIn("invariants.run", src)

        # ensure save_state passed into configure (important for persisted throttle)
        self.assertIn("save_state_fn", src)


if __name__ == "__main__":
    unittest.main()
