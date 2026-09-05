from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from executor import executor


def _frame(*, lows: list[float], highs: list[float], volumes: list[float]) -> pd.DataFrame:
    assert len(lows) == len(highs) == len(volumes)
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=len(lows), freq="min")
    return pd.DataFrame(
        {
            "Timestamp": timestamps,
            "price": [(low + high) / 2 for low, high in zip(lows, highs)],
            "close_usdt": [(low + high) / 2 for low, high in zip(lows, highs)],
            "low_usdt": lows,
            "high_usdt": highs,
            "volume_1m": volumes,
            "swing_row_real": [True] * len(lows),
        }
    )


@pytest.fixture
def v8_env(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "INITIAL_STOP_POLICY": "VOLUME_SWING_24H_LR25",
        "INITIAL_SWING_LOOKBACK": 7,
        "INITIAL_SWING_LR": 1,
        "INITIAL_SWING_BUFFER_USD": 0.5,
        "INITIAL_SWING_MAX_DISTANCE_USD": 5.0,
        "INITIAL_SWING_REQUIRE_FULL_WINDOW": True,
        "SL_PCT": 0.002,
        "TICK_SIZE": executor.Decimal("0.01"),
    }
    for key, value in values.items():
        monkeypatch.setitem(executor.ENV, key, value)


def test_v8_initial_stop_selects_highest_volume_swing_inside_cap(v8_env: None) -> None:
    frame = _frame(
        lows=[99, 90, 96, 99, 98, 99, 99.5],
        highs=[101, 100, 101, 101, 100, 101, 101],
        volumes=[10, 500, 10, 10, 200, 10, 10],
    )

    selected = executor.select_volume_confirmed_initial_stop(frame, 6, "BUY", 100.5)

    assert selected.swing_price_usdt == 98
    assert selected.swing_volume == 200
    assert selected.stop_usdt == 97.5
    assert selected.confirmed_count == 2
    assert selected.eligible_count == 1


def test_v8_initial_stop_short_uses_high_plus_buffer(v8_env: None) -> None:
    frame = _frame(
        lows=[99, 99, 99, 98, 99, 98, 98],
        highs=[101, 110, 104, 101, 102, 101, 100.5],
        volumes=[10, 500, 10, 10, 200, 10, 10],
    )

    selected = executor.select_volume_confirmed_initial_stop(frame, 6, "SELL", 99.5)

    assert selected.swing_price_usdt == 102
    assert selected.swing_volume == 200
    assert selected.stop_usdt == 102.5
    assert selected.confirmed_count == 2
    assert selected.eligible_count == 1


def test_v8_initial_stop_preserves_far_stop_floor(
    v8_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(executor.ENV, "INITIAL_SWING_BUFFER_USD", 0.0)

    assert executor._initial_stop_from_swing_usdt("BUY", 100.5, 100.4) == 100.29
    assert executor._initial_stop_from_swing_usdt("SELL", 99.5, 99.6) == 99.7


def test_v8_initial_stop_breaks_equal_volume_tie_toward_newer_swing(v8_env: None) -> None:
    frame = _frame(
        lows=[99, 98, 99, 99, 97.5, 99, 99.5],
        highs=[101, 100, 101, 101, 100, 101, 101],
        volumes=[10, 200, 10, 10, 200, 10, 10],
    )

    selected = executor.select_volume_confirmed_initial_stop(frame, 6, "BUY", 100.5)

    assert selected.swing_price_usdt == 97.5
    assert selected.swing_ts == datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc)


def test_v8_initial_stop_rejects_incomplete_window_and_audits_gaps(v8_env: None) -> None:
    short = _frame(
        lows=[99, 98, 99, 98, 99, 99],
        highs=[101, 100, 101, 100, 101, 101],
        volumes=[10] * 6,
    )
    with pytest.raises(executor.InitialStopSelectionError, match="NO_FULL_INITIAL_SWING_WINDOW"):
        executor.select_volume_confirmed_initial_stop(short, 5, "BUY", 100.5)

    gapped = _frame(
        lows=[99, 98, 99, 99, 98, 99, 99.5],
        highs=[101, 100, 101, 101, 100, 101, 101],
        volumes=[10] * 7,
    )
    gapped.loc[4, "Timestamp"] = gapped.loc[4, "Timestamp"] + pd.Timedelta(minutes=1)
    selected = executor.select_volume_confirmed_initial_stop(gapped, 6, "BUY", 100.5)
    assert selected.window_gap_count == 2


def test_v8_initial_stop_rejects_untrusted_swing_neighborhood(v8_env: None) -> None:
    frame = _frame(
        lows=[99, 98, 99, 99, 97.5, 99, 99.5],
        highs=[101, 100, 101, 101, 100, 101, 101],
        volumes=[10, 100, 10, 10, 200, 10, 10],
    )
    frame.loc[3, "swing_row_real"] = False

    selected = executor.select_volume_confirmed_initial_stop(frame, 6, "BUY", 100.5)

    assert selected.swing_price_usdt == 98
    assert selected.swing_volume == 100


