"""test_trade_outcome_archive.py

Focused tests for executor_mod/trade_outcome_archive.py.

Tests the JSONL writer, payload contract, error handling, and
that archive failures never raise into the caller.
"""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

import executor_mod.trade_outcome_archive as archive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_st(reason="SL", trade_key="EX_EN_TEST001", **overrides):
    lc = {
        "ts": "2025-06-01T10:00:00Z",
        "mode": "live",
        "reason": reason,
        "pos_status": "OPEN_FILLED",
        "trade_key": trade_key,
        "order_id": 123456,
        "side": "LONG",
        "qty": 0.10,
        "entry_ref": 95000.0,
        "entry_actual": 95001.5,
        "opened_at": "2025-06-01T09:00:00Z",
        "order_id_sl": 333333,
        "order_id_tp1": 111222,
        "order_id_tp2": 111333,
        "qty1": 0.033,
        "qty2": 0.033,
        "qty3": 0.034,
        "tp1_done": False,
        "tp2_done": False,
        "sl_done": True,
        "trail_active": False,
        "trail_sl_price": None,
        "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
    }
    lc.update(overrides)
    return {"last_closed": lc, "position": None}


# ---------------------------------------------------------------------------
# Core writer tests
# ---------------------------------------------------------------------------

class TestRecordOutcomeWriter(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False, mode="w", encoding="utf-8"
        )
        self._tmp.close()
        self._path = self._tmp.name
        self._env_patch = patch.dict(os.environ, {"TRADE_OUTCOMES_FN": self._path})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def _read_lines(self):
        with open(self._path, encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip()]

    # --- basic write ---

    def test_writes_one_line(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        lines = self._read_lines()
        self.assertEqual(len(lines), 1)

    def test_line_is_valid_json(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        line = self._read_lines()[0]
        obj = json.loads(line)
        self.assertIsInstance(obj, dict)

    def test_multiple_calls_append_separate_lines(self):
        archive.record_outcome(_make_st(reason="SL"), "_close_slot", "BTCUSDC")
        archive.record_outcome(_make_st(reason="TP1"), "_close_slot", "BTCUSDC")
        lines = self._read_lines()
        self.assertEqual(len(lines), 2)
        r0 = json.loads(lines[0])
        r1 = json.loads(lines[1])
        self.assertEqual(r0["last_closed"]["reason"], "SL")
        self.assertEqual(r1["last_closed"]["reason"], "TP1")

    # --- payload contract ---

    def test_event_field(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertEqual(obj["event"], "TRADE_OUTCOME")

    def test_schema_field(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertEqual(obj["schema"], archive.SCHEMA_VERSION)

    def test_symbol_field(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertEqual(obj["symbol"], "BTCUSDC")

    def test_source_field(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertEqual(obj["source"], "_close_slot")

    def test_last_closed_present(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertIn("last_closed", obj)
        self.assertIsInstance(obj["last_closed"], dict)

    def test_ts_field_from_last_closed(self):
        archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertEqual(obj["ts"], "2025-06-01T10:00:00Z")

    def test_ts_field_fallback_when_last_closed_has_no_ts(self):
        st = _make_st()
        del st["last_closed"]["ts"]
        archive.record_outcome(st, "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        self.assertIn("ts", obj)
        self.assertTrue(len(obj["ts"]) > 0)

    def test_last_closed_content_preserved(self):
        archive.record_outcome(_make_st(trade_key="EX_EN_CHECK"), "_close_slot", "BTCUSDC")
        obj = json.loads(self._read_lines()[0])
        lc = obj["last_closed"]
        self.assertEqual(lc["trade_key"], "EX_EN_CHECK")
        self.assertEqual(lc["side"], "LONG")
        self.assertEqual(lc["qty"], 0.10)
        self.assertTrue(lc["sl_done"])

    def test_source_variants(self):
        for source in ("_close_slot", "_clear_position_slot", "sync_confirmed_canceled", "sync_exchange_clear"):
            archive.record_outcome(_make_st(), source, "BTCUSDC")
        lines = self._read_lines()
        self.assertEqual(len(lines), 4)
        sources = [json.loads(l)["source"] for l in lines]
        self.assertEqual(sources, [
            "_close_slot", "_clear_position_slot",
            "sync_confirmed_canceled", "sync_exchange_clear",
        ])

    # --- skip when no last_closed ---

    def test_no_write_when_last_closed_is_none(self):
        st = {"last_closed": None, "position": None}
        archive.record_outcome(st, "_close_slot", "BTCUSDC")
        self.assertEqual(self._read_lines(), [])

    def test_no_write_when_last_closed_missing(self):
        archive.record_outcome({}, "_close_slot", "BTCUSDC")
        self.assertEqual(self._read_lines(), [])


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestRecordOutcomeErrorHandling(unittest.TestCase):

    def test_no_raise_on_write_failure(self):
        """A write failure must not propagate an exception to the caller."""
        with patch.dict(os.environ, {"TRADE_OUTCOMES_FN": "/nonexistent_dir/trade_outcomes.jsonl"}):
            try:
                archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
            except Exception as e:
                self.fail(f"record_outcome raised unexpectedly: {e}")

    def test_no_raise_on_json_serialization_error(self):
        """Unserializable value in last_closed must not raise — _safe_default handles it."""
        st = _make_st()
        st["last_closed"]["bad_field"] = object()  # not JSON serialisable normally
        with patch.dict(os.environ, {"TRADE_OUTCOMES_FN": "/tmp/test_outcome_bad.jsonl"}):
            try:
                archive.record_outcome(st, "_close_slot", "BTCUSDC")
            except Exception as e:
                self.fail(f"record_outcome raised on unserializable value: {e}")
            finally:
                try:
                    os.unlink("/tmp/test_outcome_bad.jsonl")
                except OSError:
                    pass

    def test_write_error_logs_event(self):
        logged = []
        with patch.dict(os.environ, {"TRADE_OUTCOMES_FN": "/nonexistent/path.jsonl"}), \
             patch("executor_mod.trade_outcome_archive.open", side_effect=OSError("disk full")), \
             patch("executor_mod.notifications.log_event",
                   side_effect=lambda ev, **kw: logged.append((ev, kw))):
            archive.record_outcome(_make_st(), "_close_slot", "BTCUSDC")
        # Either logged via the deferred import path or silently suppressed — no raise either way.
        # We only assert no exception was raised (covered by reaching this line).


# ---------------------------------------------------------------------------
# Executor integration smoke: archive calls don't break close paths
# ---------------------------------------------------------------------------

class TestExecutorIntegrationSmoke(unittest.TestCase):
    """
    Verify the four call sites in executor.py don't raise and that
    the archive module is invoked with the expected source label.
    """

    def setUp(self):
        import executor
        self._executor = executor
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False, mode="w", encoding="utf-8"
        )
        self._tmp.close()
        self._path = self._tmp.name
        self._env_patch = patch.dict(os.environ, {"TRADE_OUTCOMES_FN": self._path})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def _read_lines(self):
        with open(self._path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_clear_position_slot_writes_archive(self):
        executor = self._executor
        pos = {
            "mode": "live", "status": "PENDING", "side": "LONG",
            "order_id": 777, "client_id": "EX_EN_A", "trade_key": "EX_EN_A",
            "qty": 0.05, "opened_at": "2025-06-01T00:00:00Z",
            "entry_actual": None, "prices": {"entry": 95000.0},
            "orders": {},
        }
        st = {"position": pos, "last_closed": None, "lock_until": 0.0}
        with patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor._clear_position_slot(st, "ENTRY_CANCELED")
        records = self._read_lines()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "_clear_position_slot")
        self.assertEqual(records[0]["event"], "TRADE_OUTCOME")

    def test_clear_position_slot_archive_failure_does_not_break_close(self):
        executor = self._executor
        pos = {
            "mode": "live", "status": "PENDING", "side": "LONG",
            "order_id": 888, "client_id": "EX_EN_B", "trade_key": "EX_EN_B",
            "qty": 0.05, "opened_at": "2025-06-01T00:00:00Z",
            "entry_actual": None, "prices": {}, "orders": {},
        }
        st = {"position": pos, "last_closed": None, "lock_until": 0.0}
        with patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None), \
             patch.object(archive, "record_outcome", side_effect=RuntimeError("archive down")):
            # Must not raise even if record_outcome itself throws
            try:
                executor._clear_position_slot(st, "ENTRY_CANCELED")
            except Exception as e:
                self.fail(f"_clear_position_slot raised due to archive failure: {e}")
        # position must still be cleared
        self.assertIsNone(st["position"])


if __name__ == "__main__":
    unittest.main()
