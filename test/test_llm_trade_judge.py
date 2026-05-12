import json
import os
import tempfile
import unittest

from executor_mod import llm_trade_judge as judge


def _pos(**overrides):
    pos = {
        "status": "OPEN",
        "mode": "live",
        "side": "LONG",
        "qty": 0.12,
        "entry": 95000.0,
        "entry_actual": 95001.5,
        "opened_at": "2026-01-01T00:00:05Z",
        "filled_at": "2026-01-01T00:00:10Z",
        "order_id": 111,
        "client_id": "EX_EN_1",
        "trade_key": "EX_EN_1",
        "entry_mode": "LIMIT_THEN_MARKET",
        "executedQty": "0.12",
        "cummulativeQuoteQty": "11400",
        "k_entry": 1.0001,
        "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
        "orders": {"sl": 201, "tp1": 202, "tp2": 203, "qty1": 0.04, "qty2": 0.04, "qty3": 0.04},
        "src_evt": {
            "ts": "2026-01-01T00:00:00Z",
            "kind": "long",
            "price_usdt": 94990.0,
        },
    }
    pos.update(overrides)
    return pos


class TestCutoffAndEvidence(unittest.TestCase):
    def setUp(self):
        judge.configure({"SYMBOL": "BTCUSDC", "LLM_TRADE_JUDGE_ENABLED": False})

    def test_choose_analysis_cutoff_uses_src_evt_ts(self):
        cutoff = judge.choose_analysis_cutoff(_pos())
        self.assertEqual(cutoff["peak_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(cutoff["cutoff_source"], "position.src_evt.ts")

    def test_missing_src_evt_falls_back_to_filled_at(self):
        pos = _pos(src_evt={})
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertIsNone(cutoff["peak_ts"])
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:10Z")
        self.assertEqual(cutoff["cutoff_source"], "entry_ts_fallback")

    def test_missing_src_evt_falls_back_to_opened_at(self):
        pos = _pos(src_evt={}, filled_at=None)
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:05Z")
        self.assertEqual(cutoff["cutoff_source"], "entry_ts_fallback")

    def test_missing_all_timestamps_marks_gap(self):
        pos = _pos(src_evt={}, filled_at=None, opened_at=None)
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertIsNone(cutoff["analysis_cutoff_ts"])
        self.assertEqual(cutoff["cutoff_source"], "missing")
        self.assertIn("missing_analysis_cutoff_ts", cutoff["data_gaps"])

    def test_build_pretrade_evidence_pack_fields(self):
        st = {"baseline": {"active": {"trade_key": "EX_EN_1", "balances": {"quote_free": 100.0}}}}
        pack = judge.build_pretrade_evidence_pack(_pos(), st, "EXITS_PLACED_V15")
        self.assertEqual(pack["schema_version"], "llm_trade_judge_open_v1")
        self.assertEqual(pack["trade_key"], "EX_EN_1")
        self.assertEqual(pack["symbol"], "BTCUSDC")
        self.assertEqual(pack["direction"], "long")
        self.assertEqual(pack["prices"]["sl"], 94000.0)
        self.assertEqual(pack["orders"]["tp1"], 202)
        self.assertEqual(pack["src_evt"]["ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["peak_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["cutoff_source"], "position.src_evt.ts")
        self.assertIn("baseline", pack)


class TestVerdictJournal(unittest.TestCase):
    def test_duplicate_trade_key_does_not_append_second_primary_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "state", "llm_trade_verdicts.jsonl")
            saved = []
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                },
                save_state_fn=lambda st: saved.append(dict(st)),
            )
            st = {"baseline": {"active": {"trade_key": "EX_EN_1"}}}
            first = judge.maybe_record_llm_pretrade_stub(st, _pos())
            second = judge.maybe_record_llm_pretrade_stub(st, _pos())

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "noop")
            self.assertEqual(second["reason"], "duplicate_primary")
            with open(journal, "r", encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["is_primary"])
            self.assertEqual(st["llm"]["pretrade_done"]["EX_EN_1"], records[0]["verdict_id"])
            self.assertTrue(saved)

    def test_noop_if_position_not_open(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                }
            )
            result = judge.maybe_record_llm_pretrade_stub({}, _pos(status="OPEN_FILLED"))
            self.assertEqual(result["status"], "noop")
            self.assertEqual(result["reason"], "position_not_open")
            self.assertFalse(os.path.exists(journal))

    def test_noop_if_orders_missing(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                }
            )
            result = judge.maybe_record_llm_pretrade_stub({}, _pos(orders={}))
            self.assertEqual(result["status"], "noop")
            self.assertEqual(result["reason"], "missing_orders")
            self.assertFalse(os.path.exists(journal))


class TestLifecycleAndScoring(unittest.TestCase):
    def test_lifecycle_classes(self):
        self.assertEqual(judge.classify_lifecycle(False, False, True, False, "SL"), "plain_sl")
        self.assertEqual(judge.classify_lifecycle(True, False, True, False, "SL"), "tp1_sl")
        self.assertEqual(judge.classify_lifecycle(True, True, True, True, "SL"), "tp1_tp2_trailing_stop")
        self.assertEqual(judge.classify_lifecycle(False, True, False, False, "TP2"), "manual_or_unknown")

    def test_scoring_matrix_reject(self):
        self.assertEqual(judge.score_llm_vs_bot("REJECT", "plain_sl")["llm_points"], 2)
        self.assertEqual(judge.score_llm_vs_bot("REJECT", "tp1_sl")["llm_points"], 1)
        score = judge.score_llm_vs_bot("REJECT", "tp1_tp2_trailing_stop")
        self.assertEqual(score["llm_points"], 0)
        self.assertEqual(score["bot_points"], 2)

    def test_scoring_matrix_unclear(self):
        self.assertEqual(judge.score_llm_vs_bot("UNCLEAR", "plain_sl")["llm_points"], 1)
        score = judge.score_llm_vs_bot("UNCLEAR", "tp1_sl")
        self.assertEqual(score["llm_points"], 0)
        self.assertEqual(score["bot_points"], 1)
        score = judge.score_llm_vs_bot("UNCLEAR", "tp1_tp2_trailing_stop")
        self.assertEqual(score["bot_points"], 2)

    def test_scoring_matrix_support_alignment(self):
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "plain_sl")["alignment_score"], -2)
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "tp1_sl")["alignment_score"], 1)
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "tp1_tp2_trailing_stop")["alignment_score"], 2)

    def test_stub_not_called_not_scored(self):
        score = judge.score_llm_vs_bot("STUB_NOT_CALLED", "plain_sl")
        self.assertFalse(score["applies"])
