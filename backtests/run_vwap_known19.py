"""Select audited known-PASS19 without altering originals; run existing CLI."""
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
AUDIT = ROOT / "backtests/vwap_ab_admission_audit_20260918_v2/cases.jsonl"
INPUTS = ROOT / "server_journals/vwap_known19_20260918_v1"
SOURCE = ROOT / "server_journals/vwap_portfolio_2026-09-18"
EXPERIMENT = "vwap_distance_admitted19_single_position_20260918_v1"


def main():
    selected = [r for r in map(json.loads, AUDIT.read_text(encoding="utf-8").splitlines())
                if r["base_admission_status"] == "BASE_GATES_PROXY_PASS_AB_UNRESOLVED"
                and r["component_a"] is False and r["component_b"] is False]
    identities = {(r["signal_ts_utc"],r["side"].lower()) for r in selected}
    assert len(identities) == 19
    raw = INPUTS / "selected_raw_archive"
    raw.mkdir(parents=True,exist_ok=False)
    empty = INPUTS / "empty_candidates"
    empty.mkdir()
    manifest = dict(selection="BASE_GATES_PROXY_PASS + A=false + B=false; excludes UNKNOWN",
                    selected=selected,audit_sha256=hashlib.sha256(AUDIT.read_bytes()).hexdigest(),
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),files=[])
    kept,removed = 0,0
    for path in sorted((SOURCE / "archive/deltascout").glob("*.jsonl")):
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
            r=json.loads(line)
            if r.get("event")=="CANDIDATE_COMPARISON_REJECT" and r.get("reject_reason")=="vwap_distance":
                t=datetime.fromisoformat(r["ts"]).replace(tzinfo=ZoneInfo("Europe/Bratislava")).astimezone(ZoneInfo("UTC")).isoformat()
                if (t,r["kind"]) not in identities:
                    removed+=1
                    continue
                kept+=1
            # Keep every DELTA and all other decisions byte-for-byte as lines:
            # no fabricated PEAK, no loss of same-side shadow history.
            lines.append(line)
        out=raw/path.name
        out.write_text("".join(lines),encoding="utf-8",newline="")
        manifest["files"].append(dict(source=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     derived=str(out),derived_sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
    assert kept==19 and removed==133
    manifest.update(kept_distance_rejects=kept,removed_distance_rejects=removed)
    args=["--candidate-root",str(empty),"--raw-archive-root",str(raw),
          "--feed-root",str(SOURCE/"normalized_agg/daily"),
          "--quality-sidecar-root",str(REPO/"deltascout/research_material/recovery_clock_v2_2026-09-08/quality"),
          "--execution-feed-root",str(SOURCE/"btcusdc_spot/daily"),
          "--server-state-root",str(ROOT/"server_journals/2026-09-18"),
          "--output-root",str(ROOT/"backtests"),"--date-from","2026-03-16","--date-to","2026-09-18",
          "--candidate-groups","VWAP_DISTANCE_REJECT","--candidate-loss-filter","NONE",
          "--fill-model","LIMIT_THEN_MARKET_90S_GUARDED_V0_1",
          "--initial-stop-policy","volume_confirmed_swing","--swing-lookback-minutes","1440",
          "--initial-swing-lr","25","--initial-swing-buffer-usd","50","--initial-swing-max-distance-usd","1200",
          "--initial-swing-require-full-window","--trail-swing-lookback","240","--trail-swing-lr","25",
          "--trail-swing-buffer-usd","50","--trail-step-usd","25","--trail-confirm-buffer-usd","20",
          "--fixed-notional-usdc","3000","--commission-rate","0.000744",
          "--entry-slippage-bps","0","--exit-slippage-bps","1","--stop-slippage-bps","2",
          "--replay-modes","executor_portfolio","--experiment-id",EXPERIMENT,
          "--description","Audited base-gate proxy PASS and known A/B PASS19 only; isolated single-position cohort, 180s cooldown, frozen V8; closed candles cutoff17:04UTC Sep18; historical policy counterfactual not actual PnL"]
    manifest["cli_args"]=args
    (INPUTS/"selection_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    env=dict(os.environ,PYTHONPATH=str(REPO),PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable,"-m","deltascout.research_bundle.scout_backtester.cli",*args],cwd=ROOT,env=env,check=True)
    run=json.loads((ROOT/"backtests"/EXPERIMENT/"run_manifest.json").read_text(encoding="utf-8"))
    assert run["candidate_count"]==19
    assert run["resolved_config"]["cooldown_seconds"]==180
    print("Verified selected candidate_count=19; cooldown=180s")


if __name__=="__main__":
    main()
