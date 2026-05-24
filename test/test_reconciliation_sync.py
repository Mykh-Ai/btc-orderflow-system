import unittest
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

import executor


_UNSET = object()


class EnvRestoreMixin:
    def setUp(self):
        self._env = deepcopy(executor.ENV)

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self._env)

    def _margin_mode(self):
        executor.ENV.update(
            {
                "TRADE_MODE": "margin",
                "SYMBOL": "BTCUSDC",
                "MIN_QTY": 0.001,
                "MARGIN_DEBT_EPS": 0.01,
                "RECON_THROTTLE_SEC": 600,
                "INVAR_THROTTLE_SEC": 600,
            }
        )


class TestExchangePositionExists(EnvRestoreMixin, unittest.TestCase):
    def test_margin_payload_detects_base_asset_above_min_qty(self):
        self._margin_mode()
        payload = {
            "userAssets": [
                {"asset": "BTC", "free": "0.0011", "locked": "0", "borrowed": "0", "interest": "0", "netAsset": "0"}
            ]
        }
        with patch.object(executor.binance_api, "margin_account", return_value=payload, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), True)

    def test_margin_payload_zero_or_below_threshold_returns_false(self):
        self._margin_mode()
        payload = {
            "userAssets": [
                {"asset": "BTC", "free": "0.001", "locked": "0", "borrowed": "0.01", "interest": "0", "netAsset": "0"}
            ]
        }
        with patch.object(executor.binance_api, "margin_account", return_value=payload, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), False)

    def test_spot_payload_detects_base_asset_above_min_qty(self):
        executor.ENV.update({"TRADE_MODE": "spot", "SYMBOL": "BTCUSDC", "MIN_QTY": 0.001})
        payload = {"balances": [{"asset": "BTC", "free": "0.0012", "locked": "0"}]}
        with patch.object(executor.binance_api, "account", return_value=payload, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), True)

    def test_spot_payload_zero_or_below_threshold_returns_false(self):
        executor.ENV.update({"TRADE_MODE": "spot", "SYMBOL": "BTCUSDC", "MIN_QTY": 0.001})
        payload = {"balances": [{"asset": "BTC", "free": "0.001", "locked": "0"}]}
        with patch.object(executor.binance_api, "account", return_value=payload, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), False)

    def test_malformed_payload_returns_none_without_raise(self):
        self._margin_mode()
        with patch.object(executor.binance_api, "margin_account", return_value={"userAssets": "bad"}, create=True):
            self.assertIsNone(executor._exchange_position_exists("BTCUSDC"))

    def test_missing_api_methods_return_none_without_raise(self):
        self._margin_mode()
        names = ("margin_account", "get_margin_account", "get_margin_account_info", "get_margin_account_details")
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(executor.binance_api, name, None, create=True))
            self.assertIsNone(executor._exchange_position_exists("BTCUSDC"))

    def test_min_qty_and_margin_debt_eps_thresholds(self):
        self._margin_mode()
        equal_threshold = {
            "userAssets": [
                {"asset": "BTC", "free": "0.001", "locked": "0", "borrowed": "0.01", "interest": "0", "netAsset": "0"}
            ]
        }
        above_debt = {
            "userAssets": [
                {"asset": "BTC", "free": "0", "locked": "0", "borrowed": "0.010001", "interest": "0", "netAsset": "0"}
            ]
        }
        with patch.object(executor.binance_api, "margin_account", return_value=equal_threshold, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), False)
        with patch.object(executor.binance_api, "margin_account", return_value=above_debt, create=True):
            self.assertIs(executor._exchange_position_exists("BTCUSDC"), True)

    def test_base_asset_absent_returns_none(self):
        self._margin_mode()
        margin_payload = {"userAssets": [{"asset": "ETH", "free": "1", "locked": "0", "borrowed": "0", "interest": "0"}]}
        with patch.object(executor.binance_api, "margin_account", return_value=margin_payload, create=True):
            self.assertIsNone(executor._exchange_position_exists("BTCUSDC"))

        executor.ENV.update({"TRADE_MODE": "spot", "SYMBOL": "BTCUSDC", "MIN_QTY": 0.001})
        spot_payload = {"balances": [{"asset": "ETH", "free": "1", "locked": "0"}]}
        with patch.object(executor.binance_api, "account", return_value=spot_payload, create=True):
            self.assertIsNone(executor._exchange_position_exists("BTCUSDC"))


