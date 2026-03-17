from __future__ import annotations

import pandas as pd

from scripts.offline.build_close_outcomes import (
    _filter_df_by_date as _filter_close_df_by_date,
    _dedupe_close_events,
    _filter_close_events_by_date,
    _load_close_events,
    _load_trade_outcomes_events,
    _load_peak_events,
    derive_close_outcomes,
)
from scripts.offline.build_phase1_derived import _filter_df_by_date, derive_reject_dataset


def test_reject_classification_soft_and_multi():
    df = pd.DataFrame(
        [
            {"event": "CANDIDATE_GATE_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:00:00Z"), "seq": 1, "reject_reason": "chop_coh", "kind": "long"},
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:01:00Z"), "seq": 2, "reject_reason": "vwap_distance", "kind": "short", "price": 1010, "vwap": 0, "vwap_max_dist_usd": 1000},
            {"event": "CANDIDATE_GATE_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:02:00Z"), "seq": 3, "reject_reason": "imb_band", "kind": "long", "imb": 0.651, "imb_min": 0.55, "imb_max": 0.65},
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:03:00Z"), "seq": 4, "reject_reason": "direction_mismatch", "kind": "long"},
        ]
    )

    out = derive_reject_dataset(df, "2026-01-01", soft_vwap_margin=20.0, soft_imb_margin=0.01)
    classes = dict(zip(out["seq"], out["reject_class"]))
    assert classes[1] == "multi_condition"
    assert classes[2] == "soft_fail"
    assert classes[3] == "soft_fail"
    assert classes[4] == "single_condition"


def test_close_outcomes_exact_and_ambiguous():
    peaks = pd.DataFrame(
        [
            {"event_ts": pd.Timestamp("2026-01-01T00:10:00Z"), "kind": "long", "price": 100.0, "delta": 1.0, "imb": 0.6, "vol": 10.0, "seq": 1},
            {"event_ts": pd.Timestamp("2026-01-01T00:20:00Z"), "kind": "long", "price": 101.0, "delta": 1.1, "imb": 0.61, "vol": 11.0, "seq": 2},
        ]
    )
    close_events = [
        {
            "ts": "2026-01-01T00:30:00Z",
            "side": "LONG",
            "mode": "paper",
            "reason": "TP1",
            "close_price": 102.0,
            "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long", "price": 100.0, "delta": 1.0, "imb": 0.6, "vol": 10.0},
        },
        {
            "ts": "2026-01-01T00:40:00Z",
            "side": "LONG",
            "mode": "paper",
            "reason": "SL",
            "close_price": 99.0,
        },
    ]
    out = derive_close_outcomes(close_events, peaks, "2026-01-01", window_min=60)
    assert list(out["join_status"]) == ["exact", "ambiguous"]
    assert "close_key" in out.columns
    assert out["close_key"].nunique() == len(out)
    assert out.iloc[0]["peak_price"] == 100.0
    assert pd.isna(out.iloc[1]["peak_price"])


def test_date_scoping_filters_daily_rows():
    evt = pd.DataFrame(
        [
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:01:00Z")},
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-02T00:01:00Z")},
        ]
    )
    feed = pd.DataFrame(
        [
            {"ts": pd.Timestamp("2026-01-01T00:00:00Z"), "delta": 1.0},
            {"ts": pd.Timestamp("2026-01-02T00:00:00Z"), "delta": 2.0},
        ]
    )
    evt_scoped = _filter_df_by_date(evt, "event_ts", "2026-01-01")
    feed_scoped = _filter_df_by_date(feed, "ts", "2026-01-01")
    assert len(evt_scoped) == 1
    assert len(feed_scoped) == 1
    assert evt_scoped.iloc[0]["event_ts"].strftime("%Y-%m-%d") == "2026-01-01"
    assert feed_scoped.iloc[0]["ts"].strftime("%Y-%m-%d") == "2026-01-01"


