import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import executor
import executor_mod.reconciliation as reconciliation


class TestReconciliationModulePurity(unittest.TestCase):
    def test_no_forbidden_imports(self):
        src = Path(reconciliation.__file__).read_text(encoding="utf-8")
        forbidden = [
            "import executor",
            "executor_mod.binance_api",
            "executor_mod.notifications",
            "executor_mod.state_store",
            "executor_mod.margin_guard",
            "executor_mod.trade_execution_snapshot",
            "executor_mod.trade_close_summary",
            "executor_mod.trade_outcome_archive",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, src)

    def test_direct_exchange_position_exists_minimal_margin_payload(self):
        class FakeApi:
            def margin_account(self):
                return {"userAssets": [{"asset": "BTC", "free": "0.002", "locked": "0", "borrowed": "0", "interest": "0"}]}

        env = {"TRADE_MODE": "margin", "MIN_QTY": 0.001, "MARGIN_DEBT_EPS": 0.01}
        self.assertIs(
            reconciliation.exchange_position_exists("BTCUSDC", env=env, binance_api=FakeApi()),
            True,
        )


class TestReconciliationWrapperCompatibility(unittest.TestCase):
    def setUp(self):
        self._env = deepcopy(executor.ENV)

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self._env)

    def _configure_margin_sync(self):
        executor.ENV.update(
            {
                "TRADE_MODE": "margin",
                "SYMBOL": "BTCUSDC",
                "I13_CLEAR_STATE_ON_EXCHANGE_CLEAR": True,
                "RECON_THROTTLE_SEC": 600,
                "INVAR_THROTTLE_SEC": 600,
            }
        )

    def _p5_state(self):
        return {
            "position": {
                "status": "OPEN",
                "mode": "live",
                "side": "LONG",
                "trade_key": "TK-CURRENT",
                "order_id": 900,
                "qty": 0.03,
                "orders": {"tp1": None, "tp2": None, "sl": None},
                "prices": {"entry": 100.0, "sl": 90.0, "tp1": 110.0, "tp2": 120.0},
            },
            "last_closed": {"trade_key": "STALE"},
            "lock_until": 123.0,
            "margin": {
                "borrowed_by_trade": {"TK-CURRENT": {"asset": "USDC"}},
                "active_trade_key": "TK-CURRENT",
            },
        }

    def test_sync_wrapper_passes_live_clear_dependencies(self):
        self._configure_margin_sync()
        st = self._p5_state()
        snapshots = []
        saves = []
        events = []
        webhooks = []
        archives = []
        margin_hooks = []

        def fake_snapshot(state, source, **kwargs):
            snapshots.append((source, deepcopy(state.get("last_closed")), state.get("position") is not None, kwargs))
            return {"source": source}

        with patch.object(executor.binance_api, "open_orders", side_effect=[[], []]), \
             patch.object(executor, "_exchange_position_exists", return_value=False) as exchange_exists, \
             patch.object(executor, "_record_trade_execution_snapshot", side_effect=fake_snapshot), \
             patch.object(executor.margin_guard, "on_after_position_closed", side_effect=lambda state, trade_key=None: margin_hooks.append(trade_key)), \
             patch.object(executor.trade_outcome_archive, "record_outcome", side_effect=lambda state, source, symbol: archives.append((source, state.get("position"), symbol))), \
             patch.object(executor, "save_state", side_effect=lambda state: saves.append(deepcopy(state))), \
             patch.object(executor, "log_event", side_effect=lambda event, **kw: events.append((event, kw))), \
             patch.object(executor, "send_webhook", side_effect=lambda payload: webhooks.append(deepcopy(payload))), \
             patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"):
            executor.sync_from_binance(st)

        exchange_exists.assert_called_once_with("BTCUSDC")
        self.assertEqual(margin_hooks, ["TK-CURRENT"])
        self.assertEqual(snapshots[0][0], "sync_exchange_clear")
        self.assertEqual(snapshots[0][1]["trade_key"], "TK-CURRENT")
        self.assertIs(snapshots[0][2], True)
        self.assertEqual(snapshots[0][3], {"enrich_exchange": False})
        self.assertIsNone(st["position"])
        self.assertEqual(st["lock_until"], 0.0)
        self.assertEqual(len(saves), 1)
        self.assertIsNone(saves[0]["position"])
        self.assertEqual(archives, [("sync_exchange_clear", None, "BTCUSDC")])
        self.assertEqual(events[0][0], "POSITION_CLEARED_BY_EXCHANGE")
        self.assertEqual(webhooks[0]["event"], "POSITION_CLEARED_BY_EXCHANGE")

    def test_sync_wrapper_uses_live_log_webhook_and_save_for_tagged_recon(self):
        self._configure_margin_sync()
        st = {
            "position": {
                "status": "OPEN",
                "mode": "live",
                "side": "LONG",
                "order_id": 900,
                "orders": {"tp1": 111, "tp2": 222, "sl": None},
            }
        }
        events = []
        webhooks = []
        saves = []

        with patch.object(executor.binance_api, "open_orders", return_value=[{"clientOrderId": "EX_TP2_X", "orderId": 222}]), \
             patch.object(executor.binance_api, "get_order", side_effect=RuntimeError("exchange timeout")), \
             patch.object(executor, "save_state", side_effect=lambda state: saves.append(deepcopy(state))), \
             patch.object(executor, "log_event", side_effect=lambda *args, **kw: events.append((args[0], kw))), \
             patch.object(executor, "send_webhook", side_effect=lambda payload: webhooks.append(deepcopy(payload))), \
             patch.object(executor.time, "time", return_value=1000.0), \
             patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"):
            executor.sync_from_binance(st)

        self.assertEqual(events[0][0], "RECON_ORDER_UNKNOWN")
        self.assertEqual(webhooks[0]["event"], "RECON_ORDER_UNKNOWN")
        self.assertEqual(len(saves), 1)
