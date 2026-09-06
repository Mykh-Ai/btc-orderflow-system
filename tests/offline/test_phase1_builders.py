from __future__ import annotations

import pandas as pd
import pytest

from scripts.offline.build_close_outcomes import (
    _filter_df_by_date as _filter_close_df_by_date,
    _dedupe_close_events,
    _filter_close_events_by_date,
    _load_close_events,
    _load_manual_close_overrides,
    _load_trade_outcomes_events,
    _merge_manual_close_overrides,
    _load_peak_events,
    derive_close_outcomes,
)
from scripts.offline.build_phase1_derived import _filter_df_by_date, derive_reject_dataset, resolve_feed_file, run
from scripts.offline.common import OfflineBuildError, load_feed


def _read_output_dataset(path_base):
    parquet_path = path_base.with_suffix(".parquet")
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    return pd.read_csv(path_base.with_suffix(".csv"))


def test_reject_classification_soft_and_multi():
    df = pd.DataFrame(
        [
            {"event": "CANDIDATE_GATE_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:00:00Z"), "seq": 1, "reject_reason": "chop_coh", "kind": "long"},
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:01:00Z"), "seq": 2, "reject_reason": "vwap_distance", "kind": "short", "price": 1010, "vwap": 0, "vwap_max_dist_usd": 1000},
            {"event": "CANDIDATE_GATE_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:02:00Z"), "seq": 3, "reject_reason": "imb_band", "kind": "long", "imb": 0.651, "imb_min": 0.55, "imb_max": 0.65},
            {"event": "CANDIDATE_COMPARISON_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:03:00Z"), "seq": 4, "reject_reason": "direction_mismatch", "kind": "long"},
            {"event": "PEAK_LOSS_FILTER_REJECT", "event_ts": pd.Timestamp("2026-01-01T00:04:00Z"), "seq": 5, "reject_reason": "loss_avoidance_union", "kind": "short"},
        ]
    )

    out = derive_reject_dataset(df, "2026-01-01", soft_vwap_margin=20.0, soft_imb_margin=0.01)
    classes = dict(zip(out["seq"], out["reject_class"]))
    assert classes[1] == "multi_condition"
    assert classes[2] == "soft_fail"
    assert classes[3] == "soft_fail"
    assert classes[4] == "single_condition"
    assert classes[5] == "policy_filter"


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


