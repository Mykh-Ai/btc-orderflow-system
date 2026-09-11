"""Offline data boundary for a future LLM monitor; never imports live execution.

SHI labels the flush at the end of accumulated time. These are UTC close labels,
not exchange kline open labels. Final CSVs do not prove arrival time at a decision.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


VERSION = "MONITOR_SHI_CLOSE_CONTRACT_V1"
GAP_START = pd.Timestamp("2026-04-23T17:05:00Z")
GAP_END = pd.Timestamp("2026-05-06T22:51:00Z")
RECOVERY_LINEAGE = "recovery_clock_v2_2026-09-08"
RENAME = {"Open": "OpenPrice", "High": "HiPrice", "Low": "LowPrice",
          "Close": "ClosePrice", "Volume": "TotalQty", "AggTrades": "Trades"}
PRICES = ["OpenPrice", "HiPrice", "LowPrice", "ClosePrice"]
FLOW = ["TotalQty", "Trades", "BuyQty", "SellQty"]
OPTIONAL = ["OpenInterest", "FundingRate", "LiqBuyQty", "LiqSellQty"]
WINDOWS = (5, 15, 30, 60, 240, 1440)


class MonitorContractError(ValueError):
    pass


def utc_cutoff(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None or pd.isna(ts):
        raise MonitorContractError("Decision cutoff must have an explicit timezone")
    return ts.tz_convert("UTC")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _iso(value: pd.Timestamp | None) -> str | None:
    return value.isoformat() if value is not None and pd.notna(value) else None


def _number(value: object) -> float | None:
    return float(value) if pd.notna(value) else None


def load_shi_prefix(
    root: str | Path,
    cutoff: str | pd.Timestamp,
    *,
    history_minutes: int = 30 * 1440,
    recovery_quality: str | Path | None = None,
    recovery_lineage: str | None = None,
    recovery_manifest: str | Path | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Read only dated files intersecting (cutoff-history, cutoff].

    Recovery acceptance requires the corrected lineage AND matching sidecar
    timestamp/price/source. The raw asset is never changed. Whole-file hashes
    belong to the manifest; the eligible-prefix hash belongs to the evidence.
    """
    end = utc_cutoff(cutoff)
    if history_minutes < max(WINDOWS):
        raise MonitorContractError("History must cover at least 1440 minutes")
    start = end - pd.Timedelta(minutes=history_minutes)
    root = Path(root)
    paths = [root / f"{day.date()}.csv" for day in pd.date_range(start.floor("D"), end.floor("D"))]
    source_files = []
    frames = []
    for path in paths:
        if not path.is_file():
            continue
        raw_bytes = path.read_bytes()
        source_files.append({"path": str(path.resolve()), "sha256": hashlib.sha256(raw_bytes).hexdigest()})
        raw = pd.read_csv(path)
        if "Timestamp" not in raw:
            raise MonitorContractError(f"Missing Timestamp: {path.name}")
        # SHI source timezone is explicit in this adapter, unlike decision cutoff.
        raw["Timestamp"] = pd.to_datetime(raw["Timestamp"], utc=True, errors="coerce")
        if raw["Timestamp"].isna().any():
            raise MonitorContractError(f"Unlocatable invalid timestamp: {path.name}")
        raw = raw[(raw.Timestamp > start) & (raw.Timestamp <= end)].copy()
        if raw.empty:
            continue
        raw = raw.rename(columns=RENAME)
        if raw.columns.duplicated().any():
            raise MonitorContractError("Ambiguous duplicate source columns")
        missing = set(PRICES + FLOW) - set(raw.columns)
        if missing:
            raise MonitorContractError(f"Missing required fields: {sorted(missing)}")
        for name in PRICES + FLOW + OPTIONAL:
            if name not in raw:
                raw[name] = float("nan")
            raw[name] = pd.to_numeric(raw[name], errors="coerce")
        raw["IsSynthetic"] = pd.to_numeric(raw.get("IsSynthetic", pd.Series(index=raw.index, dtype=float)), errors="coerce")
        raw["SourceFile"] = path.name
        frames.append(raw[["Timestamp"] + PRICES + FLOW + OPTIONAL + ["IsSynthetic", "SourceFile"]])

    columns = ["Timestamp"] + PRICES + FLOW + OPTIONAL + ["IsSynthetic", "SourceFile"]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True)
    frame = frame.sort_values("Timestamp", kind="stable").reset_index(drop=True)
    if frame.Timestamp.duplicated().any():
        # Even identical repeats can conceal an append/flush recovery problem.
        raise MonitorContractError("Duplicate close timestamps; resolve source provenance first")
    if not frame.empty and (frame.Timestamp != frame.Timestamp.dt.floor("min")).any():
        raise MonitorContractError("SHI close labels must lie on the minute grid")

    frame["Quality"] = "RAW"
    frame["PriceSource"] = "SHI_USDM_FUTURES"
    frame.loc[frame.IsSynthetic.ne(0), "Quality"] = "UNKNOWN_OR_SYNTHETIC"
    gap = frame.Timestamp.between(GAP_START, GAP_END, inclusive="both")
    frame.loc[gap, "Quality"] = "UNVERIFIED_RECOVERY"
    sidecar_manifest = None
    if recovery_quality is not None:
        if recovery_manifest is None:
            raise MonitorContractError("Recovery requires a frozen output manifest")
        frozen = json.loads(Path(recovery_manifest).read_text(encoding="utf-8-sig"))
        if frozen.get("schema_version") != "RECOVERY_CLOCK_V2":
            raise MonitorContractError("Recovery manifest is not clock v2")
        approved = {item["sha256"] for item in frozen["outputs"]}
        for source in source_files:
            day = pd.Timestamp(Path(source["path"]).stem, tz="UTC")
            if day <= GAP_END and day + pd.Timedelta(days=1) > GAP_START and source["sha256"] not in approved:
                raise MonitorContractError("Recovery source is not a frozen clock-v2 output")
        sidecar_path = Path(recovery_quality)
        if hashlib.sha256(sidecar_path.read_bytes()).hexdigest() not in approved:
            raise MonitorContractError("Recovery sidecar is not a frozen clock-v2 output")
        quality = pd.read_csv(sidecar_path)
        needed = {"Timestamp", "RecoveryClass", "RecoveredClose", "PriceSource", "OiSource", "FundingSource", "LiqSource"}
        if not needed.issubset(quality.columns):
            raise MonitorContractError("Recovery sidecar schema mismatch")
        quality["Timestamp"] = pd.to_datetime(quality.Timestamp, utc=True, errors="raise")
        if quality.Timestamp.duplicated().any():
            raise MonitorContractError("Duplicate recovery sidecar timestamps")
        sidecar_manifest = {"path": str(sidecar_path.resolve()), "sha256": hashlib.sha256(sidecar_path.read_bytes()).hexdigest(), "lineage": recovery_lineage}
        if recovery_lineage != RECOVERY_LINEAGE:
            raise MonitorContractError("Only explicit corrected recovery lineage is supported")
        lookup = quality.set_index("Timestamp")
        for index in frame.index[gap]:
            ts = frame.at[index, "Timestamp"]
            if ts not in lookup.index:
                continue
            q = lookup.loc[ts]
            close = pd.to_numeric(q.RecoveredClose, errors="coerce")
            matched_price = pd.notna(close) and abs(frame.at[index, "ClosePrice"] - close) <= .011
            # Class/source values are checked, not inferred from a directory name.
            if matched_price and q.RecoveryClass == "PRICE_VOLUME_OI_RECOVERED" and q.PriceSource == "legacy_volume_alert_archive":
                frame.at[index, "Quality"] = "RECOVERED_DEGRADED"
                frame.at[index, "PriceSource"] = "LEGACY_RECOVERED_PVD_VENUE_UNVERIFIED"
                frame.loc[index, OPTIONAL] = float("nan")
            elif matched_price and q.RecoveryClass == "REAL_ENRICHED" and frame.at[index, "IsSynthetic"] == 0:
                frame.at[index, "Quality"] = "RAW"

    invalid = frame[PRICES + FLOW].isna().any(axis=1)
    invalid |= (~frame[PRICES + FLOW].apply(lambda col: col.map(lambda x: pd.notna(x) and abs(x) != float("inf")))).any(axis=1)
    invalid |= (frame[PRICES] <= 0).any(axis=1) | (frame[FLOW] < 0).any(axis=1)
    invalid |= (frame.HiPrice < frame[PRICES].max(axis=1)) | (frame.LowPrice > frame[PRICES].min(axis=1))
    invalid |= ((frame.BuyQty + frame.SellQty - frame.TotalQty).abs() > (frame.TotalQty.abs() * 1e-5 + 1e-5))
    frame.loc[invalid, "Quality"] = "INVALID_REQUIRED_FIELDS"
    for name in OPTIONAL:
        frame.loc[frame[name].isin([float("inf"), -float("inf")]), name] = float("nan")
    unusable = ~frame.Quality.isin(["RAW", "RECOVERED_DEGRADED"])
    frame.loc[unusable, PRICES + FLOW + OPTIONAL] = float("nan")
    frame["Usable"] = ~unusable
    manifest = {"contract_version": VERSION, "source_files": source_files,
                "recovery_sidecar": sidecar_manifest, "cutoff_utc": end.isoformat(),
                "history_minutes": history_minutes, "raw_inputs_modified": False}
    return frame, manifest


