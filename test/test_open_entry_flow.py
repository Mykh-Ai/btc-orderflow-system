import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import executor


def _peak(**overrides):
    evt = {
        "ts": "2026-01-01T00:00:00Z",
        "action": "PEAK",
        "kind": "long",
        "source": "DeltaScout",
        "price": 100.0,
        "delta": 50,
        "vol": 60,
        "imb": 0.6,
        "vwap": 99.5,
        "poc": 99.0,
    }
    evt.update(overrides)
    return evt


def _df(rows=3):
    return pd.DataFrame(
        {
            "Timestamp": pd.date_range("2026-01-01T00:00:00Z", periods=rows, freq="min"),
            "price": [100.0 + i for i in range(rows)],
            "LowPrice": [90.0 + i for i in range(rows)],
            "HiPrice": [110.0 + i for i in range(rows)],
            "ClosePrice": [100.0 + i for i in range(rows)],
        }
    )


class TestOpenEntryFlow(unittest.TestCase):
    def setUp(self):
        self.env_snapshot = deepcopy(executor.ENV)
        executor.ENV["SYMBOL"] = "BTCUSDC"
        executor.ENV["TRADE_MODE"] = "spot"
        executor.ENV["POLL_SEC"] = 0
        executor.ENV["TAIL_LINES"] = 80
        executor.ENV["DELTASCOUT_LOG"] = "ignored.jsonl"
        executor.ENV["INVAR_ENABLED"] = False
        executor.ENV["MAX_PEAK_AGE_SEC"] = 600
        executor.ENV["LOCK_SEC"] = 15
        executor.ENV["ENTRY_MODE"] = "LIMIT_THEN_MARKET"
        executor.ENV["QTY_USD"] = 50.0
        executor.ENV["TICK_SIZE"] = Decimal("0.1")
        executor.ENV["QTY_STEP"] = Decimal("0.001")
        executor.ENV["MIN_NOTIONAL"] = 5.0

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self.env_snapshot)

    def _run_one_open_cycle(
        self,
        *,
        st=None,
        events=None,
        now=1000.0,
        time_value=None,
        df=None,
        entry_mode=None,
        build_entry=101.0,
        swing_stop=90.0,
        tps=None,
        k_entry=1.0,
        qty=0.5,
        qty_valid=True,
        market_order=None,
        market_error=None,
        limit_order=None,
        limit_error=None,
        baseline_snap=None,
        baseline_error=None,
        exits_return=True,
        locked_return=None,
        cooldown_return=None,
        has_open_position_return=None,
        locate_side_effect=None,
        extra_patches=None,
    ):
        st = st if st is not None else {"position": None, "meta": {}}
        events = events if events is not None else [_peak()]
        tps = tps if tps is not None else [111.0, 121.0]
        df = df if df is not None else _df()
        time_value = now if time_value is None else time_value
        baseline_snap = baseline_snap if baseline_snap is not None else {
            "trade_key": f"EX_EN_{int(time_value)}",
            "symbol": "BTCUSDC",
            "trade_mode": "spot",
        }

        order = []
        saves = []
        logs = []
        webhooks = []
        tail_calls = []
        sleep_calls = {"n": 0}
        locate_calls = []

        def fake_sleep(_sec):
            sleep_calls["n"] += 1
            if sleep_calls["n"] > 1:
                raise StopIteration

        def fake_tail(*args, **kwargs):
            tail_calls.append((args, kwargs))
            if len(tail_calls) == 1:
                return []
            return [json.dumps(evt) for evt in events]

        def fake_save(state):
            snap = deepcopy(state)
            saves.append(snap)
            order.append(("save", snap))

        def fake_log(event, **kwargs):
            logs.append((event, deepcopy(kwargs)))
            order.append(("log", event, deepcopy(kwargs)))

        def fake_webhook(payload):
            webhooks.append(deepcopy(payload))
            order.append(("webhook", deepcopy(payload)))

        def fake_sync(state):
            order.append(("sync", deepcopy(state)))

        def fake_build_entry(kind, price):
            order.append(("build_entry_price", kind, price))
            return build_entry

        def fake_swing_stop(frame, idx, side, entry):
            order.append(("swing_stop_far", idx, side, entry))
            return swing_stop

        def fake_compute_tps(entry, sl, side):
            order.append(("compute_tps", entry, sl, side))
            return list(tps)

        def fake_k():
            order.append(("get_usdt_usdc_k",))
            return k_entry

        def fake_qty(entry, usd):
            order.append(("notional_to_qty", entry, usd))
            return qty

        def fake_validate_qty(qty_arg, entry):
            order.append(("validate_qty", qty_arg, entry))
            return qty_valid

        def fake_locate(frame, ts):
            locate_calls.append((frame, ts))
            order.append(("locate_index_by_ts", ts))
            if locate_side_effect is not None:
                return locate_side_effect(frame, ts)
            return 0

        def fake_margin_before(*args, **kwargs):
            order.append(("margin_before", args, deepcopy(kwargs)))

        def fake_margin_after(*args, **kwargs):
            order.append(("margin_after", args, deepcopy(kwargs)))

        def fake_market(*args, **kwargs):
            order.append(("place_market", args, deepcopy(kwargs)))
            if market_error is not None:
                raise market_error
            return market_order if market_order is not None else {"orderId": 200, "executedQty": "0"}

        def fake_limit(*args, **kwargs):
            order.append(("place_limit", args, deepcopy(kwargs)))
            if limit_error is not None:
                raise limit_error
            return limit_order if limit_order is not None else {"orderId": 100}

        def fake_baseline(*args, **kwargs):
            order.append(("baseline", args, deepcopy(kwargs)))
            if baseline_error is not None:
                raise baseline_error
            return deepcopy(baseline_snap)

        def fake_ensure(*args, **kwargs):
            order.append(("ensure_exits", args, deepcopy(kwargs)))
            pos = args[1]
            pos["orders"] = {"sl": 501}
            return exits_return

        def fake_llm(*args, **kwargs):
            order.append(("llm", args, deepcopy(kwargs)))

        if entry_mode is not None:
            executor.ENV["ENTRY_MODE"] = entry_mode

        with ExitStack() as stack:
            stack.enter_context(patch.object(executor, "_validate_trade_mode", return_value="spot"))
            stack.enter_context(patch.object(executor, "load_state", return_value=st))
            stack.enter_context(patch.object(executor, "read_tail_lines", side_effect=fake_tail))
            stack.enter_context(patch.object(executor, "bootstrap_seen_keys_from_tail", return_value=None))
            stack.enter_context(patch.object(executor, "_preflight_margin_cross_usdc", return_value=None))
            stack.enter_context(patch.object(executor, "sync_from_binance", side_effect=fake_sync))
            stack.enter_context(patch.object(executor.atexit, "register", return_value=None))
            stack.enter_context(patch.object(executor.signal, "signal", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_startup", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_shutdown", return_value=None))
            stack.enter_context(patch.object(executor.invariants, "run", return_value=None))
            stack.enter_context(patch.object(executor.time, "sleep", side_effect=fake_sleep))
            stack.enter_context(patch.object(executor.time, "time", return_value=time_value))
            stack.enter_context(patch.object(executor, "_now_s", return_value=now))
            stack.enter_context(patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:05Z"))
            stack.enter_context(patch.object(executor, "save_state", side_effect=fake_save))
            stack.enter_context(patch.object(executor, "log_event", side_effect=fake_log))
            stack.enter_context(patch.object(executor, "send_webhook", side_effect=fake_webhook))
            stack.enter_context(patch.object(executor, "load_df_sorted", return_value=df))
            stack.enter_context(patch.object(executor, "locate_index_by_ts", side_effect=fake_locate))
            build_entry_mock = stack.enter_context(patch.object(executor, "build_entry_price", side_effect=fake_build_entry))
            swing_stop_mock = stack.enter_context(patch.object(executor, "swing_stop_far", side_effect=fake_swing_stop))
            compute_tps_mock = stack.enter_context(patch.object(executor, "compute_tps", side_effect=fake_compute_tps))
            get_k_mock = stack.enter_context(patch.object(executor, "get_usdt_usdc_k", side_effect=fake_k))
            notional_mock = stack.enter_context(patch.object(executor, "notional_to_qty", side_effect=fake_qty))
            validate_mock = stack.enter_context(patch.object(executor, "validate_qty", side_effect=fake_validate_qty))
            margin_before_mock = stack.enter_context(patch.object(executor.margin_guard, "on_before_entry", side_effect=fake_margin_before))
            margin_after_mock = stack.enter_context(patch.object(executor.margin_guard, "on_after_entry_opened", side_effect=fake_margin_after))
            market_mock = stack.enter_context(patch.object(executor.binance_api, "place_spot_market", side_effect=fake_market))
            limit_mock = stack.enter_context(patch.object(executor.binance_api, "place_spot_limit", side_effect=fake_limit))
            baseline_mock = stack.enter_context(patch.object(executor.baseline_policy, "take_snapshot", side_effect=fake_baseline))
            ensure_mock = stack.enter_context(patch.object(executor.exits_flow, "ensure_exits", side_effect=fake_ensure))
            llm_mock = stack.enter_context(patch.object(executor.llm_trade_judge, "maybe_record_llm_pretrade_judge", side_effect=fake_llm))
            if locked_return is not None:
                stack.enter_context(patch.object(executor, "locked", return_value=locked_return))
            if cooldown_return is not None:
                stack.enter_context(patch.object(executor, "in_cooldown", return_value=cooldown_return))
            if has_open_position_return is not None:
                stack.enter_context(patch.object(executor, "has_open_position", return_value=has_open_position_return))
            if extra_patches:
                for patcher in extra_patches:
                    stack.enter_context(patcher)
            try:
                executor.main()
            except StopIteration:
                pass

        return SimpleNamespace(
            st=st,
            order=order,
            saves=saves,
            logs=logs,
            webhooks=webhooks,
            tail_calls=tail_calls,
            sleep_calls=sleep_calls["n"],
            locate_calls=locate_calls,
            build_entry_price=build_entry_mock,
            swing_stop_far=swing_stop_mock,
            compute_tps=compute_tps_mock,
            get_usdt_usdc_k=get_k_mock,
            notional_to_qty=notional_mock,
            validate_qty=validate_mock,
            margin_before=margin_before_mock,
            margin_after=margin_after_mock,
            place_market=market_mock,
            place_limit=limit_mock,
            baseline=baseline_mock,
            ensure_exits=ensure_mock,
            llm=llm_mock,
        )

    def _events(self, h, name):
        return [kwargs for event, kwargs in h.logs if event == name]

    def _order_names(self, h):
        return [item[0] for item in h.order]

    def test_guard_skip_behavior_does_not_place_orders(self):
        cases = [
            (
                "stale_peak",
                {"events": [_peak(ts="2020-01-01T00:00:00Z")], "now": 2000000000.0},
                "stale_peak",
            ),
            ("locked", {"locked_return": True}, "position_lock"),
            ("cooldown", {"cooldown_return": True}, "cooldown"),
            ("open_position", {"has_open_position_return": True}, "position_already_open"),
        ]

        for label, kwargs, reason in cases:
            with self.subTest(label=label):
                h = self._run_one_open_cycle(**kwargs)

                self.assertIn({"reason": reason}, [{k: v for k, v in evt.items() if k == "reason"} for evt in self._events(h, "SKIP_PEAK")])
                h.place_market.assert_not_called()
                h.place_limit.assert_not_called()
                self.assertNotIn("lock_until", h.st)

    def test_lock_saved_before_downstream_calculations_and_agg_unavailable_skips_open(self):
        h = self._run_one_open_cycle(df=pd.DataFrame())

        lock_saves = [snap for snap in h.saves if snap.get("lock_until") == 1015.0]
        self.assertTrue(lock_saves)
        self.assertLess(self._order_names(h).index("save"), self._order_names(h).index("build_entry_price"))
        self.assertEqual(h.st["lock_until"], 1015.0)
        self.assertIn({"reason": "agg_unavailable"}, self._events(h, "SKIP_OPEN"))
        h.place_market.assert_not_called()
        h.place_limit.assert_not_called()

    def test_timestamp_parse_failure_falls_back_to_latest_row(self):
        h = self._run_one_open_cycle(events=[_peak(ts="not-a-timestamp")], df=_df(rows=4))

        self.assertEqual(h.locate_calls, [])
        swing_calls = [item for item in h.order if item[0] == "swing_stop_far"]
        self.assertEqual(swing_calls[0][1], 3)
        self.assertFalse(self._events(h, "LIVE_OPEN_ERROR"))
        h.place_limit.assert_called_once()

    def test_tps_not_ready_and_qty_invalid_skip_without_order(self):
        cases = [
            ("tps_not_ready", {"tps": [111.0]}, "tps_not_ready"),
            ("qty_too_small", {"qty_valid": False}, "qty_too_small"),
        ]

        for label, kwargs, reason in cases:
            with self.subTest(label=label):
                h = self._run_one_open_cycle(**kwargs)

                self.assertIn(reason, [evt["reason"] for evt in self._events(h, "SKIP_OPEN")])
                h.place_market.assert_not_called()
                h.place_limit.assert_not_called()

    def test_long_price_conversion_and_position_schema(self):
        h = self._run_one_open_cycle(
            events=[_peak(kind="long", price=100.0)],
            build_entry=101.0,
            swing_stop=90.0,
            tps=[111.0, 121.0],
            k_entry=1.01,
        )

        h.build_entry_price.assert_called_once_with("long", 100.0)
        h.swing_stop_far.assert_called_once()
        h.compute_tps.assert_called_once()
        h.get_usdt_usdc_k.assert_called_once()
        pos = h.st["position"]
        for key in (
            "status",
            "mode",
            "opened_at",
            "opened_s",
            "side",
            "qty",
            "entry",
            "order_id",
            "client_id",
            "trade_key",
            "entry_mode",
            "entry_actual",
            "k_entry",
            "prices",
            "src_evt",
        ):
            self.assertIn(key, pos)
        self.assertEqual(pos["side"], "LONG")
        self.assertAlmostEqual(pos["entry"], 102.0)
        self.assertAlmostEqual(pos["prices"]["sl"], 90.9)
        self.assertAlmostEqual(pos["prices"]["tp1"], 112.1)
        self.assertAlmostEqual(pos["prices"]["tp2"], 122.2)
        self.assertEqual(pos["src_evt"]["entry_usdt"], 101.0)
        self.assertEqual(pos["src_evt"]["price_usdt"], 100.0)

    def test_short_price_conversion_and_position_schema(self):
        h = self._run_one_open_cycle(
            events=[_peak(kind="short", price=100.0)],
            build_entry=99.0,
            swing_stop=110.0,
            tps=[89.0, 79.0],
            k_entry=1.01,
        )

        h.build_entry_price.assert_called_once_with("short", 100.0)
        pos = h.st["position"]
        self.assertEqual(pos["side"], "SHORT")
        self.assertAlmostEqual(pos["entry"], 100.0)
        self.assertAlmostEqual(pos["prices"]["sl"], 111.1)
        self.assertAlmostEqual(pos["prices"]["tp1"], 89.9)
        self.assertAlmostEqual(pos["prices"]["tp2"], 79.8)
        self.assertEqual(pos["src_evt"]["kind"], "short")

    def test_market_only_filled_places_market_then_margin_after_exits_and_llm(self):
        h = self._run_one_open_cycle(
            entry_mode="MARKET_ONLY",
            market_order={"orderId": 200, "executedQty": "0.5", "cummulativeQuoteQty": "50"},
        )

        self.assertLess(self._order_names(h).index("margin_before"), self._order_names(h).index("place_market"))
        h.place_market.assert_called_once_with("BTCUSDC", "BUY", 0.5, client_id="EX_EN_1000")
        self.assertEqual(h.st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(h.st["position"]["entry_actual"], 100.0)
        h.margin_after.assert_called_once()
        h.ensure_exits.assert_called_once_with(h.st, h.st["position"], reason="open_filled", best_effort=True, save_on_success=False)
        h.llm.assert_called_once()
        save_after_exits = [snap for snap in h.saves if (snap.get("position") or {}).get("orders") == {"sl": 501}]
        self.assertTrue(save_after_exits)

    def test_market_only_not_filled_keeps_pending_without_immediate_exits_or_llm(self):
        h = self._run_one_open_cycle(
            entry_mode="MARKET_ONLY",
            market_order={"orderId": 200, "executedQty": "0"},
        )

        self.assertEqual(h.st["position"]["status"], "PENDING")
        h.margin_after.assert_not_called()
        h.ensure_exits.assert_not_called()
        h.llm.assert_not_called()

    def test_limit_entry_modes_place_limit_and_keep_pending(self):
        for entry_mode in ("LIMIT_THEN_MARKET", "LIMIT_ONLY"):
            with self.subTest(entry_mode=entry_mode):
                h = self._run_one_open_cycle(entry_mode=entry_mode, limit_order={"orderId": "100"})

                self.assertLess(self._order_names(h).index("margin_before"), self._order_names(h).index("place_limit"))
                h.place_limit.assert_called_once_with("BTCUSDC", "BUY", 0.5, 101.0, client_id="EX_EN_1000")
                self.assertEqual(h.st["position"]["status"], "PENDING")
                self.assertIsNone(h.st["position"]["entry_actual"])
                h.ensure_exits.assert_not_called()
                h.llm.assert_not_called()

    def test_baseline_snapshot_success_sets_active_normalizes_truth_and_logs(self):
        st = {"position": None, "meta": {}, "baseline": {"truth": "legacy"}}
        snap = {"trade_key": "EX_EN_1000", "symbol": "BTCUSDC", "trade_mode": "spot", "balances": {"quote_free": 10.0}}

        h = self._run_one_open_cycle(st=st, baseline_snap=snap)

        h.baseline.assert_called_once()
        args = h.baseline.call_args.args
        self.assertIs(args[0], executor.binance_api)
        self.assertIs(args[1], executor.ENV)
        self.assertEqual(args[2:], ("BTCUSDC", "EX_EN_1000", "pre_trade"))
        self.assertEqual(st["baseline"]["active"], snap)
        self.assertIsNone(st["baseline"]["truth"])
        baseline_events = self._events(h, "BASELINE_TAKEN")
        self.assertEqual(baseline_events[0]["trade_key"], "EX_EN_1000")

    def test_baseline_snapshot_failure_logs_error_and_open_continues(self):
        h = self._run_one_open_cycle(baseline_error=RuntimeError("snapshot down"))

        self.assertIn("BASELINE_ERROR", [event for event, _ in h.logs])
        self.assertEqual(h.st["position"]["status"], "PENDING")
        self.assertTrue(any((snap.get("position") or {}).get("trade_key") == "EX_EN_1000" for snap in h.saves))
        self.assertIn("OPEN", [event for event, _ in h.logs])

    def test_save_open_log_and_webhook_ordering(self):
        h = self._run_one_open_cycle()
        names = self._order_names(h)

        position_save_indexes = [
            idx for idx, item in enumerate(h.order)
            if item[0] == "save" and (item[1].get("position") or {}).get("trade_key") == "EX_EN_1000"
        ]
        self.assertTrue(position_save_indexes)
        open_log_index = next(idx for idx, item in enumerate(h.order) if item[0] == "log" and item[1] == "OPEN")
        open_webhook_index = next(idx for idx, item in enumerate(h.order) if item[0] == "webhook" and item[1]["event"] == "OPEN")
        self.assertLess(position_save_indexes[-1], open_log_index)
        self.assertLess(open_log_index, open_webhook_index)
        open_log = self._events(h, "OPEN")[0]
        self.assertEqual(open_log["side"], "LONG")
        self.assertEqual(open_log["entry"], 101.0)
        self.assertEqual(open_log["qty"], 0.5)
        self.assertEqual(open_log["order_id"], 100)
        self.assertEqual(h.webhooks[-1]["event"], "OPEN")
        self.assertEqual(names[open_webhook_index], "webhook")

    def test_live_open_error_logs_and_loop_continues(self):
        h = self._run_one_open_cycle(limit_error=RuntimeError("exchange down"))

        errors = self._events(h, "LIVE_OPEN_ERROR")
        self.assertEqual(errors[0]["error"], "exchange down")
        self.assertEqual(h.sleep_calls, 2)

    def test_multiple_new_events_second_skips_after_first_open(self):
        events = [
            _peak(ts="2026-01-01T00:00:00Z", price=100.0),
            _peak(ts="2026-01-01T00:01:00Z", price=101.0),
        ]

        h = self._run_one_open_cycle(events=events)

        h.place_limit.assert_called_once()
        skip_reasons = [evt["reason"] for evt in self._events(h, "SKIP_PEAK")]
        self.assertIn("position_lock", skip_reasons)


if __name__ == "__main__":
    unittest.main()
