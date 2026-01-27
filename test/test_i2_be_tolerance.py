"""Test invariant I2 with BE tolerance for TP1 scenarios."""
import unittest
import importlib.util
import time
from pathlib import Path


def _load_fresh_invariants():
    """Load a fresh invariants module to avoid throttling cache."""
    repo_root = Path(__file__).resolve().parents[1]
    inv_path = repo_root / "executor_mod" / "invariants.py"
    mod_name = f"executor_mod_invariants_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(mod_name, inv_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestI2BETolerance(unittest.TestCase):
    def setUp(self):
        self.inv = _load_fresh_invariants()
        self.sent = []
        self.logged = []
        self.now = 1_000_000.0

        def send_webhook(payload):
            self.sent.append(payload)

        def log_event(*args, **kwargs):
            self.logged.append((args, kwargs))

        def save_state(st):
            pass

        def now_fn():
            return self.now

        env = {
            "INVAR_ENABLED": True,
            "INVAR_THROTTLE_SEC": 600,
            "SYMBOL": "BTCUSDT",
            "TICK_SIZE": "0.01",
            "I2_BE_TOLERANCE_USD": 0.1,  # 10 cents tolerance
        }

        self.inv.configure(
            env=env,
            log_event_fn=log_event,
            send_webhook_fn=send_webhook,
            save_state_fn=save_state,
            now_fn=now_fn,
        )

    def test_i2_accepts_be_exact_entry_long(self):
        """I2 should accept SL exactly at entry for LONG after TP1."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "LONG",
                "tp1_done": True,
                "prices": {
                    "entry": 88258.0,
                    "sl": 88258.0,  # Exact BE
                    "tp1": 88350.0,
                    "tp2": 88450.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 0, f"Expected no I2 error, got: {i2_errors}")

    def test_i2_accepts_be_within_tolerance_long(self):
        """I2 should accept SL within ±10 cents of entry for LONG after TP1."""
        # Test +5 cents
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "LONG",
                "tp1_done": True,
                "prices": {
                    "entry": 88258.0,
                    "sl": 88258.05,  # +5 cents
                    "tp1": 88350.0,
                    "tp2": 88450.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 0)

        # Test -5 cents
        st["position"]["prices"]["sl"] = 88257.95
        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 0)

    def test_i2_rejects_be_beyond_tolerance_long(self):
        """I2 should reject SL beyond ±10 cents of entry for LONG after TP1."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "LONG",
                "tp1_done": True,
                "prices": {
                    "entry": 88258.0,
                    "sl": 88257.85,  # -15 cents (beyond -10 cents tolerance)
                    "tp1": 88350.0,
                    "tp2": 88450.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 1, f"Expected I2 error, got: {self.sent}")
        self.assertEqual(i2_errors[0].get("severity"), "ERROR")

    def test_i2_accepts_be_exact_entry_short(self):
        """I2 should accept SL exactly at entry for SHORT after TP1."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "SHORT",
                "tp1_done": True,
                "prices": {
                    "entry": 88258.0,
                    "sl": 88258.0,  # Exact BE
                    "tp1": 88150.0,
                    "tp2": 88050.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 0)

    def test_i2_enforces_strict_hierarchy_before_tp1_long(self):
        """I2 should enforce sl < entry BEFORE TP1 (no tolerance)."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "LONG",
                "tp1_done": False,  # BEFORE TP1
                "prices": {
                    "entry": 88258.0,
                    "sl": 88258.0,  # NOT allowed before TP1
                    "tp1": 88350.0,
                    "tp2": 88450.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 1, "Expected I2 error before TP1")
        self.assertEqual(i2_errors[0].get("severity"), "ERROR")

    def test_i2_enforces_strict_hierarchy_before_tp1_short(self):
        """I2 should enforce sl > entry BEFORE TP1 (no tolerance)."""
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "side": "SHORT",
                "tp1_done": False,  # BEFORE TP1
                "prices": {
                    "entry": 88258.0,
                    "sl": 88258.0,  # NOT allowed before TP1
                    "tp1": 88150.0,
                    "tp2": 88050.0,
                },
            }
        }

        self.inv._check_i2_exit_price_sanity(st)
        i2_errors = [p for p in self.sent if p.get("inv_id") == "I2"]
        self.assertEqual(len(i2_errors), 1, "Expected I2 error before TP1")
        self.assertEqual(i2_errors[0].get("severity"), "ERROR")


if __name__ == "__main__":
    unittest.main()
