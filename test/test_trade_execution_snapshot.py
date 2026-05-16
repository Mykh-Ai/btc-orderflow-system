import json
import os
import tempfile
import unittest
from unittest.mock import patch

import executor_mod.trade_execution_snapshot as snap


def _last_closed(**overrides):
    lc = {
        "ts": "2025-06-01T10:00:00Z",
        "mode": "live",
        "reason": "SL",
        "side": "LONG",
        "trade_key": "EX_EN_1000",
        "order_id": 10,
        "order_id_tp1": 20,
        "order_id_tp2": 30,
        "order_id_sl": 40,
        "qty1": 0.01,
        "qty2": 0.01,
        "qty3": 0.01,
        "tp1_done": False,
        "tp2_done": False,
        "sl_done": True,
        "prices": {"entry": 100.0, "tp1": 110.0, "tp2": 120.0, "sl": 90.0},
    }
    lc.update(overrides)
    return lc


class FakeBinanceApi:
    def __init__(self, fills_by_order=None, fail_orders=None, fail_all=False):
        self.fills_by_order = fills_by_order or {}
        self.fail_orders = set(fail_orders or [])
        self.fail_all = fail_all

    def _env(self):
        return {"SYMBOL": "BTCUSDC", "TRADE_MODE": "margin", "MARGIN_ISOLATED": "FALSE"}

    def margin_my_trades(self, symbol, order_id=None, **_kwargs):
        if self.fail_all or order_id in self.fail_orders:
            raise RuntimeError(f"boom {order_id}")
        return self.fills_by_order.get(order_id, [])


class TestLifecycleClassification(unittest.TestCase):
    def test_plain_sl(self):
        self.assertEqual(snap.classify_lifecycle_from_last_closed(_last_closed()), "plain_sl")

    def test_tp1_sl(self):
        self.assertEqual(
            snap.classify_lifecycle_from_last_closed(_last_closed(tp1_done=True, tp2_done=False, sl_done=True)),
            "tp1_sl",
        )

    def test_tp1_tp2_trailing_stop(self):
        self.assertEqual(
            snap.classify_lifecycle_from_last_closed(_last_closed(tp1_done=True, tp2_done=True, sl_done=False)),
            "tp1_tp2_trailing_stop",
        )

    def test_manual_or_unknown(self):
        self.assertEqual(
            snap.classify_lifecycle_from_last_closed(_last_closed(tp1_done=False, tp2_done=False, sl_done=False)),
            "manual_or_unknown",
        )


class TestLocalSnapshot(unittest.TestCase):
    def test_build_local_snapshot_core_fields(self):
        st = {"last_closed": _last_closed()}
        with patch.dict(os.environ, {"SYMBOL": "BTCUSDC"}, clear=False):
            out = snap.build_local_snapshot(st, st["last_closed"], "_close_slot")
        self.assertEqual(out["trade_key"], "EX_EN_1000")
        self.assertEqual(out["symbol"], "BTCUSDC")
        self.assertEqual(out["orders"]["entry"]["order_id"], 10)
        self.assertEqual(out["orders"]["tp1"]["order_id"], 20)
        self.assertEqual(out["orders"]["tp2"]["order_id"], 30)
        self.assertEqual(out["orders"]["final_sl"]["order_id"], 40)
        self.assertEqual(out["lifecycle_class"], "plain_sl")
        self.assertFalse(out["excluded_from_scoring"])

    def test_exclusion_by_env(self):
        with patch.dict(os.environ, {"LLM_TRADE_JUDGE_SCORE_EXCLUDE_KEYS": "EX_EN_1778689753"}, clear=False):
            excluded = snap.should_exclude_from_scoring("EX_EN_1778689753", "_close_slot", _last_closed())
            normal = snap.should_exclude_from_scoring("EX_EN_NORMAL", "_close_slot", _last_closed())
        self.assertTrue(excluded["excluded_from_scoring"])
        self.assertEqual(excluded["scoring_exclusion_reason"], "manual_false_peak_mechanics_test")
        self.assertFalse(normal["excluded_from_scoring"])

    def test_secondary_source_excluded(self):
        out = snap.should_exclude_from_scoring("EX_EN_X", "sync_exchange_clear", _last_closed())
        self.assertTrue(out["excluded_from_scoring"])
        self.assertEqual(out["scoring_exclusion_reason"], "reconciliation_exchange_clear")


