"""test_close_snapshot.py
Focused tests for close-snapshot enrichment in executor.py.

Tests _clear_position_slot and manage_v15_position._close_slot (via SL-fill path).
No trading logic tested here — only that last_closed carries the whitelist fields.
"""
import unittest
from copy import deepcopy
from unittest.mock import patch, MagicMock

import executor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_full_pos(**overrides):
    """Return a realistic OPEN_FILLED position dict."""
    pos = {
        "mode": "live",
        "status": "OPEN_FILLED",
        "side": "LONG",
        "opened_at": "2025-01-01T00:00:00Z",
        "qty": 0.12,
        "entry": 95000.0,
        "entry_actual": 95001.5,
        "order_id": 111111,
        "client_id": "EX_EN_1000",
        "trade_key": "EX_EN_1000",
        "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
        "orders": {
            "sl": 333333,
            "tp1": 111222,
            "tp2": 111333,
            "qty1": 0.04,
            "qty2": 0.04,
            "qty3": 0.04,
        },
        "tp1_done": False,
        "tp2_done": False,
        "sl_done": False,
        "trail_active": False,
        "trail_sl_price": None,
    }
    pos.update(overrides)
    return pos


WHITELIST_KEYS = [
    "opened_at", "trade_key", "order_id", "qty",
    "entry_ref", "entry_actual",
    "order_id_sl", "order_id_tp1", "order_id_tp2",
    "qty1", "qty2", "qty3",
    "tp1_done", "tp2_done", "sl_done",
    "trail_active", "trail_sl_price",
    "prices",
]

LEGACY_KEYS = ["ts", "mode", "reason", "pos_status"]  # _clear_position_slot
LEGACY_CLOSE_KEYS = ["ts", "mode", "reason", "side", "entry"]  # _close_slot


# ---------------------------------------------------------------------------
# _clear_position_slot
# ---------------------------------------------------------------------------

class TestClearPositionSlotSnapshot(unittest.TestCase):

    def _call(self, pos, reason="TEST", **extra_fields):
        st = {"position": pos}
        with patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor._clear_position_slot(st, reason, **extra_fields)
        return st

    # --- whitelist fields present ---

    def test_whitelist_keys_present(self):
        pos = _make_full_pos()
        st = self._call(pos)
        lc = st["last_closed"]
        for key in WHITELIST_KEYS:
            self.assertIn(key, lc, f"Missing whitelist key: {key}")

    def test_legacy_keys_still_present(self):
        pos = _make_full_pos()
        st = self._call(pos)
        lc = st["last_closed"]
        for key in LEGACY_KEYS:
            self.assertIn(key, lc, f"Missing legacy key: {key}")

    # --- values are correct ---

    def test_entry_actual_preserved_as_is(self):
        pos = _make_full_pos(entry_actual=95001.5)
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["entry_actual"], 95001.5)

    def test_entry_actual_none_preserved(self):
        """Must not invent a fallback — None stays None."""
        pos = _make_full_pos(entry_actual=None)
        lc = self._call(pos)["last_closed"]
        self.assertIsNone(lc["entry_actual"])

    def test_order_ids_from_orders_dict(self):
        pos = _make_full_pos()
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["order_id_sl"], 333333)
        self.assertEqual(lc["order_id_tp1"], 111222)
        self.assertEqual(lc["order_id_tp2"], 111333)

    def test_qty_split_from_orders_dict(self):
        pos = _make_full_pos()
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["qty1"], 0.04)
        self.assertEqual(lc["qty2"], 0.04)
        self.assertEqual(lc["qty3"], 0.04)

    def test_done_flags_as_bool(self):
        pos = _make_full_pos(tp1_done=True, tp2_done=False, sl_done=True)
        lc = self._call(pos)["last_closed"]
        self.assertIs(lc["tp1_done"], True)
        self.assertIs(lc["tp2_done"], False)
        self.assertIs(lc["sl_done"], True)

    def test_trail_fields(self):
        pos = _make_full_pos(trail_active=True, trail_sl_price=94500.0)
        lc = self._call(pos)["last_closed"]
        self.assertIs(lc["trail_active"], True)
        self.assertEqual(lc["trail_sl_price"], 94500.0)

    def test_prices_dict_preserved(self):
        pos = _make_full_pos()
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["prices"], {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0})

    def test_trade_key_preferred_over_client_id(self):
        pos = _make_full_pos(trade_key="TK_explicit", client_id="CL_fallback")
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["trade_key"], "TK_explicit")

    def test_trade_key_falls_back_to_client_id(self):
        pos = _make_full_pos()
        pos.pop("trade_key", None)
        pos["client_id"] = "CL_only"
        lc = self._call(pos)["last_closed"]
        self.assertEqual(lc["trade_key"], "CL_only")

    def test_caller_fields_still_override(self):
        """**fields from caller must still win over whitelist values."""
        pos = _make_full_pos(order_id=111111)
        st = self._call(pos, reason="ENTRY_TIMEOUT", order_id=999999)
        lc = st["last_closed"]
        self.assertEqual(lc["order_id"], 999999)  # caller-supplied wins
        self.assertEqual(lc["reason"], "ENTRY_TIMEOUT")

    # --- pos=None edge case (called with empty state) ---

    def test_pos_none_produces_none_whitelist_values(self):
        st = {"position": None}
        with patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor._clear_position_slot(st, "EMPTY")
        lc = st["last_closed"]
        self.assertIn("ts", lc)
        self.assertIsNone(lc["trade_key"])
        self.assertIsNone(lc["entry_actual"])
        self.assertIsNone(lc["order_id_sl"])
        self.assertIs(lc["tp1_done"], False)
        self.assertIs(lc["trail_active"], False)

    # --- position cleared ---

    def test_position_is_none_after_call(self):
        pos = _make_full_pos()
        st = self._call(pos)
        self.assertIsNone(st["position"])