def test_close_dedup_state_and_log_duplicate():
    duplicate = {
        "ts": "2026-01-01T00:30:00Z",
        "side": "LONG",
        "mode": "paper",
        "reason": "TP1",
        "close_price": 102.0,
        "entry": 100.0,
        "sl": 99.0,
        "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long", "price": 100.0},
    }
    events = [duplicate, dict(duplicate), {**duplicate, "ts": "2026-01-02T00:30:00Z"}]
    daily = _filter_close_events_by_date(events, "2026-01-01")
    deduped = _dedupe_close_events(daily)
    assert len(daily) == 2
    assert len(deduped) == 1


def test_close_date_filter_with_no_peak_rows_does_not_crash(tmp_path):
    archive = tmp_path / "empty.jsonl"
    archive.write_text("", encoding="utf-8")
    peaks = _load_peak_events(archive)

    scoped = _filter_close_df_by_date(peaks, "event_ts", "2026-01-01")
    assert scoped.empty
    assert str(scoped["event_ts"].dtype) == "datetime64[ns, UTC]"


def test_close_dedup_log_and_state_same_close_with_shape_differences():
    log_evt = {
        "ts": "2026-01-01T00:30:00.987Z",
        "side": "LONG",
        "mode": "paper",
        "reason": "tp1",
        "close_price": 102,
        "entry": "100.000000",
        "sl": 99.0,
        "src_evt": {"ts": "2026-01-01T00:10:00.200Z", "kind": "LONG", "price": 100.0},
    }
    state_evt = {
        "closed_at": "2026-01-01T00:30:00Z",
        "side": " long ",
        "mode": "PAPER",
        "close_reason": "TP1",
        "close_price": "102.0",
        "entry": 100,
        "sl": "99",
        "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long"},
    }
    deduped = _dedupe_close_events([log_evt, state_evt])
    assert len(deduped) == 1


def test_close_dedup_log_and_state_one_second_timestamp_skew():
    log_evt = {
        "ts": "2026-01-01T00:30:01Z",
        "side": "LONG",
        "mode": "paper",
        "reason": "TP1",
        "close_price": 102.0,
        "entry": 100.0,
        "sl": 99.0,
        "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long"},
    }
    state_evt = {
        "closed_at": "2026-01-01T00:30:00Z",
        "side": "LONG",
        "mode": "paper",
        "close_reason": "TP1",
        "close_price": 102.0,
        "entry": 100.0,
        "sl": 99.0,
        "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long"},
    }
    deduped = _dedupe_close_events([log_evt, state_evt])
    assert len(deduped) == 1