def _window(frame: pd.DataFrame, end: pd.Timestamp, minutes: int) -> dict:
    start = end - pd.Timedelta(minutes=minutes)
    rows = frame[(frame.Timestamp > start) & (frame.Timestamp <= end)]
    expected = pd.date_range(start=end.floor("min") - pd.Timedelta(minutes=minutes - 1), periods=minutes, freq="min", tz="UTC")
    missing = expected.difference(pd.DatetimeIndex(rows.Timestamp))
    usable = rows[rows.Usable]
    issues = []
    if len(missing):
        issues.append("MISSING_MINUTES")
    if len(usable) != len(rows):
        issues.append("UNUSABLE_ROWS")
    if (rows.Quality == "RECOVERED_DEGRADED").any():
        issues.append("RECOVERED_DEGRADED")
    complete = not len(missing) and len(usable) == minutes
    result = {"start_exclusive_utc": start.isoformat(), "end_inclusive_utc": end.isoformat(),
              "expected_minutes": minutes, "rows_present": len(rows), "usable_rows": len(usable),
              "missing_minutes": len(missing), "first_missing_utc": _iso(missing[0]) if len(missing) else None,
              "quality_counts": {str(k): int(v) for k, v in rows.Quality.value_counts().items()},
              "status": "READY" if complete and not issues else "PARTIAL" if len(usable) else "UNUSABLE",
              "issues": issues, "metrics": None}
    if complete:
        volume = rows.TotalQty.sum()
        delta = rows.BuyQty.sum() - rows.SellQty.sum()
        metrics = {"open": float(rows.OpenPrice.iloc[0]), "close": float(rows.ClosePrice.iloc[-1]),
                   "high": float(rows.HiPrice.max()), "low": float(rows.LowPrice.min()),
                   "volume_btc": float(volume), "delta_btc": float(delta),
                   "delta_fraction": float(delta / volume) if volume > 0 else None,
                   "return_fraction": float(rows.ClosePrice.iloc[-1] / rows.OpenPrice.iloc[0] - 1)}
        for name in OPTIONAL:
            available = rows[name].notna().all()
            metrics[name] = (_number(rows[name].sum()) if name.startswith("Liq") else _number(rows[name].iloc[-1])) if available else None
            if not available:
                result["issues"].append(f"UNSUPPORTED_{name}")
        result["metrics"] = metrics
        if result["issues"]:
            result["status"] = "PARTIAL"
    return result


