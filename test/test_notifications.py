import os
import json
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch
import importlib


class TestNotifications(unittest.TestCase):
    def _reload_notifications_with_env(self, env: dict):
        with mock.patch.dict(os.environ, env, clear=False):
            import executor_mod.notifications as n
            importlib.reload(n)
            return n

    def test_log_event_writes_line(self):
        with tempfile.TemporaryDirectory() as td:
            log_fn = os.path.join(td, "executor.log")
            n = self._reload_notifications_with_env({
                "EXEC_LOG": log_fn,
                "LOG_MAX_LINES": "200",
                "N8N_WEBHOOK_URL": "",
            })

            n.log_event("TEST", a=1)
            with open(log_fn, "r", encoding="utf-8") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 1)
            obj = json.loads(lines[0])
            self.assertEqual(obj["action"], "TEST")
            self.assertEqual(obj["a"], 1)

    def test_log_cap_keeps_last_n(self):
        with tempfile.TemporaryDirectory() as td:
            log_fn = os.path.join(td, "executor.log")
            n = self._reload_notifications_with_env({
                "EXEC_LOG": log_fn,
                "LOG_MAX_LINES": "3",
                "N8N_WEBHOOK_URL": "",
            })

            for i in range(5):
                n.log_event("E", i=i)

            with open(log_fn, "r", encoding="utf-8") as f:
                lines = [json.loads(x) for x in f.readlines()]

            self.assertEqual(len(lines), 3)
            self.assertEqual([x["i"] for x in lines], [2, 3, 4])

    def test_send_webhook_error_logs(self):
        with tempfile.TemporaryDirectory() as td:
            log_fn = os.path.join(td, "executor.log")
            n = self._reload_notifications_with_env({
                "EXEC_LOG": log_fn,
                "LOG_MAX_LINES": "200",
                "N8N_WEBHOOK_URL": "http://example.invalid/webhook",
            })

            with mock.patch("executor_mod.notifications.requests.post", side_effect=RuntimeError("boom")):
                n.send_webhook({"x": 1})

            with open(log_fn, "r", encoding="utf-8") as f:
                objs = [json.loads(x) for x in f.readlines()]

            self.assertTrue(any(o.get("action") == "WEBHOOK_ERROR" for o in objs))

    def test_send_trade_closed_emits_once_with_trade_key(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"trade_key": "TK1", "symbol": "BTCUSDC", "side": "SELL", "entry_price": 100.0, "qty": 0.01}
        sent = []

        with patch.object(n, "send_webhook", side_effect=lambda p: sent.append(p)), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get("event"), "TRADE_CLOSED")
        self.assertEqual(sent[0].get("trade_key"), "TK1")
        self.assertEqual(st.get("last_notified_close_trade_key"), "TK1")

    def test_send_trade_closed_dedup_same_trade_key(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"trade_key": "TK2", "symbol": "BTCUSDC", "side": "SELL"}
        sent = []

        with patch.object(n, "send_webhook", side_effect=lambda p: sent.append(p)), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertEqual(len(sent), 1, "Must emit TRADE_CLOSED only once per trade_key")

    def test_send_trade_closed_no_trade_key_still_emits(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"symbol": "BTCUSDC", "side": "SELL"}
        sent = []

        with patch.object(n, "send_webhook", side_effect=lambda p: sent.append(p)), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get("event"), "TRADE_CLOSED")
        self.assertIsNone(sent[0].get("trade_key"))

    def test_send_trade_closed_fail_soft(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"trade_key": "TK3", "symbol": "BTCUSDC", "side": "SELL"}

        with patch.object(n, "send_webhook", side_effect=RuntimeError("boom")), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")
