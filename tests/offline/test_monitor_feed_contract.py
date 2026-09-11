import hashlib
import json

import pandas as pd
import pytest

from deltascout.research_bundle.monitor_feed_contract import (
    MonitorContractError, RECOVERY_LINEAGE, build_data_snapshot, closed_bars,
    load_shi_prefix,
)


def source(start="2026-07-25T00:01Z", count=1500):
    return pd.DataFrame({"Timestamp": pd.date_range(start, periods=count, freq="min"),
                         "Open": 100., "High": 102., "Low": 99., "Close": 101.,
                         "Volume": 10., "AggTrades": 20, "BuyQty": 7., "SellQty": 3.,
                         "OpenInterest": 200., "FundingRate": .0001,
                         "LiqBuyQty": 0., "LiqSellQty": 0., "IsSynthetic": 0})


def write_days(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    for day, group in rows.groupby(rows.Timestamp.dt.strftime("%Y-%m-%d")):
        group.to_csv(root / f"{day}.csv", index=False)


def snapshot(root, cutoff="2026-07-26T00:26Z"):
    frame, manifest = load_shi_prefix(root, cutoff, history_minutes=1440)
    return build_data_snapshot(frame, cutoff), manifest


def test_midnight_windows_are_elapsed_time_not_current_file(tmp_path):
    write_days(tmp_path, source())
    result, _ = snapshot(tmp_path)
    assert result["local_window_readiness"] == "READY"
    assert {w: x["rows_present"] for w, x in result["windows"].items()} == {
        "5": 5, "15": 15, "30": 30, "60": 60, "240": 240, "1440": 1440}
    assert result["windows"]["240"]["metrics"]["delta_fraction"] == .4
    assert result["live_decision_eligible"] is False


def test_future_synthetic_and_invalid_values_cannot_change_prefix(tmp_path):
    rows = source(); write_days(tmp_path, rows)
    before, manifest1 = snapshot(tmp_path)
    rows.loc[rows.Timestamp > pd.Timestamp("2026-07-26T00:26Z"), ["IsSynthetic", "Close"]] = [1, -10]
    write_days(tmp_path, rows)
    after, manifest2 = snapshot(tmp_path)
    assert before == after
    assert manifest1["source_files"] != manifest2["source_files"]


def test_gap_is_not_filled_with_older_observations(tmp_path):
    rows = source(); rows = rows.drop(rows[rows.Timestamp == pd.Timestamp("2026-07-26T00:01Z")].index)
    write_days(tmp_path, rows)
    result, _ = snapshot(tmp_path)
    assert result["windows"]["60"]["missing_minutes"] == 1
    assert result["windows"]["60"]["metrics"] is None
    assert "60m:MISSING_MINUTES" in result["gaps"]


def test_synthetic_tail_does_not_reset_age_of_last_real_price(tmp_path):
    rows = source(); rows.loc[rows.Timestamp > pd.Timestamp("2026-07-26T00:20Z"), "IsSynthetic"] = 1
    write_days(tmp_path, rows)
    result, _ = snapshot(tmp_path)
    assert result["source_label_age_seconds"] == 360
    assert "STALE_OR_MISSING_USABLE_FEED" in result["gaps"]
    assert result["windows"]["5"]["status"] == "UNUSABLE"


def test_optional_absence_is_null_and_propagates_to_readiness(tmp_path):
    write_days(tmp_path, source().drop(columns=["LiqBuyQty", "OpenInterest"]))
    result, _ = snapshot(tmp_path)
    w = result["windows"]["60"]
    assert w["metrics"]["LiqBuyQty"] is None
    assert w["metrics"]["LiqSellQty"] == 0
    assert w["metrics"]["OpenInterest"] is None
    assert w["status"] == "PARTIAL"
    assert "60m:UNSUPPORTED_LiqBuyQty" in result["gaps"]
    assert result["local_window_readiness"] == "PARTIAL"


def test_utc_cutoff_must_be_explicit_but_shi_source_naive_is_utc(tmp_path):
    rows = source(); rows.Timestamp = rows.Timestamp.dt.tz_localize(None)
    write_days(tmp_path, rows)
    with pytest.raises(MonitorContractError, match="timezone"):
        load_shi_prefix(tmp_path, "2026-07-26 00:26:00")
    result, _ = snapshot(tmp_path)
    assert result["windows"]["60"]["rows_present"] == 60


def test_empty_missing_files_are_unusable_not_zero_evidence(tmp_path):
    result, _ = snapshot(tmp_path)
    assert result["local_window_readiness"] == "UNUSABLE"
    assert result["source_label_age_seconds"] is None
    assert result["windows"]["60"]["metrics"] is None


def test_duplicate_close_label_fails_instead_of_silent_keeplast(tmp_path):
    rows = source(); write_days(tmp_path, pd.concat([rows, rows.iloc[[30]]]))
    with pytest.raises(MonitorContractError, match="Duplicate close"):
        snapshot(tmp_path)


@pytest.mark.parametrize("field,value", [("Close", float("inf")), ("BuyQty", 30), ("Low", 200), ("Volume", -1)])
def test_bad_required_evidence_cannot_become_ready(tmp_path, field, value):
    rows = source(); rows.loc[rows.Timestamp == pd.Timestamp("2026-07-26T00:26Z"), field] = value
    write_days(tmp_path, rows)
    result, _ = snapshot(tmp_path)
    assert result["windows"]["60"]["metrics"] is None
    assert "60m:UNUSABLE_ROWS" in result["gaps"]


def test_closed_h1_uses_0001_through_0100_and_never_partial_0101(tmp_path):
    rows = source("2026-07-25T00:01Z", count=61)
    rows.loc[60, ["High", "Close"]] = [300, 200]
    write_days(tmp_path, rows)
    frame, _ = load_shi_prefix(tmp_path, "2026-07-25T01:01Z", history_minutes=1440)
    assert closed_bars(frame, "2026-07-25T00:59Z", 60) == []
    bars = closed_bars(frame, "2026-07-25T01:01Z", 60)
    assert len(bars) == 1
    assert bars[0]["close_utc"] == "2026-07-25T01:00:00+00:00"
    assert bars[0]["high"] == 102
    assert bars[0]["available_no_earlier_than_utc"] == bars[0]["close_utc"]


def test_missing_minute_cannot_confirm_complete_h1(tmp_path):
    write_days(tmp_path, source("2026-07-25T00:01Z", 60).drop(index=20))
    frame, _ = load_shi_prefix(tmp_path, "2026-07-25T01:00Z", history_minutes=1440)
    assert closed_bars(frame, "2026-07-25T01:00Z", 60) == []


def test_recovery_is_fail_closed_without_frozen_clock_lineage(tmp_path):
    write_days(tmp_path, source("2026-05-04T00:01Z"))
    result, _ = snapshot(tmp_path, "2026-05-05T00:26Z")
    assert result["local_window_readiness"] == "UNUSABLE"


def test_corrected_recovery_requires_matching_output_hash_and_nullable_enrichment(tmp_path):
    rows = source("2026-05-04T00:01Z", count=60); feed = tmp_path / "feed"; write_days(feed, rows)
    quality = rows[["Timestamp"]].copy()
    for name, value in {"RecoveryClass": "PRICE_VOLUME_OI_RECOVERED", "RecoveredClose": 101,
                        "PriceSource": "legacy_volume_alert_archive", "OiSource": "shi_rest_same_ts",
                        "FundingSource": "untrusted", "LiqSource": "missing"}.items():
        quality[name] = value
    sidecar = tmp_path / "quality.csv"; quality.to_csv(sidecar, index=False)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "RECOVERY_CLOCK_V2", "outputs": [
        {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in [sidecar, feed / "2026-05-04.csv"]]}))
    kwargs = dict(history_minutes=1440, recovery_quality=sidecar, recovery_lineage=RECOVERY_LINEAGE, recovery_manifest=manifest)
    frame, _ = load_shi_prefix(feed, "2026-05-04T01:00Z", **kwargs)
    result = build_data_snapshot(frame, "2026-05-04T01:00Z")
    window = result["windows"]["60"]
    assert window["status"] == "PARTIAL" and window["metrics"]["volume_btc"] == 600
    assert window["metrics"]["OpenInterest"] is None
    assert window["metrics"]["LiqBuyQty"] is None
    rows.loc[0, "Close"] = 102; write_days(feed, rows)
    with pytest.raises(MonitorContractError, match="not a frozen"):
        load_shi_prefix(feed, "2026-05-04T01:00Z", **kwargs)


def test_subminute_cutoff_does_not_include_next_flush(tmp_path):
    write_days(tmp_path, source())
    result, _ = snapshot(tmp_path, "2026-07-26T00:26:30Z")
    assert result["windows"]["60"]["rows_present"] == 60
    assert result["source_label_age_seconds"] == 30