def test_usdt_usdc_stop_conversion_is_directional(v8_env: None) -> None:
    assert executor.convert_stop_usdt_to_usdc(99.0, "LONG", 1.001) == 99.09
    assert executor.convert_stop_usdt_to_usdc(101.0, "SHORT", 1.001) == 101.11


def test_quote_snapshot_uses_current_btcusdc_to_btcusdt_ratio(
    v8_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mids = {"BTCUSDT": 100_000.0, "BTCUSDC": 100_100.0}
    monkeypatch.setattr(executor, "get_mid_price", lambda symbol: mids[symbol])

    snapshot = executor.get_usdt_usdc_quote_snapshot()

    assert snapshot.mid_usdt == 100_000.0
    assert snapshot.mid_usdc == 100_100.0
    assert snapshot.ratio == pytest.approx(1.001)


def test_trailing_quote_converts_usdt_swing_and_checks_usdc_mid(
    v8_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = executor.UsdtUsdcQuoteSnapshot(
        mid_usdt=100.0,
        mid_usdc=100.1,
        ratio=1.001,
        observed_at_utc="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(executor, "_trail_desired_stop_from_agg_usdt", lambda pos: 99.0)
    monkeypatch.setattr(executor, "get_usdt_usdc_quote_snapshot", lambda: snapshot)

    quote = executor._trail_stop_quote_from_agg({"side": "LONG"})

    assert quote is not None
    assert quote.stop_usdt == 99.0
    assert quote.stop_usdc == 99.09
    assert quote.snapshot.ratio == pytest.approx(1.001)


def test_trailing_quote_rejects_stop_already_crossed_on_usdc(
    v8_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = executor.UsdtUsdcQuoteSnapshot(
        mid_usdt=100.0,
        mid_usdc=99.0,
        ratio=0.99,
        observed_at_utc="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(executor, "_trail_desired_stop_from_agg_usdt", lambda pos: 100.0)
    monkeypatch.setattr(executor, "get_usdt_usdc_quote_snapshot", lambda: snapshot)

    with pytest.raises(executor.QuoteSyncError, match="not below BTCUSDC mid"):
        executor._trail_stop_quote_from_agg({"side": "LONG"})


def test_vps_market_loader_preserves_v8_trust_columns(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "aggregated.csv"
    pd.DataFrame(
        {
            "Timestamp": pd.date_range("2026-01-01", periods=3, freq="min"),
            "Trades": [10, 0, 12],
            "TotalQty": [4.0, 5.0, 6.0],
            "AvgSize": [0.4, 0.5, 0.5],
            "BuyQty": [2.0, 2.0, 3.0],
            "SellQty": [2.0, 3.0, 3.0],
            "AvgPrice": [100.0, 101.0, 102.0],
            "ClosePrice": [100.0, 101.0, 102.0],
            "HiPrice": [101.0, 102.0, 103.0],
            "LowPrice": [99.0, 100.0, 101.0],
        }
    ).to_csv(csv_path, index=False)
    monkeypatch.setitem(executor.ENV, "AGG_CSV", str(csv_path))

    loaded = executor.load_df_sorted()

    assert {"close_usdt", "high_usdt", "low_usdt", "volume_1m", "swing_row_real"} <= set(loaded.columns)
    assert loaded["swing_row_real"].tolist() == [True, False, True]
    assert executor.locate_index_by_ts(loaded, datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)) == 1
    assert executor.locate_index_by_ts(loaded, datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)) == -1


def test_trailing_sync_failure_keeps_existing_protective_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"cancel": 0, "place": 0}

    monkeypatch.setattr(executor.binance_api, "open_orders", lambda symbol: [{"orderId": 123}])
    monkeypatch.setattr(executor.binance_api, "check_order_status", lambda symbol, order_id: {"status": "NEW"})
    monkeypatch.setattr(
        executor.binance_api,
        "cancel_order",
        lambda *args, **kwargs: calls.__setitem__("cancel", calls["cancel"] + 1),
    )
    monkeypatch.setattr(
        executor.binance_api,
        "place_order_raw",
        lambda *args, **kwargs: calls.__setitem__("place", calls["place"] + 1),
    )
    monkeypatch.setattr(
        executor,
        "_trail_stop_quote_from_agg",
        lambda pos: (_ for _ in ()).throw(executor.QuoteSyncError("snapshot failed")),
    )
    monkeypatch.setattr(executor, "save_state", lambda state: None)
    monkeypatch.setattr(executor, "log_event", lambda *args, **kwargs: None)

    state = {
        "position": {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 123, "tp1": 0, "tp2": 0},
            "prices": {"entry": 100.0, "sl": 99.0, "tp1": 101.0, "tp2": 102.0},
            "trail_active": True,
            "trail_last_update_s": 0.0,
            "trail_qty": 0.01,
        }
    }

    executor.manage_v15_position("BTCUSDC", state)

    assert state["position"]["orders"]["sl"] == 123
    assert calls == {"cancel": 0, "place": 0}