class SyncHarness(EnvRestoreMixin):
    def _live_st(self):
        return {
            "position": {
                "status": "OPEN",
                "mode": "live",
                "side": "LONG",
                "trade_key": "TK-LIVE",
                "order_id": 900,
                "qty": 0.03,
                "orders": {"tp1": 111, "tp2": 222, "sl": None},
                "prices": {"entry": 100.0, "sl": 90.0, "tp1": 110.0, "tp2": 120.0},
            },
            "last_closed": {"trade_key": "STALE"},
            "lock_until": 123.0,
        }

    def _run_sync(
        self,
        st,
        *,
        open_orders_return=_UNSET,
        open_orders_side_effect=_UNSET,
        get_order_return=_UNSET,
        get_order_side_effect=_UNSET,
        exchange_position_exists=_UNSET,
        now_s=1000.0,
    ):
        self._margin_mode()
        events = []
        webhooks = []
        saves = []
        with ExitStack() as stack:
            if open_orders_side_effect is not _UNSET:
                stack.enter_context(patch.object(executor.binance_api, "open_orders", side_effect=open_orders_side_effect))
            else:
                stack.enter_context(patch.object(executor.binance_api, "open_orders", return_value=open_orders_return))

            if get_order_side_effect is not _UNSET:
                stack.enter_context(patch.object(executor.binance_api, "get_order", side_effect=get_order_side_effect))
            elif get_order_return is not _UNSET:
                stack.enter_context(patch.object(executor.binance_api, "get_order", return_value=get_order_return))
            else:
                stack.enter_context(patch.object(executor.binance_api, "get_order", return_value={}))

            if exchange_position_exists is not _UNSET:
                stack.enter_context(patch.object(executor, "_exchange_position_exists", return_value=exchange_position_exists))

            stack.enter_context(patch.object(executor.time, "time", return_value=now_s))
            stack.enter_context(patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"))
            stack.enter_context(patch.object(executor.binance_api, "check_order_status", return_value={}))
            stack.enter_context(patch.object(executor, "save_state", side_effect=lambda state: saves.append(deepcopy(state))))
            stack.enter_context(patch.object(executor, "log_event", side_effect=lambda *args, **kw: events.append((args[0], kw))))
            stack.enter_context(patch.object(executor, "send_webhook", side_effect=lambda payload: webhooks.append(deepcopy(payload))))
            executor.sync_from_binance(st)
        return events, webhooks, saves


class TestSyncTaggedOrderReconciliation(SyncHarness, unittest.TestCase):
    def test_recon_order_missing_emitted_and_order_removed(self):
        st = self._live_st()
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_return=[{"clientOrderId": "EX_TP2_X", "orderId": 222}],
            get_order_side_effect=RuntimeError("-2013 Order does not exist."),
        )

        self.assertNotIn("tp1", st["position"]["orders"])
        self.assertEqual(st["position"]["recon"]["tp1_missing_reason"], "NOT_FOUND")
        self.assertEqual(events[0][0], "RECON_ORDER_MISSING")
        self.assertEqual(events[0][1]["which"], "tp1")
        self.assertEqual(webhooks[0]["event"], "RECON_ORDER_MISSING")
        self.assertEqual(len(saves), 1)

    def test_recon_order_unknown_emitted_and_order_retained(self):
        st = self._live_st()
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_return=[{"clientOrderId": "EX_TP2_X", "orderId": 222}],
            get_order_side_effect=RuntimeError("exchange timeout"),
        )

        self.assertEqual(st["position"]["orders"]["tp1"], 111)
        self.assertIn("tp1_unknown_ts", st["position"]["recon"])
        self.assertEqual(events[0][0], "RECON_ORDER_UNKNOWN")
        self.assertEqual(webhooks[0]["event"], "RECON_ORDER_UNKNOWN")
        self.assertEqual(len(saves), 1)

    def test_recon_order_filled_seen_emitted_and_current_order_key_is_retained(self):
        st = self._live_st()
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_return=[{"clientOrderId": "EX_TP2_X", "orderId": 222}],
            get_order_return={"status": "FILLED", "executedQty": "0.01"},
        )

        self.assertEqual(st["position"]["orders"]["tp1"], 111)
        self.assertIn("tp1_filled_seen_ts", st["position"]["recon"])
        self.assertEqual(events[0][0], "RECON_ORDER_FILLED_SEEN")
        self.assertEqual(webhooks[0]["event"], "RECON_ORDER_FILLED_SEEN")
        self.assertEqual(len(saves), 1)

    def test_recon_exit_not_in_open_but_active_emitted(self):
        st = self._live_st()
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_return=[{"clientOrderId": "EX_TP2_X", "orderId": 222}],
            get_order_return={"status": "NEW", "executedQty": "0"},
        )

        self.assertEqual(st["position"]["orders"]["tp1"], 111)
        self.assertEqual(st["position"]["recon"]["tp1_not_in_open_active_status"], "NEW")
        self.assertEqual(events[0][0], "RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE")
        self.assertEqual(webhooks[0]["event"], "RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE")
        self.assertEqual(len(saves), 1)

    def test_recon_throttle_prevents_repeated_event_spam_but_saves_mutation(self):
        st = self._live_st()
        st["position"]["recon"] = {"last_emit": {"recon:tp1:111:not_found": 999.0}}
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_return=[{"clientOrderId": "EX_TP2_X", "orderId": 222}],
            get_order_side_effect=RuntimeError("-2013 Order does not exist."),
            now_s=1000.0,
        )

        self.assertNotIn("tp1", st["position"]["orders"])
        self.assertEqual(events, [])
        self.assertEqual(webhooks, [])
        self.assertEqual(len(saves), 1)


