import os
import json
import tempfile
import unittest
from unittest import mock
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
