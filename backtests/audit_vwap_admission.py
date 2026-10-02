"""Offline evidence-only audit; never imports live Scout or calls an API.

Reconstruct prev_peak in archive order, respecting sequence resets. Rounded
volume ties remain UNKNOWN. Later gate contexts absent from reject records are
not fabricated, and observed segment thresholds are explicitly only inferred.
"""
import json
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "server_journals/vwap_portfolio_2026-09-18/archive/deltascout"
OUT = ROOT / "backtests/vwap_admission_audit_20260918_v3"


def compare(curr, prev):
    if not prev or curr.get("kind") != prev.get("kind"):
        return {k: "UNKNOWN" for k in ("price", "volume", "vwap")}
    result = {}
    for field, name in (("price", "price"), ("vol", "volume"), ("vwap", "vwap")):
        a, b = curr.get(field), prev.get(field)
        if a is None or b is None:
            result[name] = "UNKNOWN"
            continue
        diff = float(a) - float(b)
        if field == "vol":
            # Both research volumes are rounded to 2 decimals; equality cannot
            # establish the strict unrounded inequality used by live Scout.
            result[name] = "PASS" if diff > 0.0100001 else "FAIL" if diff < -0.0100001 else "UNKNOWN"
        else:
            if curr["kind"] == "short":
                diff = -diff
            result[name] = "PASS" if diff > 0 else "FAIL"
    return result