class TestSyncAttachPath(SyncHarness, unittest.TestCase):
    def test_tagged_orders_without_local_position_attach_shell_and_save(self):
        st = {"position": None, "last_closed": {"trade_key": "OLD"}}
        tagged = [
            {"clientOrderId": "EX_EN_abc", "orderId": 901, "side": "BUY", "price": "100.5", "origQty": "0.03"},
            {"clientOrderId": "EX_TP1_abc", "orderId": 902, "side": "SELL", "price": "110.5", "origQty": "0.01"},
            {"clientOrderId": "EX_TP2_abc", "orderId": 903, "side": "SELL", "price": "120.5", "origQty": "0.01"},
            {"clientOrderId": "EX_SL_abc", "orderId": 904, "side": "SELL", "stopPrice": "90.5", "origQty": "0.03"},
        ]

        events, _webhooks, saves = self._run_sync(st, open_orders_return=tagged)

        pos = st["position"]
        self.assertEqual(pos["status"], "PENDING")
        self.assertEqual(pos["mode"], "live")
        self.assertEqual(pos["opened_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(pos["side"], "LONG")
        self.assertEqual(pos["qty"], 0.03)
        self.assertEqual(pos["order_id"], 901)
        self.assertEqual(pos["prices"], {"entry": 100.5, "sl": 90.5, "tp1": 110.5, "tp2": 120.5})
        self.assertEqual(pos["orders"], {"tp1": 902, "tp2": 903, "sl": 904, "qty1": None, "qty2": None})
        self.assertIs(pos["synced"], True)
        self.assertEqual(events, [("SYNC_ATTACHED", {"side": "LONG", "tagged_orders": 4})])
        self.assertEqual(len(saves), 1)


class TestSyncP5NegativePaths(SyncHarness, unittest.TestCase):
    def _p5_st(self):
        st = self._live_st()
        st["position"]["orders"] = {"tp1": None, "tp2": None, "sl": None}
        return st

    def test_p5_does_not_clear_if_second_open_orders_confirmation_fails(self):
        st = self._p5_st()
        executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = True
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_side_effect=[[], RuntimeError("open orders unavailable")],
            exchange_position_exists=False,
        )

        self.assertIsNotNone(st["position"])
        self.assertEqual(st["last_closed"], {"trade_key": "STALE"})
        self.assertEqual(events[0][0], "POSITION_CLEAR_CHECK_FAILED")
        self.assertEqual(webhooks, [])
        self.assertEqual(saves, [])

    def test_p5_does_not_clear_if_exchange_position_exists_true(self):
        st = self._p5_st()
        executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = True
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_side_effect=[[], []],
            exchange_position_exists=True,
        )

        self.assertIsNotNone(st["position"])
        self.assertEqual(st["last_closed"], {"trade_key": "STALE"})
        self.assertEqual(events[0][0], "SYNC_KEEP_NO_TAGGED_ENTRY_NOT_CANCELED")
        self.assertEqual(events[0][1]["status"], "UNKNOWN")
        self.assertEqual(webhooks, [])
        self.assertEqual(saves, [])

    def test_p5_unknown_exchange_position_keeps_state_and_logs_unknown(self):
        st = self._p5_st()
        executor.ENV["I13_CLEAR_STATE_ON_EXCHANGE_CLEAR"] = True
        events, webhooks, saves = self._run_sync(
            st,
            open_orders_side_effect=[[], []],
            exchange_position_exists=None,
        )

        self.assertIsNotNone(st["position"])
        self.assertEqual(st["last_closed"], {"trade_key": "STALE"})
        self.assertEqual(events[0], ("POSITION_CLEAR_EXCHANGE_UNKNOWN", {"mode": "live", "symbol": "BTCUSDC"}))
        self.assertEqual(events[1][0], "SYNC_KEEP_NO_TAGGED_ENTRY_NOT_CANCELED")
        self.assertEqual(events[1][1]["status"], "UNKNOWN")
        self.assertEqual(webhooks, [])
        self.assertEqual(saves, [])