class TestFillNormalization(unittest.TestCase):
    def test_normalize_trade_fill(self):
        raw = {
            "id": 7,
            "orderId": 10,
            "price": "100.50",
            "qty": "0.2",
            "commission": "0.0001",
            "commissionAsset": "BTC",
            "time": 123456,
            "isBuyer": True,
            "isMaker": False,
            "isBestMatch": True,
        }
        out = snap.normalize_trade_fill(raw)
        self.assertEqual(out["id"], 7)
        self.assertEqual(out["orderId"], 10)
        self.assertEqual(out["price"], "100.50")
        self.assertEqual(out["qty"], "0.2")
        self.assertEqual(out["quoteQty"], "20.100")
        self.assertEqual(out["commission"], "0.0001")
        self.assertEqual(out["commissionAsset"], "BTC")
        self.assertEqual(out["time"], 123456)
        self.assertIs(out["isBuyer"], True)
        self.assertIs(out["isMaker"], False)
        self.assertIs(out["isBestMatch"], True)

    def test_summarize_fills(self):
        fills = [
            snap.normalize_trade_fill({"price": "100", "qty": "1", "commission": "0.1", "commissionAsset": "USDC", "time": 10}),
            snap.normalize_trade_fill({"price": "110", "qty": "1", "commission": "0.2", "commissionAsset": "USDC", "time": 20}),
        ]
        out = snap.summarize_fills(fills)
        self.assertEqual(out["total_qty"], "2")
        self.assertEqual(out["total_quote_qty"], "210")
        self.assertEqual(out["avg_price"], "105")
        self.assertEqual(out["commission_by_asset"], {"USDC": "0.3"})
        self.assertEqual(out["first_fill_time"], 10)
        self.assertEqual(out["last_fill_time"], 20)


class TestExchangeEnrichment(unittest.TestCase):
    def _snapshot(self):
        st = {"last_closed": _last_closed()}
        return snap.build_local_snapshot(st, st["last_closed"], "_close_slot")

    def test_enrich_success_for_entry_tp_sl(self):
        api = FakeBinanceApi(
            fills_by_order={
                10: [{"orderId": 10, "price": "100", "qty": "1", "commission": "0.1", "commissionAsset": "USDC"}],
                20: [{"orderId": 20, "price": "110", "qty": "0.4", "commission": "0.04", "commissionAsset": "USDC"}],
                30: [{"orderId": 30, "price": "120", "qty": "0.3", "commission": "0.03", "commissionAsset": "USDC"}],
                40: [{"orderId": 40, "price": "90", "qty": "0.3", "commission": "0.03", "commissionAsset": "USDC"}],
            }
        )
        out = snap.enrich_snapshot_with_margin_trades(self._snapshot(), api)
        self.assertEqual(out["snapshot_status"], "complete")
        self.assertEqual(out["fill_summaries"]["entry"]["total_quote_qty"], "100")
        self.assertEqual(out["fees"]["commission_by_asset"], {"USDC": "0.20"})
        self.assertEqual(out["pnl"]["gross_realized_pnl_approx"], "7.0")

    def test_partial_failure(self):
        api = FakeBinanceApi(
            fills_by_order={10: [{"orderId": 10, "price": "100", "qty": "1"}]},
            fail_orders={20},
        )
        out = snap.enrich_snapshot_with_margin_trades(self._snapshot(), api)
        self.assertEqual(out["snapshot_status"], "partial")
        self.assertTrue(out["errors"])
        self.assertEqual(out["errors"][0]["code"], "margin_my_trades_failed")

    def test_all_failure_leaves_local_only(self):
        out = snap.enrich_snapshot_with_margin_trades(self._snapshot(), FakeBinanceApi(fail_all=True))
        self.assertEqual(out["snapshot_status"], "local_only")
        self.assertEqual(len(out["errors"]), 4)


class TestPnlAndAppend(unittest.TestCase):
    def _snapshot_with_quotes(self, entry_quote, exit_quote):
        st = {"last_closed": _last_closed()}
        out = snap.build_local_snapshot(st, st["last_closed"], "_close_slot")
        out["fill_summaries"]["entry"] = {"total_quote_qty": str(entry_quote)}
        out["fill_summaries"]["tp1"] = {"total_quote_qty": str(exit_quote)}
        out["fees"]["commission_by_asset"] = {}
        return out

    def test_gross_pnl_positive(self):
        out = snap.compute_gross_realized_pnl_approx(self._snapshot_with_quotes(100, 110))
        self.assertEqual(out["pnl"]["gross_realized_pnl_approx"], "10")

    def test_gross_pnl_negative(self):
        out = snap.compute_gross_realized_pnl_approx(self._snapshot_with_quotes(100, 90))
        self.assertEqual(out["pnl"]["gross_realized_pnl_approx"], "-10")

    def test_append_execution_snapshot_jsonl(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            snap.append_execution_snapshot(path, {"schema": snap.SCHEMA_VERSION, "n": 1})
            snap.append_execution_snapshot(path, {"schema": snap.SCHEMA_VERSION, "n": 2})
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual([row["n"] for row in rows], [1, 2])
        finally:
            os.unlink(path)

    def test_record_final_execution_snapshot_never_raises_on_binance_failure(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            st = {"last_closed": _last_closed()}
            with patch.dict(os.environ, {"TRADE_EXECUTION_SNAPSHOTS_FN": path}, clear=False):
                out = snap.record_final_execution_snapshot(st, "_close_slot", binance_api=FakeBinanceApi(fail_all=True))
            self.assertIsNotNone(out)
            self.assertEqual(out["snapshot_status"], "local_only")
            self.assertTrue(out["errors"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