def test_trade_outcomes_primary_and_last_closed_flatten(tmp_path):
    trade_outcomes = tmp_path / "trade_outcomes.jsonl"
    trade_outcomes.write_text(
        "\n".join(
            [
                '{"schema":2,"event":"EXEC_CLOSE","ts":"2026-01-01T00:31:00Z","symbol":"BTCUSDC","source":"executor","last_closed":{"ts":"2026-01-01T00:30:00Z","mode":"paper","reason":"TP1","side":"LONG","qty":0.01,"entry":100.0,"entry_ref":100.2,"entry_actual":100.1,"opened_at":"2026-01-01T00:05:00Z","sl":99.0,"close_price":102.0,"trade_key":"TK-1","order_id":999,"order_id_sl":111,"order_id_tp1":222,"order_id_tp2":333,"qty1":0.003,"qty2":0.003,"qty3":0.004,"tp1_done":true,"tp2_done":false,"sl_done":false,"trail_active":true,"trail_sl_price":99.5,"prices":{"entry":100.0,"sl":99.0},"src_evt":{"ts":"2026-01-01T00:10:00Z","kind":"long","price":100.0}}}',
                '{"schema":2,"event":"EXEC_CLOSE","ts":"2026-01-01T01:31:00Z","symbol":"BTCUSDC","source":"executor","last_closed":{"ts":"2026-01-01T01:30:00Z","mode":"paper","reason":"SL","side":"SHORT","entry":105.0,"sl":106.0,"close_price":106.0,"trade_key":"TK-2"}}',
            ]
        ),
        encoding="utf-8",
    )
    exec_log = tmp_path / "executor.log"
    exec_log.write_text('{"action":"CLOSE","ts":"2026-01-01T05:00:00Z","reason":"LEGACY"}\n', encoding="utf-8")
    state_file = tmp_path / "executor_state.json"
    state_file.write_text('{"last_closed":{"ts":"2026-01-01T05:10:00Z","reason":"LEGACY_STATE"}}', encoding="utf-8")

    loaded = _load_trade_outcomes_events(trade_outcomes)
    assert len(loaded) == 2
    assert loaded[0]["schema"] == 2
    assert loaded[0]["event"] == "EXEC_CLOSE"
    assert loaded[0]["record_ts"] == "2026-01-01T00:31:00Z"
    assert loaded[0]["lc_trade_key"] == "TK-1"
    assert loaded[0]["lc_entry_actual"] == 100.1
    assert loaded[0]["lc_order_id_tp1"] == 222
    assert loaded[0]["lc_qty3"] == 0.004
    assert loaded[0]["lc_order_id_sl"] == 111
    assert loaded[0]["lc_tp1_done"] is True
    assert loaded[0]["lc_trail_active"] is True
    assert loaded[0]["lc_prices_entry"] == 100.0

    peaks = pd.DataFrame(
        [{"event_ts": pd.Timestamp("2026-01-01T00:10:00Z"), "kind": "long", "price": 100.0, "delta": 1.0, "imb": 0.6, "vol": 10.0, "seq": 1}]
    )
    out = derive_close_outcomes(loaded, peaks, "2026-01-01", window_min=60)
    assert "schema" in out.columns
    assert "event" in out.columns
    assert "record_ts" in out.columns
    assert "symbol" in out.columns
    assert "source" in out.columns
    assert "lc_trade_key" in out.columns
    assert "lc_entry_actual" in out.columns
    assert "lc_order_id_tp1" in out.columns
    assert "lc_qty3" in out.columns
    assert "lc_order_id_sl" in out.columns
    assert "lc_tp1_done" in out.columns
    assert "lc_trail_active" in out.columns
    assert "lc_prices_entry" in out.columns

    primary = _load_close_events(exec_log, state_file, trade_outcomes, "2026-01-01")
    assert len(primary) == 2
    assert all(evt.get("event") == "EXEC_CLOSE" for evt in primary)


def test_trade_outcomes_date_aware_fallback_to_legacy(tmp_path):
    trade_outcomes = tmp_path / "trade_outcomes.jsonl"
    trade_outcomes.write_text(
        '{"schema":2,"event":"EXEC_CLOSE","ts":"2026-01-02T00:31:00Z","symbol":"BTCUSDC","source":"executor","last_closed":{"ts":"2026-01-02T00:30:00Z","mode":"paper","reason":"TP1"}}\n',
        encoding="utf-8",
    )
    exec_log = tmp_path / "executor.log"
    exec_log.write_text('{"action":"CLOSE","ts":"2026-01-01T05:00:00Z","reason":"LEGACY"}\n', encoding="utf-8")
    state_file = tmp_path / "executor_state.json"
    state_file.write_text('{"last_closed":{"ts":"2026-01-01T05:10:00Z","reason":"LEGACY_STATE"}}', encoding="utf-8")

    primary = _load_close_events(exec_log, state_file, trade_outcomes, "2026-01-01")
    assert len(primary) == 2
    assert all(evt.get("event") != "EXEC_CLOSE" for evt in primary)


def test_trade_outcomes_dedupe_prefers_trade_key_identity():
    e1 = {
        "ts": "2026-01-01T00:30:00Z",
        "side": "LONG",
        "reason": "TP1",
        "symbol": "BTCUSDC",
        "lc_trade_key": "TK-777",
        "close_price": 102.0,
        "entry": 100.0,
        "sl": 99.0,
    }
    e2 = {
        "ts": "2026-01-01T00:30:01Z",
        "side": "LONG",
        "reason": "TP1",
        "symbol": "BTCUSDC",
        "lc_trade_key": "TK-777",
        "close_price": 102.1,
        "entry": 100.0,
        "sl": 99.0,
    }
    deduped = _dedupe_close_events([e1, e2])
    assert len(deduped) == 1
