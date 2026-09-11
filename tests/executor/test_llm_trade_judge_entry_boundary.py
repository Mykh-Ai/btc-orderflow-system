from __future__ import annotations

from executor_mod import llm_trade_judge
from executor_mod.entry_snapshot import build_entry_snapshot


def _full_pack() -> dict:
    pack = {
        "schema_version": "llm_trade_judge_open_v1",
        "trade_key": "T-1",
        "symbol": "BTCUSDC",
        "direction": "long",
        "entry": 70000.0,
        "entry_actual": 70001.0,
        "prices": {"entry": 70000.0, "sl": 69700.0, "tp1": 70600.0, "tp2": 71200.0},
        "orders": {"sl": "secret-order", "tp1": "secret-order-2"},
        "order_id": "secret-order",
        "outcome": {"pnl": 123.0},
        "analysis_cutoff_ts": "2026-07-26T00:26:00+00:00",
        "peak_ts": "2026-07-26T00:26:00+00:00",
        "src_evt": {
            "kind": "long",
            "price_usdt": 70000.0,
            "delta": 100.0,
            "loss_filter_admission": {
                "decision": "KEEP",
                "filter_a": {"status": "PASS"},
                "filter_b": {"status": "PASS"},
            },
        },
        "market_monitor_snapshot": {"schema_version": "market_monitor_snapshot_v1", "data_gaps": []},
        "market_context": {"schema_version": "context_v1", "windows": {"240": {"status": "READY"}}},
        "data_gaps": [],
    }
    pack["entry_snapshot"] = build_entry_snapshot(pack)
    return pack


def test_prompt_uses_snapshot_when_full_journal_pack_has_management_fields() -> None:
    pack = _full_pack()
    prompt = llm_trade_judge.build_llm_trade_judge_prompt(pack)
    assert "secret-order" not in prompt
    assert '"orders"' not in prompt
    assert '"outcome"' not in prompt
    assert "LLM_ENTRY_SNAPSHOT_V2" in prompt


def test_injected_model_client_receives_entry_only_wrapper() -> None:
    captured: dict = {}

    def client(**kwargs):
        captured.update(kwargs)
        return '{"verdict":"SUPPORT","competitive_side":"BOT","confidence":0.7,"setup_class":"honest_directional_flow","reason_codes":[],"risk_flags":[],"summary_ua":null}'

    llm_trade_judge.configure(
        {"LLM_TRADE_JUDGE_MODEL": "test-model", "LLM_TRADE_JUDGE_MAX_RETRIES": "0"},
        openai_client_fn=client,
    )
    raw = llm_trade_judge.call_openai_trade_judge(_full_pack())
    assert '"verdict":"SUPPORT"' in raw
    sent = captured["evidence_pack"]
    assert set(sent) == {"schema_version", "prompt_version", "entry_snapshot"}
    assert "orders" not in str(sent).lower()
    assert "pnl" not in str(sent).lower()
