import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import executor
import executor_mod.close_reporting as close_reporting


class FakeTradeExecutionSnapshot:
    def __init__(self, *, record_result=None, record_error=None, local_result=None):
        self.record_result = record_result if record_result is not None else {"snapshot": True}
        self.record_error = record_error
        self.local_result = local_result if local_result is not None else {"local": True}
        self.record_calls = []
        self.local_calls = []

    def record_final_execution_snapshot(self, st, source, binance_api=None):
        self.record_calls.append((st, source, binance_api))
        if self.record_error:
            raise self.record_error
        return self.record_result

    def build_local_snapshot(self, st, last_closed, source):
        self.local_calls.append((st, last_closed, source))
        return self.local_result


_DEFAULT_PAYLOAD = object()


class FakeTradeCloseSummary:
    def __init__(self, payload=_DEFAULT_PAYLOAD, error=None):
        self.payload = {"event": "TRADE_CLOSED_SUMMARY", "trade_key": "TK", "text": "closed"} if payload is _DEFAULT_PAYLOAD else payload
        self.error = error
        self.calls = []

    def build_trade_closed_summary_payload(self, snapshot, **valuation):
        self.calls.append((snapshot, valuation))
        if self.error:
            raise self.error
        return self.payload


class TestCloseReporting(unittest.TestCase):
    def test_quote_asset_suffix_behavior(self):
        self.assertEqual(close_reporting.quote_asset("BTCUSDC"), "USDC")
        self.assertEqual(close_reporting.quote_asset("BTCUSDT"), "USDT")
        self.assertEqual(close_reporting.quote_asset("ETHFDUSD"), "FDUSD")
        self.assertEqual(close_reporting.quote_asset("BNBBUSD"), "BUSD")
        self.assertEqual(close_reporting.quote_asset("BTCUSD"), "USD")
        self.assertEqual(close_reporting.quote_asset("UNKNOWN"), "")

    def test_commission_usdc_valuation_returns_usdc_commission_directly(self):
        api = SimpleNamespace(get_mid_price=lambda symbol: self.fail("mid price should not be used"))
        out = close_reporting.commission_usdc_valuation(
            {"symbol": "BTCUSDC", "fees": {"commission_by_asset": {"USDC": "1.25"}}},
            binance_api=api,
        )

        self.assertEqual(out, {
            "commission_usdc_approx": "1.25",
            "commission_valuation_source": "binance_public_mid_at_notification",
            "commission_valuation_symbol": "USDC",
        })

    def test_commission_usdc_valuation_converts_bnb_commission(self):
        calls = []
        api = SimpleNamespace(get_mid_price=lambda symbol: calls.append(symbol) or "650.5")

        out = close_reporting.commission_usdc_valuation(
            {"symbol": "BTCUSDC", "fees": {"commission_by_asset": {"BNB": "0.01"}}},
            binance_api=api,
        )

        self.assertEqual(calls, ["BNBUSDC"])
        self.assertEqual(out["commission_usdc_approx"], "6.505")
        self.assertEqual(out["commission_valuation_symbol"], "BNBUSDC")

    def test_commission_usdc_valuation_returns_empty_for_unsupported_or_non_usdc(self):
        api = SimpleNamespace(get_mid_price=lambda symbol: "650")
        self.assertEqual(
            close_reporting.commission_usdc_valuation(
                {"symbol": "BTCUSDT", "fees": {"commission_by_asset": {"USDC": "1"}}},
                binance_api=api,
            ),
            {},
        )
        self.assertEqual(
            close_reporting.commission_usdc_valuation(
                {"symbol": "BTCUSDC", "fees": {"commission_by_asset": {"BTC": "0.1"}}},
                binance_api=api,
            ),
            {},
        )

    def test_record_trade_execution_snapshot_returns_snapshot_on_success(self):
        snap = FakeTradeExecutionSnapshot(record_result={"ok": True})
        api = object()

        out = close_reporting.record_trade_execution_snapshot(
            {"last_closed": {}},
            "_close_slot",
            enrich_exchange=True,
            binance_api=api,
            log_event=lambda *a, **k: None,
            trade_execution_snapshot=snap,
        )

        self.assertEqual(out, {"ok": True})
        self.assertIs(snap.record_calls[0][2], api)

    def test_record_trade_execution_snapshot_logs_and_returns_none_on_exception(self):
        events = []
        snap = FakeTradeExecutionSnapshot(record_error=RuntimeError("boom"))

        out = close_reporting.record_trade_execution_snapshot(
            {},
            "sync_exchange_clear",
            log_event=lambda *a, **k: events.append((a, k)),
            trade_execution_snapshot=snap,
        )

        self.assertIsNone(out)
        self.assertEqual(events[0][0], ("TRADE_EXECUTION_SNAPSHOT_ERROR",))
        self.assertEqual(events[0][1]["source"], "sync_exchange_clear")
        self.assertEqual(events[0][1]["error"], "boom")

    def test_send_trade_closed_summary_uses_provided_snapshot(self):
        sent = []
        events = []
        snapshot = {"symbol": "BTCUSDC", "fees": {"commission_by_asset": {"USDC": "1"}}}
        summary = FakeTradeCloseSummary(payload={"event": "TRADE_CLOSED_SUMMARY", "trade_key": "TK", "gross_pnl_usdc": "10", "net_pnl_approx_usdc": "9", "commission_usdc_approx": "1"})
        snap = FakeTradeExecutionSnapshot()

        close_reporting.send_trade_closed_summary(
            {"last_closed": {"trade_key": "LC"}},
            snapshot,
            binance_api=SimpleNamespace(get_mid_price=lambda symbol: "1"),
            log_event=lambda *a, **k: events.append((a, k)),
            send_webhook=lambda payload: sent.append(payload),
            trade_execution_snapshot=snap,
            trade_close_summary=summary,
        )

        self.assertEqual(sent, [summary.payload])
        self.assertEqual(summary.calls[0][0], snapshot)
        self.assertFalse(snap.local_calls)
        self.assertEqual(events[0][0], ("TRADE_CLOSED_SUMMARY_SENT",))

    def test_send_trade_closed_summary_falls_back_to_local_snapshot(self):
        sent = []
        local_snapshot = {"symbol": "BTCUSDC", "fees": {}}
        snap = FakeTradeExecutionSnapshot(local_result=local_snapshot)
        summary = FakeTradeCloseSummary(payload={"event": "TRADE_CLOSED_SUMMARY", "trade_key": "TK"})
        st = {"last_closed": {"trade_key": "TK", "reason": "SL"}}

        close_reporting.send_trade_closed_summary(
            st,
            None,
            binance_api=SimpleNamespace(get_mid_price=lambda symbol: "1"),
            log_event=lambda *a, **k: None,
            send_webhook=lambda payload: sent.append(payload),
            trade_execution_snapshot=snap,
            trade_close_summary=summary,
        )

        self.assertEqual(snap.local_calls, [(st, st["last_closed"], "_close_slot")])
        self.assertEqual(summary.calls[0][0], local_snapshot)
        self.assertEqual(sent, [summary.payload])

    def test_send_trade_closed_summary_sends_no_webhook_when_payload_falsy(self):
        sent = []
        summary = FakeTradeCloseSummary(payload=None)

        close_reporting.send_trade_closed_summary(
            {},
            {"symbol": "BTCUSDC", "fees": {}},
            binance_api=SimpleNamespace(get_mid_price=lambda symbol: "1"),
            log_event=lambda *a, **k: None,
            send_webhook=lambda payload: sent.append(payload),
            trade_execution_snapshot=FakeTradeExecutionSnapshot(),
            trade_close_summary=summary,
        )

        self.assertEqual(sent, [])

    def test_send_trade_closed_summary_swallows_failures_and_logs_error(self):
        events = []

        close_reporting.send_trade_closed_summary(
            {},
            {"symbol": "BTCUSDC", "fees": {}},
            binance_api=SimpleNamespace(get_mid_price=lambda symbol: "1"),
            log_event=lambda *a, **k: events.append((a, k)),
            send_webhook=lambda payload: (_ for _ in ()).throw(RuntimeError("webhook down")),
            trade_execution_snapshot=FakeTradeExecutionSnapshot(),
            trade_close_summary=FakeTradeCloseSummary(),
        )

        self.assertEqual(events[0][0], ("TRADE_CLOSED_SUMMARY_ERROR",))
        self.assertEqual(events[0][1]["error"], "webhook down")

    def test_send_trade_closed_summary_swallows_payload_build_failures(self):
        events = []

        close_reporting.send_trade_closed_summary(
            {},
            {"symbol": "BTCUSDC", "fees": {}},
            binance_api=SimpleNamespace(get_mid_price=lambda symbol: "1"),
            log_event=lambda *a, **k: events.append((a, k)),
            send_webhook=lambda payload: None,
            trade_execution_snapshot=FakeTradeExecutionSnapshot(),
            trade_close_summary=FakeTradeCloseSummary(error=RuntimeError("payload boom")),
        )

        self.assertEqual(events[0][0], ("TRADE_CLOSED_SUMMARY_ERROR",))
        self.assertEqual(events[0][1]["error"], "payload boom")

    def test_executor_record_wrapper_uses_live_patched_dependency(self):
        calls = []

        def fake_record(st, source, binance_api=None):
            calls.append((st, source, binance_api))
            return {"patched": True}

        with patch.object(executor.trade_execution_snapshot, "record_final_execution_snapshot", side_effect=fake_record):
            out = executor._record_trade_execution_snapshot({"last_closed": {}}, "_close_slot", enrich_exchange=True)

        self.assertEqual(out, {"patched": True})
        self.assertIs(calls[0][2], executor.binance_api)

    def test_executor_summary_wrapper_uses_live_patched_send_webhook(self):
        sent = []
        snapshot = {"symbol": "BTCUSDC", "fees": {}}
        payload = {"event": "TRADE_CLOSED_SUMMARY", "trade_key": "TK"}

        with patch.object(executor.trade_close_summary, "build_trade_closed_summary_payload", return_value=payload), \
             patch.object(executor, "send_webhook", lambda p: sent.append(p)), \
             patch.object(executor, "log_event", lambda *a, **k: None):
            executor._send_trade_closed_summary({}, snapshot)

        self.assertEqual(sent, [payload])

    def test_module_purity(self):
        source = Path(close_reporting.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        forbidden_imports = [
            "executor",
            "executor_mod.binance_api",
            "executor_mod.notifications",
            "executor_mod.state_store",
            "executor_mod.margin_guard",
            "executor_mod.trade_execution_snapshot",
            "executor_mod.trade_close_summary",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, imported)
            self.assertNotIn(f"import {forbidden}", source)


if __name__ == "__main__":
    unittest.main()