def closed_bars(frame: pd.DataFrame, cutoff: str | pd.Timestamp, minutes: int) -> list[dict]:
    """Right-labelled complete bars only; partial/synthetic bars cannot confirm swings."""
    if minutes not in (15, 60, 240):
        raise MonitorContractError("Only M15/H1/H4 aggregation is supported")
    end = utc_cutoff(cutoff)
    prefix = frame[frame.Timestamp <= end].copy()
    prefix["bar_close"] = prefix.Timestamp.dt.ceil(f"{minutes}min")
    result = []
    for close, group in prefix.groupby("bar_close", sort=True):
        if close > end or len(group) != minutes or not group.Usable.all():
            continue
        expected = pd.date_range(close - pd.Timedelta(minutes=minutes - 1), close, freq="min")
        if not pd.DatetimeIndex(group.Timestamp).equals(expected):
            continue
        result.append({"close_utc": close.isoformat(), "available_no_earlier_than_utc": close.isoformat(),
                       "open": float(group.OpenPrice.iloc[0]), "high": float(group.HiPrice.max()),
                       "low": float(group.LowPrice.min()), "close": float(group.ClosePrice.iloc[-1]),
                       "volume_btc": float(group.TotalQty.sum()),
                       "data_quality": "RECOVERED_DEGRADED" if (group.Quality != "RAW").any() else "RAW"})
    return result


