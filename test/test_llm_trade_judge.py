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


class TestRealOpenAIMode(unittest.TestCase):
    def _configure(self, journal, *, client=None, webhook=None, notify=True, saved=None):
        judge.configure(
            {
                "SYMBOL": "BTCUSDC",
                "LLM_TRADE_JUDGE_ENABLED": True,
                "LLM_TRADE_JUDGE_MODE": "openai",
                "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                "LLM_TRADE_JUDGE_MODEL": "gpt-5.5",
                "LLM_TRADE_JUDGE_TIMEOUT_SEC": 20,
                "LLM_TRADE_JUDGE_MAX_RETRIES": 1,
                "LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": notify,
            },
            save_state_fn=(lambda st: saved.append(dict(st))) if saved is not None else None,
            send_webhook_fn=webhook,
            openai_client_fn=client,
        )

    def _records(self, journal):
        with open(journal, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_disabled_mode_does_not_call_client_or_append(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": False,
                    "LLM_TRADE_JUDGE_MODE": "openai",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                },
                openai_client_fn=lambda **kw: calls.append(kw),
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "noop")
            self.assertEqual(calls, [])
            self.assertFalse(os.path.exists(journal))

    def test_stub_mode_still_works(self):
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
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["verdict"], "STUB_NOT_CALLED")

    def test_openai_mode_calls_fake_client_once_and_appends_real_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []

            def fake_client(**kwargs):
                calls.append(kwargs)
                return json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "WRONG",
                    "confidence": 0.72,
                    "setup_class": "continuation_pressure",
                    "reason_codes": ["price_confirms_direction"],
                    "risk_flags": ["late_after_impulse"],
                    "summary_ua": "Погоджуюсь з ботом.",
                })

            self._configure(journal, client=fake_client, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(calls), 1)
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "success")
            self.assertEqual(record["model"], "gpt-5.5")
            self.assertEqual(record["verdict"], "SUPPORT")
            self.assertEqual(record["competitive_side"], "BOT")
            self.assertEqual(record["evidence_pack"]["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")

    def test_duplicate_trade_key_does_not_call_fake_client(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []

            def fake_client(**_kwargs):
                calls.append(1)
                return json.dumps({
                    "verdict": "REJECT",
                    "competitive_side": "BOT",
                    "confidence": 0.74,
                    "setup_class": "exhaustion",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                })

            self._configure(journal, client=fake_client, notify=False)
            first = judge.maybe_record_llm_pretrade_judge({}, _pos())
            second = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["reason"], "duplicate_primary")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(self._records(journal)), 1)

    def test_reject_and_unclear_normalize_to_llm_reject(self):
        for verdict in ("REJECT", "UNCLEAR"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as td:
                journal = os.path.join(td, "v.jsonl")
                self._configure(
                    journal,
                    client=lambda **_kw: json.dumps({
                        "verdict": verdict,
                        "competitive_side": "BOT",
                        "confidence": 0.5,
                        "setup_class": "noisy_peak",
                        "reason_codes": [],
                        "risk_flags": [],
                        "summary_ua": None,
                    }),
                    notify=False,
                )
                judge.maybe_record_llm_pretrade_judge({}, _pos(trade_key=f"TK_{verdict}", client_id=f"TK_{verdict}"))
                record = self._records(journal)[0]
                self.assertEqual(record["competitive_side"], "LLM_REJECT")

    def test_invalid_json_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(journal, client=lambda **_kw: "not-json", notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "json_validation_error")
            self.assertEqual(record["verdict"], "ERROR_NOT_SCORED")

    def test_api_exception_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")

            def boom(**_kwargs):
                raise RuntimeError("api down")

            self._configure(journal, client=boom, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "api_error")

    def test_timeout_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")

            def timeout(**_kwargs):
                raise judge.requests.exceptions.Timeout("slow")

            self._configure(journal, client=timeout, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "timeout")

    def test_telegram_notification_sent_only_after_successful_append(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "UNCLEAR",
                    "competitive_side": "BOT",
                    "confidence": 0.51,
                    "setup_class": "unknown",
                    "reason_codes": [],
                    "risk_flags": ["late_entry"],
                    "summary_ua": "Перевага неясна.",
                }),
                webhook=lambda payload: sent.append(payload),
                notify=True,
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(sent), 1)
            payload = sent[0]
            self.assertEqual(payload["event"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["type"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["symbol"], "BTCUSDC")
            self.assertEqual(payload["mode"], "live")
            self.assertEqual(payload["verdict"], "UNCLEAR")
            self.assertEqual(payload["competitive_side"], "LLM_REJECT")
            self.assertEqual(payload["confidence"], 0.51)
            self.assertEqual(payload["setup_class"], "unknown")
            self.assertEqual(payload["cutoff"], "2026-01-01T00:00:00Z")
            self.assertEqual(payload["cutoff_source"], "position.src_evt.ts")
            self.assertIn("message", payload)
            self.assertIn("telegram_text", payload)
            self.assertEqual(payload["message"], payload["text"])
            self.assertEqual(payload["telegram_text"], payload["text"])
            self.assertIn("LLM Trade Judge", payload["text"])
            self.assertIn("Game rule: UNCLEAR counts as reject-side.", payload["text"])

    def test_error_notification_payload_contains_execution_not_affected(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []

            def boom(**_kwargs):
                raise RuntimeError("api down")

            self._configure(journal, client=boom, webhook=lambda payload: sent.append(payload), notify=True)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(sent), 1)
            payload = sent[0]
            self.assertEqual(payload["event"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["type"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["symbol"], "BTCUSDC")
            self.assertEqual(payload["llm_call_status"], "error")
            self.assertEqual(payload["verdict"], "ERROR_NOT_SCORED")
            self.assertIn("Execution was not affected.", payload["text"])
            self.assertEqual(payload["message"], payload["text"])
            self.assertEqual(payload["telegram_text"], payload["text"])

    def test_telegram_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "honest_directional_flow",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                webhook=lambda payload: sent.append(payload),
                notify=False,
            )
            judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(sent, [])

    def test_append_failure_prevents_telegram_notification(self):
        with tempfile.TemporaryDirectory() as td:
            journal_dir = os.path.join(td, "as_file")
            with open(journal_dir, "w", encoding="utf-8") as fh:
                fh.write("not a dir")
            journal = os.path.join(journal_dir, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "honest_directional_flow",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                webhook=lambda payload: sent.append(payload),
                notify=True,
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "error")
            self.assertEqual(sent, [])

    def test_unknown_setup_class_becomes_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "custom_new_class",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                notify=False,
            )
            judge.maybe_record_llm_pretrade_judge({}, _pos())
            record = self._records(journal)[0]
            self.assertEqual(record["setup_class"], "unknown")
            self.assertIn("unknown_setup_class:custom_new_class", record["validation_errors"])

    def test_missing_api_key_records_error_without_crash(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(journal, client=None, notify=False)
            old_key = os.environ.pop("OPENAI_API_KEY", None)
            try:
                result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            finally:
                if old_key is not None:
                    os.environ["OPENAI_API_KEY"] = old_key
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["error_type"], "missing_api_key")


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