# ---------------------------------------------------------------------------
# manage_v15_position -> _close_slot (via SL FILLED path)
# ---------------------------------------------------------------------------

class TestCloseSlotSnapshot(unittest.TestCase):

    def _sl_filled_st(self, **pos_overrides):
        pos = _make_full_pos(**pos_overrides)
        return {"position": pos, "cooldown_until": 0.0, "lock_until": 0.0}

    def _run_manage(self, st):
        def fake_status(_sym, oid):
            oid = int(oid)
            if oid == 333333:
                return {"status": "FILLED"}
            return {"status": "NEW"}

        with patch.object(executor.binance_api, "open_orders", return_value=[]), \
             patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
             patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}), \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda *_: None), \
             patch.object(executor, "log_event", lambda *_, **__: None), \
             patch.object(executor, "_now_s", return_value=9000.0), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

    # --- whitelist keys present ---

    def test_whitelist_keys_present_after_sl(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        self.assertIsNone(st["position"])
        lc = st["last_closed"]
        for key in WHITELIST_KEYS:
            self.assertIn(key, lc, f"Missing whitelist key after SL close: {key}")

    def test_legacy_keys_still_present_after_sl(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        lc = st["last_closed"]
        for key in LEGACY_CLOSE_KEYS:
            self.assertIn(key, lc, f"Missing legacy key after SL close: {key}")

    # --- values ---

    def test_entry_actual_preserved(self):
        st = self._sl_filled_st(entry_actual=95050.0)
        self._run_manage(st)
        self.assertEqual(st["last_closed"]["entry_actual"], 95050.0)

    def test_entry_actual_none_not_fabricated(self):
        st = self._sl_filled_st(entry_actual=None)
        self._run_manage(st)
        self.assertIsNone(st["last_closed"]["entry_actual"])

    def test_order_id_sl_tp1_tp2(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        lc = st["last_closed"]
        self.assertEqual(lc["order_id_sl"], 333333)
        self.assertEqual(lc["order_id_tp1"], 111222)
        self.assertEqual(lc["order_id_tp2"], 111333)

    def test_qty_split(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        lc = st["last_closed"]
        self.assertEqual(lc["qty1"], 0.04)
        self.assertEqual(lc["qty2"], 0.04)
        self.assertEqual(lc["qty3"], 0.04)

    def test_done_flags_at_sl_close(self):
        """tp1_done and tp2_done reflect position state; sl_done=True at SL close."""
        st = self._sl_filled_st(tp1_done=True, tp2_done=False)
        self._run_manage(st)
        lc = st["last_closed"]
        self.assertIs(lc["tp1_done"], True)
        self.assertIs(lc["tp2_done"], False)
        self.assertIs(lc["sl_done"], True)

    def test_execution_snapshot_recorded_before_position_clear(self):
        st = self._sl_filled_st()
        calls = []

        def fake_status(_sym, oid):
            oid = int(oid)
            if oid == 333333:
                return {"status": "FILLED"}
            return {"status": "NEW"}

        def fake_record(st_arg, source, binance_api=None):
            calls.append({
                "source": source,
                "position_present": st_arg.get("position") is not None,
                "has_last_closed": bool(st_arg.get("last_closed")),
                "binance_api_passed": binance_api is executor.binance_api,
            })

        with patch.object(executor.binance_api, "open_orders", return_value=[]), \
             patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
             patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}), \
             patch.object(executor.trade_execution_snapshot, "record_final_execution_snapshot", side_effect=fake_record), \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda *_: None), \
             patch.object(executor, "log_event", lambda *_, **__: None), \
             patch.object(executor, "_now_s", return_value=9000.0), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["source"], "_close_slot")
        self.assertTrue(calls[0]["has_last_closed"])
        self.assertTrue(calls[0]["position_present"])
        self.assertTrue(calls[0]["binance_api_passed"])

    def test_trade_closed_summary_payload_emitted_after_snapshot(self):
        st = self._sl_filled_st(tp1_done=True, tp2_done=True, trail_active=True)
        sent = []
        snapshot = {
            "trade_key": "EX_EN_1000",
            "symbol": "BTCUSDC",
            "snapshot_status": "complete",
            "lifecycle_class": "tp1_tp2_trailing_stop",
            "local_last_closed": {"side": "LONG", "reason": "SL", "trade_key": "EX_EN_1000"},
            "fill_summaries": {
                "entry": {"avg_price": "100", "total_qty": "1", "total_quote_qty": "100"},
                "tp1": {"avg_price": "110", "total_qty": "0.4", "total_quote_qty": "44"},
                "tp2": {"avg_price": "120", "total_qty": "0.3", "total_quote_qty": "36"},
                "final_sl": {"avg_price": "90", "total_qty": "0.3", "total_quote_qty": "27"},
            },
            "fees": {"commission_by_asset": {"USDC": "0.20"}},
            "orders": {"tp1": {"order_id": 1}, "tp2": {"order_id": 2}, "final_sl": {"order_id": 3}},
        }

        def fake_status(_sym, oid):
            return {"status": "FILLED"} if int(oid) == 333333 else {"status": "NEW"}

        with patch.object(executor.binance_api, "open_orders", return_value=[]), \
             patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
             patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}), \
             patch.object(executor.trade_execution_snapshot, "record_final_execution_snapshot", return_value=snapshot), \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda payload: sent.append(payload)), \
             patch.object(executor, "log_event", lambda *_, **__: None), \
             patch.object(executor, "_now_s", return_value=9000.0), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        payloads = [p for p in sent if p.get("event") == "TRADE_CLOSED_SUMMARY"]
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["type"], "TRADE_CLOSED_SUMMARY")
        self.assertEqual(payload["message"], payload["text"])
        self.assertEqual(payload["telegram_text"], payload["text"])
        self.assertTrue(payload["text"].strip())
        self.assertIn("Trade closed", payload["text"])
        self.assertIn("Gross PnL", payload["text"])

    def test_trade_closed_summary_failure_does_not_block_cleanup(self):
        st = self._sl_filled_st()
        saved = []
        outcomes = []
        margin_calls = []

        def fake_status(_sym, oid):
            return {"status": "FILLED"} if int(oid) == 333333 else {"status": "NEW"}

        def boom(payload):
            if payload.get("event") == "TRADE_CLOSED_SUMMARY":
                raise RuntimeError("webhook down")

        with patch.object(executor.binance_api, "open_orders", return_value=[]), \
             patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
             patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}), \
             patch.object(executor.trade_execution_snapshot, "record_final_execution_snapshot", return_value=None), \
             patch.object(executor.trade_outcome_archive, "record_outcome", lambda *a, **k: outcomes.append(True)), \
             patch.object(executor, "save_state", lambda *_: saved.append(deepcopy(st))), \
             patch.object(executor, "send_webhook", boom), \
             patch.object(executor, "log_event", lambda *_, **__: None), \
             patch.object(executor, "_now_s", return_value=9000.0), \
             patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: margin_calls.append(True)):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNone(st["position"])
        self.assertTrue(saved)
        self.assertTrue(outcomes)
        self.assertTrue(margin_calls)

    def test_trail_fields_at_sl_close(self):
        st = self._sl_filled_st(trail_active=True, trail_sl_price=93800.0)
        self._run_manage(st)
        lc = st["last_closed"]
        self.assertIs(lc["trail_active"], True)
        self.assertEqual(lc["trail_sl_price"], 93800.0)

    def test_prices_dict(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        self.assertEqual(
            st["last_closed"]["prices"],
            {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
        )

    def test_reason_is_sl(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        self.assertEqual(st["last_closed"]["reason"], "SL")

    def test_position_cleared(self):
        st = self._sl_filled_st()
        self._run_manage(st)
        self.assertIsNone(st["position"])


# ---------------------------------------------------------------------------
# sync_from_binance -> P4 confirmed-canceled clear
# ---------------------------------------------------------------------------

class TestSyncFromBinanceP4ConfirmedCanceled(unittest.TestCase):
    """
    Verify P4 fix: when sync_from_binance() clears a PENDING position because
    the entry order is exchange-confirmed CANCELED (executedQty==0), it must:
      - write a fresh st["last_closed"] reflecting the current position
      - call on_after_position_closed with trade_key from the current pos
      - NOT leave last_closed pointing at a previous (stale) position
    """

    _STALE_TRADE_KEY = "EX_STALE_PREVIOUS"
    _CURRENT_TRADE_KEY = "EX_EN_P4CURRENT"

    def _make_st(self, **pos_overrides):
        """State with a PENDING live position and a stale last_closed from a prior trade."""
        pos = {
            "mode": "live",
            "status": "PENDING",
            "side": "LONG",
            "order_id": 888001,
            "client_id": self._CURRENT_TRADE_KEY,
            "trade_key": self._CURRENT_TRADE_KEY,
            "qty": 0.10,
            "opened_at": "2025-06-01T10:00:00Z",
            "entry_actual": None,
            "prices": {"entry": 95000.0},
        }
        pos.update(pos_overrides)
        stale_last_closed = {
            "ts": "2025-05-01T00:00:00Z",
            "mode": "live",
            "reason": "SL",
            "trade_key": self._STALE_TRADE_KEY,
            "order_id": 777999,
        }
        return {"position": pos, "last_closed": stale_last_closed, "lock_until": 0.0}

    def _run(self, st, od_return=None):
        """Run sync_from_binance with margin mode and I13 forced-clear disabled."""
        if od_return is None:
            od_return = {"status": "CANCELED", "executedQty": "0"}
        hook_calls = []

        saved_mode = executor.ENV.get("TRADE_MODE")
        saved_i13 = executor.ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = False
            with patch.object(executor.binance_api, "open_orders", return_value=[]), \
                 patch.object(executor.binance_api, "check_order_status", return_value=od_return), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_, **__: None), \
                 patch.object(executor.margin_guard, "on_after_position_closed",
                               lambda *a, **k: hook_calls.append(k)):
                executor.sync_from_binance(st)
        finally:
            if saved_mode is None:
                executor.ENV.pop("TRADE_MODE", None)
            else:
                executor.ENV["TRADE_MODE"] = saved_mode
            if saved_i13 is None:
                executor.ENV.pop("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", None)
            else:
                executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = saved_i13

        return hook_calls

    # --- position is cleared ---

    def test_position_is_none_after_confirmed_canceled(self):
        st = self._make_st()
        self._run(st)
        self.assertIsNone(st["position"])

    # --- fresh last_closed is written ---

    def test_fresh_last_closed_written(self):
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertIsNotNone(lc)
        self.assertEqual(lc["reason"], "SYNC_CONFIRMED_CANCELED")

    def test_last_closed_is_not_stale(self):
        """last_closed must NOT still point at the previous trade after P4 clear."""
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertNotEqual(lc.get("trade_key"), self._STALE_TRADE_KEY)

    def test_last_closed_trade_key_from_current_pos(self):
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertEqual(lc["trade_key"], self._CURRENT_TRADE_KEY)

    def test_last_closed_trade_key_falls_back_to_client_id(self):
        """When trade_key absent on pos, falls back to client_id — not stale last_closed."""
        st = self._make_st()
        del st["position"]["trade_key"]
        self._run(st)
        lc = st["last_closed"]
        self.assertEqual(lc["trade_key"], self._CURRENT_TRADE_KEY)  # client_id == CURRENT
        self.assertNotEqual(lc["trade_key"], self._STALE_TRADE_KEY)

    def test_last_closed_fields_reflect_current_pos(self):
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertEqual(lc["order_id"], 888001)
        self.assertEqual(lc["side"], "LONG")
        self.assertEqual(lc["qty"], 0.10)
        self.assertEqual(lc["opened_at"], "2025-06-01T10:00:00Z")

    def test_last_closed_order_status_is_exchange_status(self):
        st = self._make_st()
        self._run(st, od_return={"status": "CANCELED", "executedQty": "0"})
        self.assertEqual(st["last_closed"]["order_status"], "CANCELED")

    def test_last_closed_order_status_rejected(self):
        st = self._make_st()
        self._run(st, od_return={"status": "REJECTED", "executedQty": "0"})
        self.assertEqual(st["last_closed"]["order_status"], "REJECTED")

    def test_last_closed_entry_ref_from_prices(self):
        st = self._make_st()
        self._run(st)
        self.assertEqual(st["last_closed"]["entry_ref"], 95000.0)

    def test_last_closed_entry_actual_none_not_fabricated(self):
        st = self._make_st(entry_actual=None)
        self._run(st)
        self.assertIsNone(st["last_closed"]["entry_actual"])

    # --- margin hook is called ---

    def test_on_after_position_closed_called(self):
        st = self._make_st()
        calls = self._run(st)
        self.assertEqual(len(calls), 1, "on_after_position_closed must be called exactly once")

    def test_on_after_position_closed_trade_key_is_current(self):
        st = self._make_st()
        calls = self._run(st)
        self.assertEqual(calls[0].get("trade_key"), self._CURRENT_TRADE_KEY)

    def test_on_after_position_closed_trade_key_not_stale(self):
        st = self._make_st()
        calls = self._run(st)
        self.assertNotEqual(calls[0].get("trade_key"), self._STALE_TRADE_KEY)

    def test_hook_trade_key_from_active_margin_state_when_pos_has_none(self):
        """If pos has no trade_key/client_id, fall back to margin.active_trade_key."""
        st = self._make_st()
        st["position"].pop("trade_key", None)
        st["position"].pop("client_id", None)
        st["margin"] = {"active_trade_key": "MG_ACTIVE_KEY"}
        calls = self._run(st)
        self.assertEqual(calls[0].get("trade_key"), "MG_ACTIVE_KEY")

    # --- no-op when not applicable ---

    def test_no_clear_when_order_not_canceled(self):
        """If entry order is still NEW, slot must NOT be cleared."""
        st = self._make_st()
        original_lc = deepcopy(st["last_closed"])
        self._run(st, od_return={"status": "NEW", "executedQty": "0"})
        self.assertIsNotNone(st["position"], "Position must NOT be cleared when order is still NEW")
        self.assertEqual(st["last_closed"], original_lc, "last_closed must not change when no clear happens")

    def test_no_clear_when_partially_filled(self):
        """If executedQty > 0, must NOT clear even if status is CANCELED."""
        st = self._make_st()
        original_lc = deepcopy(st["last_closed"])
        self._run(st, od_return={"status": "CANCELED", "executedQty": "0.05"})
        self.assertIsNotNone(st["position"])
        self.assertEqual(st["last_closed"], original_lc)


# ---------------------------------------------------------------------------
# sync_from_binance -> P5 exchange-truth forced clear (snapshot fix only)
# ---------------------------------------------------------------------------

class TestSyncFromBinanceP5ExchangeClearSnapshot(unittest.TestCase):
    """
    Verify P5 snapshot fix: when sync_from_binance() clears a position via
    I13_CLEAR_STATE_ON_EXCHANGE_CLEAR, it must write a fresh st["last_closed"]
    from the current pos before clearing. The tk resolution and margin hook
    ordering are NOT under test here — only the snapshot gap.
    """

    _STALE_TRADE_KEY = "EX_STALE_PREV"
    _CURRENT_TRADE_KEY = "EX_EN_P5CURRENT"

    def _make_st(self, status="OPEN_FILLED", **pos_overrides):
        pos = {
            "mode": "live",
            "status": status,
            "side": "LONG",
            "order_id": 666001,
            "client_id": self._CURRENT_TRADE_KEY,
            "trade_key": self._CURRENT_TRADE_KEY,
            "qty": 0.08,
            "opened_at": "2025-06-01T12:00:00Z",
            "entry_actual": 95100.0,
            "prices": {"entry": 95000.0},
        }
        pos.update(pos_overrides)
        stale = {
            "ts": "2025-05-01T00:00:00Z",
            "mode": "live",
            "reason": "SL",
            "trade_key": self._STALE_TRADE_KEY,
        }
        return {"position": pos, "last_closed": stale, "lock_until": 0.0}

    def _run(self, st):
        saved_mode = executor.ENV.get("TRADE_MODE")
        saved_i13 = executor.ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = True
            with patch.object(executor.binance_api, "open_orders", return_value=[]), \
                 patch.object(executor, "_exchange_position_exists", return_value=False), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_, **__: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
                executor.sync_from_binance(st)
        finally:
            if saved_mode is None:
                executor.ENV.pop("TRADE_MODE", None)
            else:
                executor.ENV["TRADE_MODE"] = saved_mode
            if saved_i13 is None:
                executor.ENV.pop("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", None)
            else:
                executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = saved_i13

    # --- position is cleared ---

    def test_position_is_none_after_exchange_clear(self):
        st = self._make_st()
        self._run(st)
        self.assertIsNone(st["position"])

    # --- fresh last_closed is written ---

    def test_fresh_last_closed_written(self):
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertIsNotNone(lc)
        self.assertEqual(lc["reason"], "SYNC_EXCHANGE_CLEAR")

    def test_last_closed_is_not_stale(self):
        """last_closed must NOT still point at the previous trade after P5 clear."""
        st = self._make_st()
        self._run(st)
        self.assertNotEqual(st["last_closed"].get("trade_key"), self._STALE_TRADE_KEY)

    def test_last_closed_trade_key_from_current_pos(self):
        st = self._make_st()
        self._run(st)
        self.assertEqual(st["last_closed"]["trade_key"], self._CURRENT_TRADE_KEY)

    def test_last_closed_trade_key_falls_back_to_client_id(self):
        st = self._make_st()
        del st["position"]["trade_key"]
        self._run(st)
        lc = st["last_closed"]
        self.assertEqual(lc["trade_key"], self._CURRENT_TRADE_KEY)  # client_id == CURRENT
        self.assertNotEqual(lc["trade_key"], self._STALE_TRADE_KEY)

    def test_last_closed_fields_reflect_current_pos(self):
        st = self._make_st()
        self._run(st)
        lc = st["last_closed"]
        self.assertEqual(lc["order_id"], 666001)
        self.assertEqual(lc["side"], "LONG")
        self.assertEqual(lc["qty"], 0.08)
        self.assertEqual(lc["opened_at"], "2025-06-01T12:00:00Z")
        self.assertEqual(lc["entry_actual"], 95100.0)
        self.assertEqual(lc["entry_ref"], 95000.0)

    def test_last_closed_pos_status_preserved(self):
        st = self._make_st(status="OPEN_FILLED")
        self._run(st)
        self.assertEqual(st["last_closed"]["pos_status"], "OPEN_FILLED")

    def test_last_closed_entry_actual_none_not_fabricated(self):
        st = self._make_st(entry_actual=None)
        self._run(st)
        self.assertIsNone(st["last_closed"]["entry_actual"])

    # --- works for all three eligible statuses ---

    def test_open_filled_status(self):
        st = self._make_st(status="OPEN_FILLED")
        self._run(st)
        self.assertIsNone(st["position"])
        self.assertEqual(st["last_closed"]["reason"], "SYNC_EXCHANGE_CLEAR")

    def test_open_status(self):
        st = self._make_st(status="OPEN")
        self._run(st)
        self.assertIsNone(st["position"])
        self.assertEqual(st["last_closed"]["reason"], "SYNC_EXCHANGE_CLEAR")

    def test_pending_status(self):
        st = self._make_st(status="PENDING")
        self._run(st)
        self.assertIsNone(st["position"])
        self.assertEqual(st["last_closed"]["reason"], "SYNC_EXCHANGE_CLEAR")

    # --- no clear when I13_CLEAR_STATE_ON_EXCHANGE_CLEAR is disabled ---

    def test_no_clear_when_feature_flag_off(self):
        st = self._make_st()
        stale_snapshot = deepcopy(st["last_closed"])
        saved_mode = executor.ENV.get("TRADE_MODE")
        saved_i13 = executor.ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = False
            with patch.object(executor.binance_api, "open_orders", return_value=[]), \
                 patch.object(executor, "_exchange_position_exists", return_value=False), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_, **__: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor.margin_guard, "on_after_position_closed", lambda *a, **k: None):
                executor.sync_from_binance(st)
        finally:
            if saved_mode is None:
                executor.ENV.pop("TRADE_MODE", None)
            else:
                executor.ENV["TRADE_MODE"] = saved_mode
            if saved_i13 is None:
                executor.ENV.pop("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", None)
            else:
                executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = saved_i13
        self.assertIsNotNone(st["position"], "Position must NOT be cleared when flag is off")
        self.assertEqual(st["last_closed"], stale_snapshot, "last_closed must not change when flag is off")


# ---------------------------------------------------------------------------
# P5 stale-fallback removal: tk must never read from last_closed.trade_key
# ---------------------------------------------------------------------------

class TestSyncFromBinanceP5FallbackRemoval(unittest.TestCase):
    """
    Verify that after the stale-fallback removal, the P5 hook receives a tk
    derived only from pos.trade_key or margin.active_trade_key — never from
    the old last_closed.trade_key.

    The dedup-poisoning scenario: a stale trade_key from the previous trade
    appearing in repay_done would have silently blocked repay for the current
    trade. Removing the fallback eliminates that risk.
    """

    _STALE_TRADE_KEY = "EX_STALE_OLD_TRADE"
    _CURRENT_TRADE_KEY = "EX_EN_CURRENT"
    _ACTIVE_MARGIN_KEY = "MG_ACTIVE_CURRENT"

    def _make_st(self, pos_trade_key=_CURRENT_TRADE_KEY, active_trade_key=None):
        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "order_id": 555001,
            "client_id": self._CURRENT_TRADE_KEY,
            "trade_key": pos_trade_key,
            "qty": 0.05,
            "opened_at": "2025-06-01T14:00:00Z",
            "entry_actual": 95200.0,
            "prices": {"entry": 95000.0},
        }
        if pos_trade_key is None:
            pos.pop("trade_key")
        margin = {
            "borrowed_assets": {"BTC": 0.05},
            "borrowed_by_trade": {},
            "borrowed_trade_keys": [],
            "repaid_trade_keys": [],
            "active_trade_key": active_trade_key,
        }
        stale_lc = {
            "ts": "2025-05-01T00:00:00Z",
            "mode": "live",
            "reason": "SL",
            "trade_key": self._STALE_TRADE_KEY,
        }
        return {"position": pos, "last_closed": stale_lc, "lock_until": 0.0, "margin": margin}

    def _run_capture_hook_tk(self, st):
        """Run P5 path and capture the trade_key passed to on_after_position_closed."""
        captured = []
        saved_mode = executor.ENV.get("TRADE_MODE")
        saved_i13 = executor.ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = True
            with patch.object(executor.binance_api, "open_orders", return_value=[]), \
                 patch.object(executor, "_exchange_position_exists", return_value=False), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_, **__: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor.margin_guard, "on_after_position_closed",
                               lambda *a, **k: captured.append(k)):
                executor.sync_from_binance(st)
        finally:
            if saved_mode is None:
                executor.ENV.pop("TRADE_MODE", None)
            else:
                executor.ENV["TRADE_MODE"] = saved_mode
            if saved_i13 is None:
                executor.ENV.pop("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", None)
            else:
                executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = saved_i13
        return captured

    def test_hook_receives_pos_trade_key_not_stale(self):
        """Normal case: pos.trade_key is set — hook gets current key, not stale."""
        st = self._make_st(pos_trade_key=self._CURRENT_TRADE_KEY)
        captured = self._run_capture_hook_tk(st)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("trade_key"), self._CURRENT_TRADE_KEY)
        self.assertNotEqual(captured[0].get("trade_key"), self._STALE_TRADE_KEY)

    def test_hook_receives_active_margin_key_when_pos_trade_key_absent(self):
        """Fallback to margin.active_trade_key when pos has no trade_key."""
        st = self._make_st(pos_trade_key=None, active_trade_key=self._ACTIVE_MARGIN_KEY)
        captured = self._run_capture_hook_tk(st)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("trade_key"), self._ACTIVE_MARGIN_KEY)
        self.assertNotEqual(captured[0].get("trade_key"), self._STALE_TRADE_KEY)

    def test_hook_never_receives_stale_last_closed_trade_key(self):
        """
        Core invariant: even when both pos.trade_key and active_trade_key are
        absent, the stale last_closed.trade_key must NOT appear as the hook arg.
        """
        st = self._make_st(pos_trade_key=None, active_trade_key=None)
        captured = self._run_capture_hook_tk(st)
        self.assertEqual(len(captured), 1)
        self.assertNotEqual(
            captured[0].get("trade_key"),
            self._STALE_TRADE_KEY,
            "stale last_closed.trade_key must not be fed to on_after_position_closed",
        )


if __name__ == "__main__":
    unittest.main()
