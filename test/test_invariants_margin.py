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

    mod_name = f"executor_mod_invariants_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(mod_name, inv_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _payload_inv_id(payload: dict) -> str:
    return payload.get("inv_id") or payload.get("invariant_id") or payload.get("invariant") or ""


class TestInvariantsMargin(unittest.TestCase):
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
            self.saved.append(dict(st))

        env = {
            "INVAR_ENABLED": True,
            "INVAR_THROTTLE_SEC": 0,
            "INVAR_GRACE_SEC": 10,
            "SYMBOL": "BTCUSDT",
        }

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

    def test_spot_mode_noop_for_margin_invariants(self):
        self.inv.ENV["TRADE_MODE"] = "spot"
        self.inv.ENV["MARGIN_BORROW_MODE"] = "manual"
        self.inv.ENV["MARGIN_SIDE_EFFECT"] = "AUTO_BORROW_REPAY"

        st = {
            "position": {
                "mode": "backtest",
                "status": "OPEN",
            },
            "margin": {
                "active_trade_key": "t1",
                "borrowed_assets": {"USDT": 1.0},
                "borrowed_by_trade": {"t1": {"USDT": 1.0}},
            },
            "rt": {
                "borrow_done": {"t2": True},
            },
        }

        self.inv.run(st)
        self.assertEqual(len(self.sent), 0)

    def test_i11_margin_config_sanity_manual_side_effect(self):
        self.inv.ENV["TRADE_MODE"] = "margin"
        self.inv.ENV["MARGIN_BORROW_MODE"] = "manual"
        self.inv.ENV["MARGIN_SIDE_EFFECT"] = "AUTO_BORROW_REPAY"

        st = {
            "position": {
                "mode": "backtest",
                "status": "CLOSED",
            }
        }

        self.inv.run(st)
        self.assertEqual(self._count("I11"), 1)

    def test_i11_margin_config_sanity_auto_side_effect_mismatch(self):
        self.inv.ENV["TRADE_MODE"] = "margin"
        self.inv.ENV["MARGIN_BORROW_MODE"] = "auto"
        self.inv.ENV["MARGIN_SIDE_EFFECT"] = "NO_SIDE_EFFECT"

        st = {
            "position": {
                "mode": "backtest",
                "status": "CLOSED",
            }
        }

        self.inv.run(st)
        self.assertEqual(self._count("I11"), 1)

    def test_i12_trade_key_mismatch_across_hooks(self):
        self.inv.ENV["TRADE_MODE"] = "margin"

        st = {
            "position": {
                "mode": "backtest",
                "status": "OPEN",
            },
            "margin": {
                "active_trade_key": "t1",
            },
            "rt": {
                "borrow_done": {"t2": True},
            },
        }

        self.inv.run(st)
        self.assertEqual(self._count("I12"), 1)

    def test_i13_borrow_tracking_left_after_close(self):
        self.inv.ENV["TRADE_MODE"] = "margin"

        st = {
            "position": {
                "mode": "backtest",
                "status": "CLOSED",
            },
            "margin": {
                "active_trade_key": "t1",
                "borrowed_assets": {"USDT": 1.0},
            },
            "rt": {
                "repay_done": {},
            },
        }

        self.inv.run(st)
        self.assertEqual(self._count("I13"), 1)

    def test_i13_no_emit_when_repay_done_present(self):
        self.inv.ENV["TRADE_MODE"] = "margin"

        st = {
            "position": {
                "mode": "backtest",
                "status": "CLOSED",
            },
            "margin": {
                "active_trade_key": "t1",
                "borrowed_assets": {"USDT": 1.0},
            },
            "rt": {
                "repay_done": {"t1": True},
            },
        }

        self.inv.run(st)
        self.assertEqual(self._count("I13"), 0)


if __name__ == "__main__":
    unittest.main()
