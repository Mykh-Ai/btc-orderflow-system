"""Frozen A/B counterfactual, offline immutable evidence only; no live imports."""
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = Path("D:/Project_V/btc-orderflow-system/deltascout/research_material")
ARCHIVE = ROOT / "server_journals/vwap_portfolio_2026-09-18/archive/deltascout"
OUT = ROOT / "backtests/vwap_ab_admission_audit_20260918_v2"
sys.path.insert(0, str(RESEARCH.parents[1]))
# This is a pure, stateless function; never instantiate the runtime evaluator,
# whose startup/record methods write state.
from deltascout.loss_avoidance_policy import evaluate_loss_avoidance_policy, RULE_ID


def utc(value, local=False):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Bratislava") if local else timezone.utc)
    return dt.astimezone(timezone.utc)


def main():
    all_cases = [json.loads(s) for s in (ROOT / "backtests/vwap_admission_audit_20260918_v3/cases.jsonl").read_text(encoding="utf-8").splitlines()]
    selected = [c for c in all_cases if c["admission_conclusion"] in {"BASE_GATES_PROXY_PASS_AB_UNRESOLVED", "UNRESOLVED_REMAINING_GATES"}]
    peaks, live = {}, {}
    segment, last_seq = 0, None
    segments = {}
    for path in sorted(ARCHIVE.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            r = json.loads(line)
            seq = r.get("seq")
            if seq is not None and last_seq is not None and seq <= last_seq:
                segment += 1
            last_seq = seq
            if r.get("event") in {"DELTA_MAX", "DELTA_MIN"}:
                key = (utc(r["ts"], True), r["kind"].upper(), abs(float(r["delta"])))
                peaks[key] = dict(r, segment=segment)
                segments[key[:2]] = segment
            if r.get("event") == "PEAK_LOSS_FILTER_DECISION":
                live[(utc(r["signal_ts_utc"]), r["kind"].upper())] = r
    cutoffs = {utc(c["signal_ts_utc"]) for c in selected} | {key[0] for key in live}
    days = {dt.date() for t in cutoffs for dt in (t, t-timedelta(minutes=239))}
    bars, duplicates, provenance = {}, set(), {}
    for day in sorted(days):
        name = f"{day}.csv"
        sources = [ROOT / "server_journals/2026-09-18/shi_feed" / name,
                   RESEARCH / "recovery_clock_v2_2026-09-08/effective_feed" / name,
                   RESEARCH / "source_archives/vps_refresh_2026-08-31/enriched_feed" / name]
        path = next((p for p in sources if p.exists()), None)
        if path is None:
            provenance[name] = {"status": "MISSING"}
            continue
        provenance[name] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                t = utc(row["Timestamp"])
                if t in bars:
                    duplicates.add(t)
                bars[t] = row
    degraded = set()
    raw_delta = {}
    raw_imb = {}
    legacy_hashes = {}
    for path in sorted((ARCHIVE.parent / "feed").glob("*.csv")):
        legacy_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ts = utc(row["Timestamp"], True)
                buy,sell = float(row["BuyQty"]),float(row["SellQty"])
                raw_delta[ts] = abs(buy-sell)
                if ts in cutoffs:
                    raw_imb[ts] = abs(buy-sell)/(buy+sell) if buy+sell else 0
    quality_path = RESEARCH / "recovery_clock_v2_2026-09-08/quality/recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv"
    with quality_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["RecoveryClass"] != "REAL_ENRICHED":
                degraded.add(utc(row["Timestamp"]))

    def evaluate(t, side, delta):
        # Live records the current DELTA before checking admission, so include
        # it in the same-side sample and use <= for rank ties.
        target_segment = segments[(t, side)]
        values = [raw_delta.get(ts, d) if r["segment"] == target_segment else d
                  for (ts, s, d),r in peaks.items() if t-timedelta(hours=24) <= ts <= t and s == side]
        percentile = sum(d <= abs(delta) for d in values) / len(values) * 100 if values else None
        # Precision/bootstrap sensitivity: all earlier values rehydrated from
        # rounded research JSONL, while the new current peak is recorded exact.
        archive_values = [raw_delta.get(ts,d) if ts == t else d
                          for (ts,s,d) in peaks if t-timedelta(hours=24) <= ts <= t and s == side]
        archive_percentile = sum(d <= abs(delta) for d in archive_values)/len(archive_values)*100 if archive_values else None
        expected = [t-timedelta(minutes=239-i) for i in range(240)]
        status, oi, directional = "EXACT", None, None
        if any(ts in duplicates for ts in expected):
            status = "DUPLICATE"
        elif any(ts not in bars for ts in expected):
            status = "MISSING_240M"
        elif any(str(bars[ts].get("IsSynthetic", "")).lower() not in {"0", "false", "no", "n"} for ts in expected):
            status = "SYNTHETIC_240M"
        else:
            try:
                buy = sum(float(bars[ts]["BuyQty"]) for ts in expected)
                sell = sum(float(bars[ts]["SellQty"]) for ts in expected)
                oi = float(bars[expected[-1]]["OpenInterest"])-float(bars[expected[-60]]["OpenInterest"])
                directional = (buy-sell)/(buy+sell) * (1 if side == "LONG" else -1)
                if not all(math.isfinite(n) for n in (buy, sell, oi, directional)) or buy+sell <= 0:
                    raise ValueError("invalid numeric")
            except (ValueError, ZeroDivisionError, KeyError):
                status, oi, directional = "INVALID_NUMERIC", None, None
        # Corrected recovered flow is usable as a diagnostic, but copied/ffilled
        # OI in recovery is not proof of a trusted historical B window.
        if status == "EXACT" and any(ts in degraded for ts in expected):
            status = "RECOVERY_DEGRADED_B_UNKNOWN"
        trusted = status == "EXACT"
        decision = evaluate_loss_avoidance_policy(same_side_peak_percentile_24h=percentile,
                    oi_change_60m=oi, oi_trusted_60m=trusted, directional_delta_pct_240m=directional)
        return dict(rule_id=RULE_ID, same_side_peak_count_24h=len(values), same_side_peak_percentile_24h=percentile,
                    a_archive_bootstrap_percentile=archive_percentile,
                    a_precision_sensitivity_stable=(percentile <= 50) == (archive_percentile <= 50) if percentile is not None and archive_percentile is not None else False,
                    oi_change_60m=oi, directional_delta_pct_240m=directional, oi_trusted_60m=trusted,
                    feature_status=status, **{k: v for k,v in decision.to_dict().items() if k != "rule_id"})

    validation, comparisons = Counter(), []
    for (t, side), r in live.items():
        result = evaluate(t, side, float(r["delta"]))
        fields = ("same_side_peak_count_24h", "same_side_peak_percentile_24h", "oi_change_60m", "directional_delta_pct_240m", "component_a", "component_b")
        mismatch = []
        for field in fields:
            a,b = result[field], r.get(field)
            same = a == b if isinstance(a, (bool,type(None))) else b is not None and abs(a-b) < 1e-7
            if not same:
                mismatch.append(field)
        validation["checked"] += 1
        if mismatch:
            validation["mismatched"] += 1
        comparisons.append(dict(signal_ts_utc=t.isoformat(), side=side, mismatch=mismatch, recomputed=result, recorded=r))
    results = []
    for c in selected:
        t,side = utc(c["signal_ts_utc"]),c["side"].upper()
        result = evaluate(t, side, float(c["current"]["delta"]))
        result.update(signal_ts_utc=t.isoformat(),side=side,source=c["source"],base_admission_status=c["admission_conclusion"],
                      historical_scope="Frozen V1 policy counterfactual; rollout documented Aug20, not historical live veto for earlier dates.")
        if c["admission_conclusion"] == "UNRESOLVED_REMAINING_GATES":
            result["exact_legacy_imbalance"] = raw_imb[t]
            result["observed_imb_thresholds"] = c["observed_segment_imb_thresholds"]
            lo,hi = c["observed_segment_imb_thresholds"][0]
            result["resolved_base_status"] = "PASS" if lo <= raw_imb[t] <= hi else "BLOCKED_IMB"
        results.append(result)
    primary = [r for r in results if r["base_admission_status"] == "BASE_GATES_PROXY_PASS_AB_UNRESOLVED"]
    summary = dict(rule_id=RULE_ID, evaluated=len(results), primary_candidates=len(primary),
                   primary_decisions=dict(Counter(r["decision"] for r in primary)),
                   primary_components=dict(A_block=sum(r["component_a"] is True for r in primary),
                                           B_block=sum(r["component_b"] is True for r in primary),
                                           both_block=sum(r["component_a"] is True and r["component_b"] is True for r in primary),
                                           B_unknown=sum(r["component_b"] is None for r in primary)),
                   validation=dict(validation), feed_provenance=provenance,
                   a_precision_sensitivity_stable_all=all(r["a_precision_sensitivity_stable"] for r in results),
                   legacy_feed_sha256=legacy_hashes,
                   audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   policy_sha256=hashlib.sha256((RESEARCH.parent / "loss_avoidance_policy.py").read_bytes()).hexdigest(),
                   quality_sidecar_sha256=hashlib.sha256(quality_path.read_bytes()).hexdigest(),
                   notes="A/B states are blocker matches (true means BLOCK). Policy union does not reconstruct historical fail-open circuit, budget, state/audit I/O errors. UNKNOWN is not PASS.")
    assert len(primary)==27 and len(results)==28
    assert all(r["a_precision_sensitivity_stable"] for r in results)
    for item in comparisons:
        if item["mismatch"]:
            print(json.dumps({"ts":item["signal_ts_utc"],"mismatch":item["mismatch"],"computed":item["recomputed"],"recorded":{k:item["recorded"].get(k) for k in fields}}, indent=2))
    assert not validation["mismatched"], validation
    OUT.mkdir(exist_ok=False)
    for name,data in (("cases.jsonl",results),("live_validation.jsonl",comparisons)):
        (OUT/name).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in data),encoding="utf-8")
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in {"feed_provenance","legacy_feed_sha256"}},indent=2))
    for r in results:
        print(r["signal_ts_utc"],r["side"],r["same_side_peak_percentile_24h"],r["component_a"],r["component_b"],r["decision"],r["feature_status"])


if __name__ == "__main__":
    main()
