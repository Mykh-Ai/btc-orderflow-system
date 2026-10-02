"""Replay only the two audited UNKNOWN_KEEP deltas, offline and isolated."""
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("D:/Project_V/btc-orderflow-system")
OUT = ROOT / "server_journals/vwap_unknown2_20260918_v1"
EXPERIMENT = "vwap_distance_unknown2_single_position_20260918_v1"


def main():
    audit = ROOT / "backtests/vwap_ab_admission_audit_20260918_v2/cases.jsonl"
    selected = [r for r in map(json.loads,audit.read_text(encoding="utf-8").splitlines())
                if r["base_admission_status"] == "BASE_GATES_PROXY_PASS_AB_UNRESOLVED" and r["decision"] == "UNKNOWN_KEEP"]
    keys = {(r["signal_ts_utc"],r["side"].lower()) for r in selected}
    assert len(keys) == 2
    raw = OUT / "selected_raw_archive"
    raw.mkdir(parents=True,exist_ok=False)
    empty = OUT / "empty_candidates"
    empty.mkdir()
    files,kept,removed = [],0,0
    for p in sorted((ROOT/"server_journals/vwap_portfolio_2026-09-18/archive/deltascout").glob("*.jsonl")):
        lines = []
        for line in p.read_text(encoding="utf-8").splitlines(keepends=True):
            r = json.loads(line)
            if r.get("event") == "CANDIDATE_COMPARISON_REJECT" and r.get("reject_reason") == "vwap_distance":
                t = datetime.fromisoformat(r["ts"]).replace(tzinfo=ZoneInfo("Europe/Bratislava")).astimezone(ZoneInfo("UTC")).isoformat()
                if (t,r["kind"]) not in keys:
                    removed += 1
                    continue
                kept += 1
            lines.append(line)
        target = raw/p.name
        target.write_text("".join(lines),encoding="utf-8",newline="")
        files.append(dict(source=str(p),source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                          derived=str(target),derived_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    assert kept == 2 and removed == 150
    reference_path = ROOT/"server_journals/vwap_known19_20260918_v1/selection_manifest.json"
    args = json.loads(reference_path.read_text(encoding="utf-8"))["cli_args"]
    for option,value in (("--candidate-root",str(empty)),("--raw-archive-root",str(raw)),
                         ("--experiment-id",EXPERIMENT),("--description","Isolated two base-gate proxy PASS / B UNKNOWN_KEEP deltas; fail-open admission, same frozen V8/costs as known19, single position180s cooldown; no historical live AB claim")):
        args[args.index(option)+1] = value
    manifest = dict(selected=selected,selection="Two UNKNOWN_KEEP only; A PASS / B untrusted recovery window",
                    audit_sha256=hashlib.sha256(audit.read_bytes()).hexdigest(),files=files,
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    reference_selection_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),cli_args=args)
    (OUT/"selection_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    subprocess.run([sys.executable,"-m","deltascout.research_bundle.scout_backtester.cli",*args],cwd=ROOT,
                   env=dict(os.environ,PYTHONPATH=str(REPO),PYTHONDONTWRITEBYTECODE="1"),check=True)
    run_dir = ROOT/"backtests"/EXPERIMENT
    run = json.loads((run_dir/"run_manifest.json").read_text(encoding="utf-8"))
    assert run["candidate_count"] == 2
    with (run_dir/"portfolio_trades.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert {(r["signal_ts_utc"],r["side"].lower()) for r in rows} == keys
    for r in rows:
        print(json.dumps({k:r[k] for k in ("signal_ts_utc","side","entry_status","entry_fill_ts","entry_fill_price","initial_stop_price","tp1_fill_ts","tp2_fill_ts","exit_ts","lifecycle_class","net_pnl_usdc","blocked_reason")},indent=2))
    print("total_net",sum(float(r["net_pnl_usdc"]) for r in rows))


if __name__ == "__main__":
    main()