def audit():
    previous = None
    last_seq = None
    segment = 0
    pending = None
    configs = defaultdict(set)
    market_configs = defaultdict(set)
    observed_contexts = []
    cases = []
    validation = Counter()
    hashes = {}
    import hashlib
    for path in sorted(ARCHIVE.glob("*.jsonl")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            rec = json.loads(line)
            seq = rec.get("seq")
            if seq is not None and last_seq is not None and seq <= last_seq:
                segment += 1
                previous = None
                pending = None
            last_seq = seq
            if "imb_min" in rec and "imb_max" in rec:
                configs[segment].add((float(rec["imb_min"]), float(rec["imb_max"])))
            if "chop30_max" in rec and "coh10_min" in rec:
                market_configs[segment].add((float(rec["chop30_max"]), float(rec["coh10_min"])))
            if all(k in rec for k in ("price_now", "ema50_now", "chop30", "coh10", "ts")):
                observed_contexts.append(rec)
            if rec.get("event") in ("DELTA_MAX", "DELTA_MIN"):
                pending = (previous, rec, f"{path.name}:{line_number}", segment)
                previous = rec
            if rec.get("reject_reason") == "no_prev_peak":
                validation["recorded_no_prev_resets"] += 1
                # Explicit live reset is stronger than archive continuity.
                if pending:
                    pending = (None, pending[1], pending[2], pending[3])
            if rec.get("reject_reason") == "3of3_fail" and pending:
                p = pending[0]
                if p:
                    matches = all(abs(float(p[k]) - float(rec["prev_" + k])) <= (0.00501 if k == "vol" else 0.000001)
                                  for k in ("price", "vol", "vwap") if rec.get("prev_" + k) is not None and p.get(k) is not None)
                    validation["prev_matches_recorded" if matches else "prev_mismatches_recorded"] += 1
            if rec.get("event") != "CANDIDATE_COMPARISON_REJECT" or rec.get("reject_reason") != "vwap_distance":
                continue
            assert pending and pending[1]["ts"] == rec["ts"] and pending[1]["kind"] == rec["kind"]
            p, current, source, seg = pending
            checks = compare(current, p)
            status = "FAIL" if "FAIL" in checks.values() else "UNKNOWN" if "UNKNOWN" in checks.values() else "PASS"
            utc = datetime.fromisoformat(rec["ts"]).replace(tzinfo=ZoneInfo("Europe/Bratislava")).astimezone(ZoneInfo("UTC")).isoformat()
            cases.append(dict(signal_ts_utc=utc, side=rec["kind"], source=f"{path.name}:{line_number}",
                              delta_source=source, segment=seg, current=current, previous=p,
                              three_of_three=checks, three_of_three_status=status))
    # Reconstruct only requested/observed timestamps using original legacy
    # close/buy/sell fields. Continuous EMA is a proxy for the rolling live file;
    # compare against recorded gate contexts rather than declaring equivalence.
    targets = {c["current"]["ts"] for c in cases} | {r["ts"] for r in observed_contexts}
    contexts = {}
    window = []
    ema = None
    for path in sorted((ARCHIVE.parent / "feed").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                price, buy, sell = float(r["ClosePrice"]), float(r["BuyQty"]), float(r["SellQty"])
                ema = price if ema is None else price * (2 / 51) + ema * (49 / 51)
                window.append((price, buy, sell))
                window = window[-30:]
                if r["Timestamp"] not in targets:
                    continue
                prices = [x[0] for x in window]
                span = max(prices) - min(prices)
                chop = sum(abs(b-a) for a, b in zip(prices, prices[1:])) / span if span else None
                v = sum(x[1]+x[2] for x in window[-10:])
                coh = abs(sum(x[1]-x[2] for x in window[-10:])) / v if v else 0
                contexts[r["Timestamp"]] = dict(price=price, ema50_proxy=ema, chop30=chop, coh10=coh)
    context_validation = Counter()
    for r in observed_contexts:
        x = contexts.get(r["ts"])
        if not x:
            context_validation["missing"] += 1
            continue
        context_validation["checked"] += 1
        for key, observed, tolerance in (("price", "price_now", .000001), ("ema50_proxy", "ema50_now", .01), ("chop30", "chop30", .00501), ("coh10", "coh10", .000501)):
            if x[key] is None or abs(x[key]-r[observed]) > tolerance:
                context_validation[key + "_mismatch"] += 1
    for c in cases:
        values = configs[c["segment"]]
        c["observed_segment_imb_thresholds"] = sorted(values)
        if len(values) == 1:
            lo, hi = next(iter(values))
            imb = float(c["current"]["imb"])
            # Research imbalance is rounded to three decimals.
            c["imb_status_inferred"] = "FAIL" if imb + .0005001 < lo or imb - .0005001 > hi else "PASS" if imb - .0005001 >= lo and imb + .0005001 <= hi else "UNKNOWN"
        else:
            c["imb_status_inferred"] = "UNKNOWN"
        x = contexts.get(c["current"]["ts"])
        c["reconstructed_context"] = x
        c["ema50_vwap_regime_status"] = "UNKNOWN"
        c["chop_coherence_status"] = "UNKNOWN"
        c["observed_segment_market_thresholds"] = sorted(market_configs[c["segment"]])
        if x:
            direction = 1 if c["side"] == "long" else -1
            ema_diff = direction * (x["price"] - x["ema50_proxy"])
            vwap_diff = direction * (x["price"] - c["current"]["vwap"])
            c["ema50_vwap_regime_status"] = "FAIL" if ema_diff < -.01 or vwap_diff <= 0 else "PASS" if ema_diff > .01 else "UNKNOWN"
            if len(market_configs[c["segment"]]) == 1 and x["chop30"] is not None:
                max_chop, min_coh = next(iter(market_configs[c["segment"]]))
                c["chop_coherence_status"] = "PASS" if x["chop30"] <= max_chop and x["coh10"] >= min_coh else "FAIL"
        c["ab_status"] = "NOT_EVALUATED"
        c["admission_conclusion"] = "BLOCKED_3OF3" if c["three_of_three_status"] == "FAIL" else "BLOCKED_IMB_UNDER_OBSERVED_SEGMENT_CONFIG" if c["imb_status_inferred"] == "FAIL" else "UNRESOLVED_REMAINING_GATES"
        if c["admission_conclusion"] == "UNRESOLVED_REMAINING_GATES" and (c["ema50_vwap_regime_status"] == "FAIL" or c["chop_coherence_status"] == "FAIL"):
            c["admission_conclusion"] = "BLOCKED_RECONSTRUCTED_MARKET_GATE"
        elif all(c[k] == "PASS" for k in ("three_of_three_status", "imb_status_inferred", "ema50_vwap_regime_status", "chop_coherence_status")):
            c["admission_conclusion"] = "BASE_GATES_PROXY_PASS_AB_UNRESOLVED"
    assert len(cases) == 152
    assert not validation["prev_mismatches_recorded"], validation
    summary = dict(total=len(cases), three_of_three=dict(Counter(c["three_of_three_status"] for c in cases)),
                   audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   failed_components=dict(Counter(k for c in cases for k, v in c["three_of_three"].items() if v == "FAIL")),
                   conclusions=dict(Counter(c["admission_conclusion"] for c in cases)),
                   imb_among_3of3_pass=dict(Counter(c["imb_status_inferred"] for c in cases if c["three_of_three_status"] == "PASS")),
                   validation=dict(validation), segments=segment + 1,
                   reconstructed_context_validation=dict(context_validation),
                   remaining_gate_scope="Market gates reconstructed under segment-observed thresholds, continuous EMA proxy; historical AB not evaluated, absence is not PASS.",
                   input_sha256=hashes)
    OUT.mkdir(exist_ok=False)
    (OUT / "cases.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "input_sha256"}, indent=2))
    print("September cases:")
    for c in cases:
        if c["signal_ts_utc"].startswith("2026-09-17") or c["signal_ts_utc"].startswith("2026-09-18"):
            print(c["signal_ts_utc"], c["three_of_three"], c["imb_status_inferred"], c["admission_conclusion"])


if __name__ == "__main__":
    audit()