def build_data_snapshot(frame: pd.DataFrame, cutoff: str | pd.Timestamp, *, max_age_seconds: int = 90) -> dict:
    """Input readiness is distinct from a validated market state/trading verdict."""
    end = utc_cutoff(cutoff)
    prefix = frame[frame.Timestamp <= end].copy()
    eligible = prefix[prefix.Usable]
    last = eligible.Timestamp.max() if not eligible.empty else None
    age = float((end - last).total_seconds()) if last is not None else None
    windows = {str(minutes): _window(prefix, end, minutes) for minutes in WINDOWS}
    gaps = sorted({f"{minutes}m:{issue}" for minutes, window in windows.items() for issue in window["issues"]})
    if age is None or age > max_age_seconds:
        gaps.append("STALE_OR_MISSING_USABLE_FEED")
    records = []
    for row in prefix.to_dict("records"):
        records.append({key: _iso(value) if isinstance(value, pd.Timestamp) else None if pd.isna(value) else value
                        for key, value in row.items()})
    return {"schema_version": VERSION, "cutoff_utc": end.isoformat(),
            "price_symbol": "BTCUSDT", "price_sources": sorted(prefix.PriceSource.unique().tolist()),
            "timestamp_contract": "UTC_SHI_FLUSH_CLOSE_LABEL",
            "field_units": {"price": "USDT_per_BTC", "volume": "BTC", "delta_fraction": "fraction_-1_to_1", "return_fraction": "fraction"},
            "latest_usable_source_close_utc": _iso(last), "source_label_age_seconds": age,
            "local_window_readiness": "READY" if not gaps else "PARTIAL" if len(eligible) else "UNUSABLE",
            "gaps": gaps, "windows": windows,
            "closed_bars": {name: closed_bars(prefix, end, minutes) for name, minutes in (("M15", 15), ("H1", 60), ("H4", 240))},
            "eligible_prefix_sha256": hashlib.sha256(_json(records).encode()).hexdigest(),
            "limits": ["Final CSV does not prove when each row was available to the decision process",
                       "Flush labels do not prove exact exchange-event candle boundaries",
                       "OI/funding/liquidation channel freshness is not recorded per row",
                       "State memory, level lifecycle and forecast calibration are not implemented by this data boundary"],
            "live_decision_eligible": False}
