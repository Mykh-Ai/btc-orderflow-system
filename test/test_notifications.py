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

        def mock_webhook(p):
            sent.append(p)
            return True  # simulate successful delivery

        with patch.object(n, "send_webhook", side_effect=mock_webhook), \
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

        def mock_webhook(p):
            sent.append(p)
            return True

        with patch.object(n, "send_webhook", side_effect=mock_webhook), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertEqual(len(sent), 1, "Must emit TRADE_CLOSED only once per trade_key")
        self.assertEqual(st.get("last_notified_close_trade_key"), "TK2")

    def test_send_trade_closed_dedup_persists_trade_key(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"trade_key": "TKDUP", "symbol": "BTCUSDC", "side": "SELL"}
        sent = []

        def mock_webhook(p, *a, **k):
            sent.append(p)
            return True

        with patch.object(n, "send_webhook", side_effect=mock_webhook), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "MANUAL", mode="live")
            self.assertEqual(st.get("last_notified_close_trade_key"), "TKDUP")
            n.send_trade_closed(st, pos, "MANUAL", mode="live")

        self.assertEqual(len(sent), 1)

    def test_trade_closed_details_fallback_to_last_closed(self):
        import executor_mod.notifications as n
        st = {"last_closed": {"details": {"manual_close": {"src": "last_closed"}}}}
        pos = {"trade_key": "TK_FALLBACK", "symbol": "BTCUSDC", "side": "LONG"}
        sent = []

        def mock_webhook(p, *a, **k):
            sent.append(p)
            return True

        with patch.object(n, "send_webhook", side_effect=mock_webhook), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "REASON", mode="live")

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get("details", {}).get("manual_close", {}).get("src"), "last_closed")

    def test_send_trade_closed_no_trade_key_still_emits(self):
        import executor_mod.notifications as n
        st = {}
        pos = {"symbol": "BTCUSDC", "side": "SELL"}
        sent = []

        def mock_webhook(p):
            sent.append(p)
            return True

        with patch.object(n, "send_webhook", side_effect=mock_webhook), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get("event"), "TRADE_CLOSED")
        self.assertIsNone(sent[0].get("trade_key"))

    def test_send_trade_closed_fail_soft(self):
        """send_trade_closed must not raise even if send_webhook raises"""
        import executor_mod.notifications as n
        st = {}
        pos = {"trade_key": "TK3", "symbol": "BTCUSDC", "side": "SELL"}

        with patch.object(n, "send_webhook", side_effect=RuntimeError("boom")), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        # Dedup key should NOT be set when webhook raises
        self.assertNotIn("last_notified_close_trade_key", st, "Dedup key must NOT be set when send_webhook raises")

    def test_close_webhook_fail_does_not_set_dedup(self):
        """Phase 2: Exception in webhook should NOT set dedup key"""
        import executor_mod.notifications as n
        import requests.exceptions
        st = {}
        pos = {"trade_key": "TK_FAIL", "symbol": "BTCUSDC", "side": "LONG", "entry_price": 95000.0}

        with patch.dict("executor_mod.notifications.ENV", {"N8N_WEBHOOK_URL": "http://test.local/hook"}), \
             patch("executor_mod.notifications.requests.post", side_effect=requests.exceptions.Timeout("timeout")), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "SL_WATCHDOG", mode="live")

        self.assertNotIn("last_notified_close_trade_key", st, "Dedup key must NOT be set on webhook exception")

    def test_close_webhook_non_2xx_does_not_set_dedup(self):
        """Phase 2: Non-2xx HTTP response should NOT set dedup key"""
        import executor_mod.notifications as n

        st = {}
        pos = {"trade_key": "TK_500", "symbol": "BTCUSDC", "side": "SHORT"}

        mock_response = mock.Mock()
        mock_response.ok = False
        mock_response.status_code = 500

        with patch.dict("executor_mod.notifications.ENV", {"N8N_WEBHOOK_URL": "http://test.local/hook"}), \
             patch("executor_mod.notifications.requests.post", return_value=mock_response), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "TP2_DONE", mode="live")

        self.assertNotIn("last_notified_close_trade_key", st, "Dedup key must NOT be set on HTTP 500")

    def test_close_webhook_success_sets_dedup(self):
        """Phase 2: HTTP 2xx response SHOULD set dedup key"""
        import executor_mod.notifications as n

        st = {}
        pos = {"trade_key": "TK_SUCCESS", "symbol": "BTCUSDC", "side": "LONG"}

        mock_response = mock.Mock()
        mock_response.ok = True
        mock_response.status_code = 204

        with patch.dict("executor_mod.notifications.ENV", {"N8N_WEBHOOK_URL": "http://test.local/hook"}), \
             patch("executor_mod.notifications.requests.post", return_value=mock_response), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            n.send_trade_closed(st, pos, "MANUAL", mode="live")

        self.assertEqual(st.get("last_notified_close_trade_key"), "TK_SUCCESS", "Dedup key MUST be set on HTTP 2xx")

    def test_close_webhook_retries_next_call(self):
        """Phase 2: Failed webhook should be retried on next call"""
        import executor_mod.notifications as n
        import requests.exceptions

        st = {}
        pos = {"trade_key": "TK_RETRY", "symbol": "BTCUSDC", "side": "LONG"}

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.exceptions.Timeout("timeout on first attempt")
            mock_resp = mock.Mock()
            mock_resp.ok = True
            mock_resp.status_code = 200
            return mock_resp

        with patch.dict("executor_mod.notifications.ENV", {"N8N_WEBHOOK_URL": "http://test.local/hook"}), \
             patch("executor_mod.notifications.requests.post", side_effect=mock_post), \
             patch.object(n, "log_event", side_effect=lambda *a, **k: None):
            # First call - should fail
            n.send_trade_closed(st, pos, "MANUAL", mode="live")
            self.assertNotIn("last_notified_close_trade_key", st, "Dedup key should NOT be set after first failure")

            # Second call - should succeed
            n.send_trade_closed(st, pos, "MANUAL", mode="live")
            self.assertEqual(st.get("last_notified_close_trade_key"), "TK_RETRY", "Dedup key MUST be set after retry success")

        self.assertEqual(call_count[0], 2, "requests.post should be called exactly twice")
