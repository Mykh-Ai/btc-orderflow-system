"""Evaluate loss-avoidance shadow rules against lifecycle-defined trade utility.

The policy objective deliberately treats TP1->SL as a scratch/neutral attempt.  A
candidate rule is useful when it covers plain-stop losses without covering trades
that reached both TP1 and TP2.  This is an offline descriptive review, not a live
admission rule.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Optional


PLAIN_LOSS = "plain_loss_stop"
SCRATCH = "tp1_then_stop"
PROTECTED = "protected_profit_trailing_stop"


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _summary_quote(snapshot: Dict[str, Any], leg: str) -> float:
    summaries = snapshot.get("fill_summaries") or {}
    return _num((summaries.get(leg) or {}).get("total_quote_qty")) or 0.0


def _snapshot_turnover(snapshot: Dict[str, Any]) -> Optional[float]:
    entry = _summary_quote(snapshot, "entry")
    exits = sum(_summary_quote(snapshot, leg) for leg in ("tp1", "tp2", "final_sl"))
    return entry + exits if entry and exits else None


def _snapshot_gross(snapshot: Dict[str, Any]) -> Optional[float]:
    direct = _num((snapshot.get("pnl") or {}).get("gross_realized_pnl_approx"))
    if direct is not None:
        return direct
    entry = _summary_quote(snapshot, "entry")
    exits = sum(_summary_quote(snapshot, leg) for leg in ("tp1", "tp2", "final_sl"))
    side = str((snapshot.get("local_last_closed") or {}).get("side") or "").upper()
    if not entry or not exits or side not in {"LONG", "SHORT"}:
        return None
    return exits - entry if side == "LONG" else entry - exits


def _calibrate_fee_rate(
    ledger_by_trade: Dict[str, Dict[str, str]], snapshots_by_trade: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    observations = []
    for trade_key, ledger in ledger_by_trade.items():
        if ledger.get("commission_source") != "actual" or trade_key not in snapshots_by_trade:
            continue
        commission = _num(ledger.get("commission_usdc"))
        turnover = _snapshot_turnover(snapshots_by_trade[trade_key])
        if commission is not None and turnover:
            observations.append(
                {"trade_key": trade_key, "commission_usdc": commission, "turnover_usdc": turnover,
                 "fee_rate": commission / turnover}
            )
    rate = median(item["fee_rate"] for item in observations) if observations else 0.00075
    return {"median_fee_rate": rate, "observation_count": len(observations), "observations": observations}


def _scratch_pnl_audit(
    rows: Iterable[Dict[str, Any]], material: Path
) -> Dict[str, Any]:
    state = material / "server_state"
    snapshots = _read_jsonl(state / "trade_execution_snapshots.jsonl")
    snapshots_by_trade = {str(row.get("trade_key")): row for row in snapshots if row.get("trade_key")}
    ledger = _read_csv(state / "trade_pnl_ledger.csv")
    ledger_by_trade = {str(row.get("trade_key")): row for row in ledger if row.get("trade_key")}
    calibration = _calibrate_fee_rate(ledger_by_trade, snapshots_by_trade)
    fee_rate = calibration["median_fee_rate"]

    audited = []
    for row in sorted(rows, key=lambda item: item["signal_ts_local"]):
        trade_key = str(row.get("trade_key") or "")
        item = {
            "trade_key": trade_key or None,
            "signal_ts_local": row["signal_ts_local"],
            "side": row["side"],
            "gross_pnl_usdc": None,
            "commission_usdc": None,
            "net_pnl_after_commission_usdc": None,
            "pnl_evidence": "lifecycle_only_no_execution_pnl",
            "utility_bucket": "scratch_neutral",
        }
        if trade_key in ledger_by_trade:
            ledger_row = ledger_by_trade[trade_key]
            item.update(
                gross_pnl_usdc=_num(ledger_row.get("gross_pnl_usdc")),
                commission_usdc=_num(ledger_row.get("commission_usdc")),
                net_pnl_after_commission_usdc=_num(ledger_row.get("net_pnl_usdc")),
                pnl_evidence=(
                    "ledger_actual" if ledger_row.get("net_pnl_source") == "actual" else "ledger_fee_estimated"
                ),
            )
        elif trade_key in snapshots_by_trade:
            snapshot = snapshots_by_trade[trade_key]
            gross = _snapshot_gross(snapshot)
            turnover = _snapshot_turnover(snapshot)
            commission = turnover * fee_rate if turnover is not None else None
            item.update(
                gross_pnl_usdc=gross,
                commission_usdc=commission,
                net_pnl_after_commission_usdc=(
                    gross - commission if gross is not None and commission is not None else None
                ),
                pnl_evidence="snapshot_gross_fee_rate_estimated",
            )
        net = item["net_pnl_after_commission_usdc"]
        item["fee_flipped_negative"] = bool(
            item["gross_pnl_usdc"] is not None and item["gross_pnl_usdc"] > 0 and net is not None and net < 0
        )
        audited.append(item)
    return {
        "fee_calibration": calibration,
        "known_net_count": sum(item["net_pnl_after_commission_usdc"] is not None for item in audited),
        "fee_flipped_negative_count": sum(item["fee_flipped_negative"] for item in audited),
        "trades": audited,
        "contract": (
            "Net PnL is after execution commissions but excludes borrow interest, which is unavailable in the "
            "execution snapshots. TP1->SL remains scratch_neutral regardless of a small positive or negative net."
        ),
    }


Rule = Callable[[Dict[str, Any]], bool]


def _weak_peak(threshold: float) -> Rule:
    return lambda row: (
        _num(row.get("peak_delta_percentile_24h")) is not None
        and float(row["peak_delta_percentile_24h"]) <= threshold
    )


def _oi_down_weak_broad_flow(row: Dict[str, Any]) -> bool:
    directional = _num(row.get("directional_delta_pct_240m"))
    return bool(
        (row.get("patterns") or {}).get("oi_down_60m") is True
        and directional is not None
        and directional < 0.06
    )


def _or(left: Rule, right: Rule) -> Rule:
    return lambda row: left(row) or right(row)


def _evaluate(name: str, description: str, rule: Rule, cohorts: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"rule": name, "description": description, "cohorts": {}}
    for group, rows in cohorts.items():
        matched = [row for row in rows if rule(row)]
        result["cohorts"][group] = {
            "count": len(matched),
            "denominator": len(rows),
            "rate": len(matched) / len(rows) if rows else None,
            "trades": [
                {
                    "trade_key": row.get("trade_key"),
                    "signal_ts_local": row["signal_ts_local"],
                    "side": row["side"],
                }
                for row in matched
            ],
        }
    return result


def _fmt_rate(value: Dict[str, Any]) -> str:
    return f"{value['count']}/{value['denominator']} ({value['rate'] * 100:.0f}%)" if value["denominator"] else "n/a"


def build(source_json: Path, material: Path, output_json: Path, output_md: Path) -> Dict[str, Any]:
    source = json.loads(source_json.read_text(encoding="utf-8"))
    rows = source["trades"]
    cohorts = {
        "plain_loss": [row for row in rows if row["outcome_group"] == PLAIN_LOSS],
        "scratch_tp1_sl": [row for row in rows if row["outcome_group"] == SCRATCH],
        "protected_tp1_tp2": [row for row in rows if row["outcome_group"] == PROTECTED],
    }
    weak50 = _weak_peak(50.0)
    weak60 = _weak_peak(60.0)
    rules = [
        ("weak_peak_le_50", "delta candidate percentile <= 50", weak50),
        (
            "oi_down_60_and_directional_delta_pct_240_lt_0_06",
            "trusted OI decline over 60m and directional 240m delta share < 6%",
            _oi_down_weak_broad_flow,
        ),
        (
            "conservative_union",
            "peak percentile <= 50 OR (OI down 60m AND directional 240m delta share < 6%)",
            _or(weak50, _oi_down_weak_broad_flow),
        ),
        (
            "exploratory_union_peak_le_60",
            "peak percentile <= 60 OR (OI down 60m AND directional 240m delta share < 6%)",
            _or(weak60, _oi_down_weak_broad_flow),
        ),
    ]
    evaluations = [_evaluate(*rule, cohorts) for rule in rules]
    scratch_audit = _scratch_pnl_audit(cohorts["scratch_tp1_sl"], material)

    result = {
        "schema_version": "loss_avoidance_policy_review_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_json),
        "objective": {
            "target": "reduce plain SL losses",
            "neutral": "TP1 then SL, including fee-negative scratches",
            "protected": "TP1 and TP2 reached with trailing protection",
            "primary_error": "a rule match on a protected TP1+TP2 trade",
        },
        "scope": {
            "plain_losses": len(cohorts["plain_loss"]),
            "scratch_tp1_sl": len(cohorts["scratch_tp1_sl"]),
            "protected_tp1_tp2_joined": len(cohorts["protected_tp1_tp2"]),
            "protected_tp1_tp2_canonical_total": source["scope"]["canonical_protected_profit_total"],
        },
        "rule_evaluations": evaluations,
        "scratch_pnl_audit": scratch_audit,
        "guardrails": [
            "All features are pre-entry and use the corrected Bratislava-local to UTC feed join.",
            "The thresholds were inspected on this same small sample and therefore are exploratory.",
            "Zero protected matches means 0 of 7 signal-joined controls, not a guarantee over future trades.",
            "One of 8 canonical protected trades lacks a comparable accepted-signal join.",
            "No candidate is authorized as a live hard veto by this report.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Loss-Avoidance Policy Review",
        "",
        "## Utility contract",
        "",
        "- Target: reduce full `SL without TP1` losses.",
        "- Neutral: `TP1 -> SL`, including a tiny fee-adjusted loss.",
        "- Protect: trades that reached both `TP1 + TP2` and trailing protection.",
        "- The costly false positive is a rule match on the protected cohort, not on the scratch cohort.",
        "",
        "## Candidate coverage",
        "",
        "| Rule | Plain losses covered | TP1->SL scratches covered | Protected TP1+TP2 covered |",
        "|---|---:|---:|---:|",
    ]
    for item in evaluations:
        c = item["cohorts"]
        lines.append(
            f"| `{item['rule']}` | {_fmt_rate(c['plain_loss'])} | {_fmt_rate(c['scratch_tp1_sl'])} | "
            f"{_fmt_rate(c['protected_tp1_tp2'])} |"
        )
    lines.extend(
        [
            "",
            "## Current best shadow hypothesis",
            "",
            "The conservative union flags a signal when either:",
            "",
            "1. its same-side delta candidate is at or below the 50th percentile of the preceding 24h; or",
            "2. trusted OI is falling over 60m while the direction-adjusted 240m buy/sell delta share is below 6%.",
            "",
            "This describes two related failure modes: a weak event by itself, or a local impulse occurring while "
            "participation is shrinking and the broad directional flow is weak. Falling OI alone is deliberately "
            "not used because it also occurred in protected winners, including the latest strong trade.",
            "",
            "## TP1->SL fee audit",
            "",
            f"- Scratch trades in the feature cohort: **{len(cohorts['scratch_tp1_sl'])}**.",
            f"- Net-after-commission result known or reconstructed: **{scratch_audit['known_net_count']}**.",
            f"- Positive gross PnL flipped slightly negative by estimated commission: **{scratch_audit['fee_flipped_negative_count']}**.",
            f"- Estimated commission rate from actual overlapping fills: **{scratch_audit['fee_calibration']['median_fee_rate'] * 100:.4f}% of turnover** "
            f"({scratch_audit['fee_calibration']['observation_count']} observations).",
            "- Borrow interest is not present in the snapshots and is excluded; this does not change the neutral utility bucket.",
            "",
            "| Signal local | Trade | Gross USDC | Commission USDC | Net USDC | Evidence |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in scratch_audit["trades"]:
        def cell(value: Optional[float]) -> str:
            return "" if value is None else f"{value:.2f}"

        lines.append(
            f"| {item['signal_ts_local']} | `{item['trade_key'] or ''}` | {cell(item['gross_pnl_usdc'])} | "
            f"{cell(item['commission_usdc'])} | {cell(item['net_pnl_after_commission_usdc'])} | "
            f"`{item['pnl_evidence']}` |"
        )
    conservative = next(item for item in evaluations if item["rule"] == "conservative_union")
    lines.extend(
        [
            "",
            "## Trades matched by the conservative hypothesis",
            "",
        ]
    )
    for group, label in (
        ("plain_loss", "Plain losses"),
        ("scratch_tp1_sl", "TP1->SL scratches"),
        ("protected_tp1_tp2", "Protected TP1+TP2"),
    ):
        matched = conservative["cohorts"][group]["trades"]
        lines.append(f"### {label}")
        lines.append("")
        if matched:
            for item in matched:
                lines.append(f"- {item['signal_ts_local']} {item['side']} `{item['trade_key'] or 'manual-confirmed'}`")
        else:
            lines.append("- None in the signal-joined sample.")
        lines.append("")
    lines.extend(
        [
            "## Decision",
            "",
            "Keep this as an offline/shadow score, not a live veto. Journal both component flags separately. "
            "Promotion requires prospective observations and continued zero/near-zero coverage of TP1+TP2 winners.",
            "",
            "## Guardrails",
            "",
        ]
    )
    lines.extend(f"- {guardrail}" for guardrail in result["guardrails"])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-json",
        type=Path,
        default=Path(
            "deltascout/research_material/reviews/losing_trade_commonality_2026-03-20_to_2026-08-20.json"
        ),
    )
    parser.add_argument("--material-root", type=Path, default=Path("deltascout/research_material"))
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "deltascout/research_material/reviews/loss_avoidance_policy_review_2026-03-20_to_2026-08-20.json"
        ),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "deltascout/research_material/reviews/loss_avoidance_policy_review_2026-03-20_to_2026-08-20.md"
        ),
    )
    args = parser.parse_args()
    result = build(args.source_json, args.material_root, args.output_json, args.output_md)
    print(json.dumps({"scope": result["scope"], "rules": result["rule_evaluations"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
