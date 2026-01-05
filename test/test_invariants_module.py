import importlib.util
import inspect
import time
import unittest
from pathlib import Path


def _load_invariants_module():
    repo_root = Path(__file__).resolve().parents[1]
    inv_path = repo_root / "executor_mod" / "invariants.py"
    if not inv_path.exists():
        raise FileNotFoundError(f"Missing invariants.py at: {inv_path}")

    # Load a fresh module per test run (avoid global caches like _last_emit carrying over).
    mod_name = f"executor_mod_invariants_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(mod_name, inv_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _payload_inv_id(payload: dict) -> str:
    # Support both naming styles if they change in code.
    return (
        payload.get("inv_id")
        or payload.get("invariant_id")
        or payload.get("invariant")
        or ""
    )


class TestInvariantsModule(unittest.TestCase):
    def setUp(self):
        self.inv = _load_invariants_module()

        self.sent = []
        self.logged = []
        self.saved = []
        self.now = 1_000_000.0

        def now_fn():
            return self.now

        def send_webhook(payload):
            self.sent.append(payload)

        def log_event(*args, **kwargs):
            self.logged.append((args, kwargs))

        def save_state(st):
            # snapshot, but minimal
            self.saved.append(dict(st))

        env = {
            "INVAR_ENABLED": True,
            "INVAR_THROTTLE_SEC": 600,
            "INVAR_GRACE_SEC": 10,
            "SYMBOL": "BTCUSDT",
            # keep optional fields safe:
            "TRAIL_SOURCE": "AGG",
            "AGG_CSV": "X:/nonexistent/agg.csv",
        }

        # Configure with only the args that exist in current signature
        cfg = self.inv.configure
        sig = inspect.signature(cfg)
        kwargs = {
            "env": env,
            "log_event_fn": log_event,
            "send_webhook_fn": send_webhook,
            "save_state_fn": save_state,
            "now_fn": now_fn,
        }
        kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        cfg(**kwargs)

    def _count(self, inv_id: str) -> int:
        return sum(1 for p in self.sent if _payload_inv_id(p) == inv_id)

    def test_throttle_blocks_repeat_for_same_invariant(self):
        # Call a single check directly so we don't trigger other invariants.
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "orders": None,
                "prices": None,
            }
        }

        self.inv._check_i8_state_shape_live_position(st)
        self.assertEqual(self._count("I8"), 1)

        # within throttle => still 1
        self.now += 20
        self.inv._check_i8_state_shape_live_position(st)
        self.assertEqual(self._count("I8"), 1)

        # after throttle => becomes 2
        self.now += 601
        self.inv._check_i8_state_shape_live_position(st)
        self.assertEqual(self._count("I8"), 2)

    def test_i7_error_after_grace_when_tp_missing(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "trail_active": False,
                "orders": {},  # missing tp1/tp2
                "opened_s": self.now - 30,  # age 30 > grace 10 => ERROR
            }
        }

        self.inv._check_i7_tp_orders_after_fill(st)
        self.assertEqual(self._count("I7"), 1)

        payload = next(p for p in self.sent if _payload_inv_id(p) == "I7")
        self.assertEqual(payload.get("severity"), "ERROR")

    def test_i8_warn_when_opened_missing(self):
        # opened_s missing -> age fallback should produce WARN (not ERROR)
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN_FILLED",
                "orders": None,
                "prices": None,
            }
        }

        self.inv._check_i8_state_shape_live_position(st)
        self.assertEqual(self._count("I8"), 1)

        payload = next(p for p in self.sent if _payload_inv_id(p) == "I8")
        self.assertEqual(payload.get("severity"), "WARN")

    def test_i9_trail_active_missing_sl_warn_then_error(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "trail_active": True,
                "orders": {},
                "prices": {},
                "opened_s": self.now,
            }
        }

        self.inv._check_i9_trail_active_sl_missing(st)
        self.assertEqual(self._count("I9"), 1)
        payload = next(p for p in self.sent if _payload_inv_id(p) == "I9")
        self.assertEqual(payload.get("severity"), "WARN")

        # After grace => ERROR
        self.now += 601
        st["position"]["opened_s"] = self.now - 20
        self.inv._check_i9_trail_active_sl_missing(st)
        self.assertEqual(self._count("I9"), 2)
        payload = [p for p in self.sent if _payload_inv_id(p) == "I9"][-1]
        self.assertEqual(payload.get("severity"), "ERROR")

    def test_i10_repeated_trail_errors_throttled(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "trail_active": True,
            }
        }

        for delta in (30, 20, 10):
            st["position"]["trail_last_error_code"] = -2010
            st["position"]["trail_last_error_s"] = self.now - delta
            self.inv._check_i10_repeated_trail_stop_errors(st)

        self.assertEqual(self._count("I10"), 1)
        payload = next(p for p in self.sent if _payload_inv_id(p) == "I10")
        self.assertEqual(payload.get("severity"), "WARN")

        # Within throttle, should not emit again
        self.inv.ENV["INVAR_THROTTLE_SEC"] = 60
        st["position"]["trail_last_error_code"] = -2010
        st["position"]["trail_last_error_s"] = self.now - 5
        self.inv._check_i10_repeated_trail_stop_errors(st)
        self.assertEqual(self._count("I10"), 1)


if __name__ == "__main__":
    unittest.main()
