import json
import unittest

import executor_mod.event_dedup as ed


class TestEventDedup(unittest.TestCase):
    def setUp(self):
        # minimal injection, без файлових побічних ефектів
        self.saved = []
        self.logged = []

        def _save_state(st):
            self.saved.append(st)

        def _log_event(action, **fields):
            self.logged.append((action, fields))

        env = {
            "STRICT_SOURCE": True,
            "DEDUP_PRICE_DECIMALS": 2,
            "SEEN_KEYS_MAX": 500,
        }
        ed.configure(env, iso_utc=lambda: "2025-01-01T00:00:00+00:00", save_state=_save_state, log_event=_log_event)

    def test_stable_event_key_rejects_non_peak(self):
        evt = {"action": "NOPE", "source": "DeltaScout", "kind": "long", "ts": "2025-01-01T00:00:00Z", "price": 100}
        self.assertIsNone(ed.stable_event_key(evt))

    def test_stable_event_key_rejects_wrong_source_when_strict(self):
        evt = {"action": "PEAK", "source": "Other", "kind": "long", "ts": "2025-01-01T00:00:00Z", "price": 100}
        self.assertIsNone(ed.stable_event_key(evt))

    def test_stable_event_key_ok(self):
        evt = {"action": "PEAK", "source": "DeltaScout", "kind": "long", "ts": "2025-01-01T12:34:56Z", "price": 100.1234}
        k = ed.stable_event_key(evt)
        self.assertIsInstance(k, str)
        self.assertIn("PEAK|", k)

    def test_bootstrap_seen_keys_adds_unique(self):
        st = {"meta": {"seen_keys": []}}

        e1 = {"action": "PEAK", "source": "DeltaScout", "kind": "long", "ts": "2025-01-01T12:34:56Z", "price": 100.0}
        e2 = {"action": "PEAK", "source": "DeltaScout", "kind": "short", "ts": "2025-01-01T12:35:10Z", "price": 101.0}

        tail = [json.dumps(e1), json.dumps(e2), json.dumps(e1)]
        ed.bootstrap_seen_keys_from_tail(st, tail)

        self.assertIn("meta", st)
        self.assertIn("seen_keys", st["meta"])
        self.assertEqual(len(st["meta"]["seen_keys"]), 2)  # дубль не додається
        self.assertTrue(len(self.saved) >= 1)
        self.assertTrue(any(a == "BOOTSTRAP_SEEN_KEYS" for a, _ in self.logged))