def test_load_feed_accepts_canonical_enriched_schema_and_sorts_rows(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty",
                "2026-01-02T00:01:00Z,100,101,8,3,12345,0.0001,7,8",
                "2026-01-02T00:00:00Z,99,100,5,1,12344,0.0002,1,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = load_feed(feed)

    assert list(out["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")) == ["2026-01-02T00:00:00Z", "2026-01-02T00:01:00Z"]
    assert list(out["delta"]) == [4, 5]
    assert list(out["price"]) == [100, 101]


def test_load_feed_accepts_core_columns_only_and_closeprice_fallbacks_to_avgprice(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty",
                "2026-01-02T00:00:00Z,100,,5,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = load_feed(feed)

    assert len(out) == 1
    assert out.iloc[0]["delta"] == 3
    assert out.iloc[0]["price"] == 100


def test_load_feed_fails_loudly_on_invalid_timestamp(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty",
                "not-a-ts,100,101,5,2,12345,0.0001,7,8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OfflineBuildError, match="invalid Timestamp"):
        load_feed(feed)


def test_load_feed_fails_loudly_on_invalid_required_numeric_fields(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty",
                "2026-01-02T00:00:00Z,100,101,not-a-number,2,12345,0.0001,7,8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OfflineBuildError, match="invalid BuyQty/SellQty"):
        load_feed(feed)


def test_load_feed_fails_loudly_when_closeprice_and_avgprice_are_both_invalid(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty",
                "2026-01-02T00:00:00Z,,,5,2,12345,0.0001,7,8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OfflineBuildError, match="invalid ClosePrice/AvgPrice"):
        load_feed(feed)


def test_resolve_feed_file_priority_order(tmp_path):
    input_root = tmp_path / "input"
    explicit_file = tmp_path / "explicit.csv"
    external_root = tmp_path / "external"

    resolved = resolve_feed_file(
        date="2026-01-02",
        input_root=input_root,
        feed_root=str(external_root),
        feed_file=str(explicit_file),
    )

    assert resolved == explicit_file


def test_resolve_feed_file_uses_explicit_feed_root_when_feed_file_missing(tmp_path):
    input_root = tmp_path / "input"
    external_root = tmp_path / "external"

    resolved = resolve_feed_file(
        date="2026-01-02",
        input_root=input_root,
        feed_root=str(external_root),
        feed_file=None,
    )

    assert resolved == external_root / "2026-01-02.csv"


def test_resolve_feed_file_defaults_to_self_contained_input_root(tmp_path):
    input_root = tmp_path / "input"

    resolved = resolve_feed_file(
        date="2026-01-02",
        input_root=input_root,
        feed_root=None,
        feed_file=None,
    )

    assert resolved == input_root / "feed" / "2026-01-02.csv"


def test_enriched_feed_normalization_preserves_late_peak_behavior(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty",
                "2026-01-02T00:02:00Z,102,102,6,1,12347,0.0001,7,8",
                "2026-01-02T00:00:00Z,100,100,5,1,12345,0.0001,7,8",
                "2026-01-02T00:01:00Z,98,98,4,1,12346,0.0001,7,8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    df_feed = load_feed(feed)
    peaks = pd.DataFrame(
        [
            {"event": "PEAK_EMIT", "event_ts": pd.Timestamp("2026-01-02T00:02:00Z"), "kind": "long", "price": 102.0, "seq": 1},
        ]
    )

    from scripts.offline.build_phase1_derived import derive_late_peak

    out = derive_late_peak(df_feed, peaks, "2026-01-02", lookback_rows=3)

    assert len(out) == 1
    assert out.iloc[0]["move_start_ts"] == pd.Timestamp("2026-01-02T00:01:00Z")
    assert out.iloc[0]["latency_min"] == 1.0
    assert out.iloc[0]["move_size"] == 4.0


def test_run_uses_self_contained_feed_by_default_and_preserves_output_parity(tmp_path):
    input_root = tmp_path / "data"
    archive_dir = input_root / "archive" / "deltascout"
    feed_dir = input_root / "feed"
    output_root = tmp_path / "out"
    archive_dir.mkdir(parents=True)
    feed_dir.mkdir(parents=True)

    (archive_dir / "2026-01-02.jsonl").write_text(
        "\n".join(
            [
                '{"event":"DELTA_MAX","ts":"2026-01-02T00:02:00Z","seq":1,"delta":5,"price":102}',
                '{"event":"PEAK_EMIT","ts":"2026-01-02T00:02:00Z","seq":2,"kind":"long","price":102}',
                '{"event":"CANDIDATE_COMPARISON_REJECT","ts":"2026-01-02T00:03:00Z","seq":3,"kind":"long","reject_reason":"no_prev_peak"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (feed_dir / "2026-01-02.csv").write_text(
        "\n".join(
            [
                "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty",
                "2026-01-02T00:02:00Z,102,102,6,1",
                "2026-01-02T00:00:00Z,100,100,5,1",
                "2026-01-02T00:01:00Z,98,98,4,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    run(
        type(
            "Args",
            (),
            {
                "date": "2026-01-02",
                "input_root": str(input_root),
                "output_root": str(output_root),
                "feed_root": None,
                "feed_file": None,
                "roll_window": 3,
                "owner_quantile": 0.75,
                "late_lookback_rows": 3,
                "soft_vwap_margin": 50.0,
                "soft_imb_margin": 0.01,
            },
        )()
    )

    baseline = _read_output_dataset(output_root / "baseline_init_2026-01-02")
    late_peak = _read_output_dataset(output_root / "late_peak_2026-01-02")

    assert baseline["reject_reason"].tolist() == ["no_prev_peak"]
    assert late_peak.loc[0, "move_start_ts"] == "2026-01-02 00:01:00+00:00"
    assert late_peak.loc[0, "latency_min"] == 1.0


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


def test_close_outcomes_derives_tp1_then_sl_lifecycle_state():
    peaks = pd.DataFrame(
        [
            {"event_ts": pd.Timestamp("2026-01-01T00:10:00Z"), "kind": "long", "price": 100.0, "delta": 1.0, "imb": 0.6, "vol": 10.0, "seq": 1},
        ]
    )
    close_events = [
        {
            "ts": "2026-01-01T00:30:00Z",
            "side": "LONG",
            "mode": "paper",
            "reason": "SL",
            "entry": 100.5,
            "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "long"},
            "lc_tp1_done": True,
            "lc_tp2_done": False,
            "lc_sl_done": True,
            "lc_trail_active": False,
        }
    ]
    out = derive_close_outcomes(close_events, peaks, "2026-01-01", window_min=4320)
    assert out.iloc[0]["trade_lifecycle_state"] == "tp1_then_sl"


def test_close_outcomes_derives_tp1_tp2_then_trailing_stop_lifecycle_state():
    peaks = pd.DataFrame(
        [
            {"event_ts": pd.Timestamp("2026-01-01T00:10:00Z"), "kind": "long", "price": 100.0, "delta": 1.0, "imb": 0.6, "vol": 10.0, "seq": 1},
        ]
    )
    close_events = [
        {
            "ts": "2026-01-02T00:30:00Z",
            "side": "LONG",
            "mode": "paper",
            "reason": "SL",
            "entry": 100.5,
            "lc_opened_at": "2026-01-01T00:05:00Z",
            "lc_tp1_done": True,
            "lc_tp2_done": True,
            "lc_sl_done": True,
            "lc_trail_active": True,
            "lc_trail_sl_price": 105.0,
        }
    ]
    out = derive_close_outcomes(close_events, peaks, "2026-01-02", window_min=4320)
    assert out.iloc[0]["join_status"] == "window_match"
    assert out.iloc[0]["peak_ts"] == pd.Timestamp("2026-01-01T00:10:00Z")
    assert out.iloc[0]["trade_lifecycle_state"] == "tp1_tp2_then_trailing_stop"


def test_close_outcomes_derives_plain_sl_lifecycle_state():
    peaks = pd.DataFrame(
        [
            {"event_ts": pd.Timestamp("2026-01-01T00:10:00Z"), "kind": "short", "price": 100.0, "delta": -1.0, "imb": 0.6, "vol": 10.0, "seq": 1},
        ]
    )
    close_events = [
        {
            "ts": "2026-01-01T00:30:00Z",
            "side": "SHORT",
            "mode": "paper",
            "reason": "SL",
            "entry": 99.5,
            "src_evt": {"ts": "2026-01-01T00:10:00Z", "kind": "short"},
            "lc_tp1_done": False,
            "lc_tp2_done": False,
            "lc_sl_done": True,
            "lc_trail_active": False,
        }
    ]
    out = derive_close_outcomes(close_events, peaks, "2026-01-01", window_min=4320)
    assert out.iloc[0]["trade_lifecycle_state"] == "plain_sl"


def test_manual_close_overrides_append_missing_peak_close(tmp_path):
    overrides = tmp_path / "manual_close_overrides.jsonl"
    overrides.write_text(
        '\n'.join(
            [
                '{"source_date":"2026-04-05","peak_ts":"2026-04-05T14:34:00Z","peak_kind":"short","close_reason":"SL","side":"SHORT","entry":66774.628139,"sl":67121.0,"source":"manual_user_confirmed"}',
                '{"source_date":"2026-04-06","peak_ts":"2026-04-06T00:00:00Z","peak_kind":"long","close_reason":"TP1"}',
            ]
        )
        + '\n',
        encoding='utf-8',
    )

    loaded = _load_manual_close_overrides(overrides, '2026-04-05')
    assert len(loaded) == 1
    assert loaded[0]['peak_kind'] == 'short'

    close_df = pd.DataFrame(
        [
            {
                'close_key': 'existing',
                'source_date': '2026-04-05',
                'close_ts': '2026-04-05T01:00:00Z',
                'join_status': 'missing',
                'peak_ts': '',
                'peak_kind': '',
                'close_reason': 'SL',
            }
        ]
    )
    merged = _merge_manual_close_overrides(close_df, loaded, '2026-04-05')

    assert len(merged) == 2
    manual_row = merged[merged['source'] == 'manual_user_confirmed'].iloc[0]
    assert manual_row['peak_ts'] == '2026-04-05T14:34:00Z'
    assert manual_row['peak_kind'] == 'short'
    assert manual_row['close_reason'] == 'SL'
    assert manual_row['join_status'] == 'manual_override'


def test_manual_close_overrides_do_not_duplicate_existing_exact_peak_match():
    close_df = pd.DataFrame(
        [
            {
                'close_key': 'existing',
                'source_date': '2026-04-05',
                'close_ts': '2026-04-05T15:00:00Z',
                'join_status': 'window_match',
                'peak_ts': '2026-04-05T14:34:00Z',
                'peak_kind': 'short',
                'close_reason': 'SL',
            }
        ]
    )
    merged = _merge_manual_close_overrides(
        close_df,
        [
            {
                'source_date': '2026-04-05',
                'peak_ts': '2026-04-05T14:34:00Z',
                'peak_kind': 'short',
                'close_reason': 'SL',
                'source': 'manual_user_confirmed',
            }
        ],
        '2026-04-05',
    )

    assert len(merged) == 1
