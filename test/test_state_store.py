import os
import json
import time
import tempfile
import unittest
from unittest import mock

import executor_mod.state_store as ss


class TestStateStore(unittest.TestCase):
    def test_load_state_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            fn = os.path.join(td, "state.json")
            with mock.patch.dict(os.environ, {"STATE_FN": fn}, clear=False):
                st = ss.load_state()

            self.assertIn("meta", st)
            self.assertIn("seen_keys", st["meta"])
            self.assertIn("position", st)
            self.assertIn("last_closed", st)
            self.assertIn("cooldown_until", st)
            self.assertIn("lock_until", st)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            fn = os.path.join(td, "state.json")
            with mock.patch.dict(os.environ, {"STATE_FN": fn}, clear=False):
                st = ss.load_state()
                st["position"] = {"status": "OPEN"}
                ss.save_state(st)

                self.assertTrue(os.path.exists(fn))
                st2 = ss.load_state()
                self.assertEqual(st2["position"]["status"], "OPEN")

                # file is valid json
                with open(fn, "r", encoding="utf-8") as f:
                    json.load(f)

    def test_has_open_position(self):
        self.assertFalse(ss.has_open_position({"position": None}))
        self.assertTrue(ss.has_open_position({"position": {"status": "PENDING"}}))
        self.assertTrue(ss.has_open_position({"position": {"status": "OPEN"}}))
        self.assertTrue(ss.has_open_position({"position": {"status": "OPEN_FILLED"}}))
        self.assertFalse(ss.has_open_position({"position": {"status": "CLOSED"}}))

    def test_in_cooldown_and_locked(self):
        now = 1_000_000.0
        with mock.patch.object(time, "time", return_value=now):
            self.assertTrue(ss.in_cooldown({"cooldown_until": now + 10}))
            self.assertFalse(ss.in_cooldown({"cooldown_until": now - 10}))
            self.assertTrue(ss.locked({"lock_until": now + 10}))
            self.assertFalse(ss.locked({"lock_until": now - 10}))
