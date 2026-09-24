"""Join frozen blind GPT-5.6 verdicts to the local historical lifecycle ledger."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "docs" / "research" / "gpt56_prompt_abc"
LEDGER_PATH = ROOT / "docs" / "research" / "canonical_trade_evaluation_snapshot" / "case_ledger.csv"
SNAPSHOTS_PATH = ROOT / "docs" / "research" / "canonical_trade_evaluation_snapshot" / "frozen_trade_evaluation_snapshots.jsonl"
BLIND_PATH = RUN_DIR / "verdicts_blind.csv"
VARIANTS = ("A_CANONICAL", "B_CANONICAL", "C_CANONICAL")


def _truth(value: str) -> bool:
    return value.strip().lower() == "true"


def _lifecycle(row: dict[str, str]) -> str:
    if _truth(row["tp2_done"]):
        return "STRONG_FAVORABLE"
    if _truth(row["tp1_done"]):
        return "MIXED"
    if row["outcome_reason"] == "SL":
        return "NEGATIVE"
    return "UNKNOWN"


def _evaluation_bucket(lifecycle: str, verdict: str) -> str:
    if lifecycle == "MIXED":
        return "MIXED_OUTCOME"
    if lifecycle == "UNKNOWN":
        return "UNKNOWN_OUTCOME"
    if verdict == "UNCLEAR":
        return "UNCLEAR"
    expected = "REJECT" if lifecycle == "NEGATIVE" else "SUPPORT"
    return "ALIGNED" if verdict == expected else "MISS"


def _mean(values: list[float]) -> str:
    return f"{statistics.mean(values):.3f}" if values else "—"


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.3f}" if values else "—"


def _json_list(value: str) -> list[str]:
    parsed = json.loads(value or "[]")
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("expected JSON list of strings")
    return parsed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with LEDGER_PATH.open(encoding="utf-8", newline="") as stream:
        ledger = {row["trade_key"]: row for row in csv.DictReader(stream)}
    with BLIND_PATH.open(encoding="utf-8", newline="") as stream:
        blind = list(csv.DictReader(stream))
    snapshots = {
        item["signal"]["trade_key"]: item
        for line in SNAPSHOTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for item in [json.loads(line)]
    }

    if len(blind) != 60:
        raise ValueError(f"expected 60 blind rows, got {len(blind)}")
    pairs = {(row["trade_key"], row["variant"]) for row in blind}
    if len(pairs) != 60:
        raise ValueError("duplicate blind trade/variant pair")
    trade_keys = sorted({row["trade_key"] for row in blind})
    if len(trade_keys) != 20:
        raise ValueError(f"expected 20 trades, got {len(trade_keys)}")
    if any(key not in ledger or key not in snapshots for key in trade_keys):
        raise ValueError("blind trade missing from local ledger or snapshot set")

    by_pair = {(row["trade_key"], row["variant"]): row for row in blind}
    comparison_rows: list[dict[str, Any]] = []
    for key in trade_keys:
        lifecycle = _lifecycle(ledger[key])
        item: dict[str, Any] = {
            "trade_key": key,
            "side": snapshots[key]["signal"]["side"],
            "lifecycle_class": lifecycle,
            "outcome_reason": ledger[key]["outcome_reason"],
            "tp1_done": ledger[key]["tp1_done"],
            "tp2_done": ledger[key]["tp2_done"],
        }
        for variant in VARIANTS:
            blind_row = by_pair[(key, variant)]
            prefix = variant[0].lower()
            item[f"{prefix}_verdict"] = blind_row["verdict"]
            item[f"{prefix}_confidence"] = blind_row["confidence"]
            item[f"{prefix}_evaluation"] = _evaluation_bucket(lifecycle, blind_row["verdict"])
            item[f"{prefix}_setup_class"] = blind_row["setup_class"]
            item[f"{prefix}_reason_codes"] = blind_row["reason_codes"]
            item[f"{prefix}_risk_flags"] = blind_row["risk_flags"]
            item[f"{prefix}_summary"] = blind_row["summary"]
        comparison_rows.append(item)

    comparison_path = RUN_DIR / "unblinded_case_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparison_rows[0]))
        writer.writeheader()
        writer.writerows(comparison_rows)

    lifecycle_counts = Counter(row["lifecycle_class"] for row in comparison_rows)
    lines = [
        "# GPT-5.6 canonical prompt A/B/C unblinded evaluation",
        "",
        "This report joins the already frozen 60-call blind results to the local historical lifecycle ledger. No outcome field was available to the API runner. It does not select a winning prompt or authorize a production prompt change.",
        "",
        "## Integrity",
        "",
        f"- Blind rows: **{len(blind)}** across **{len(trade_keys)}** trades.",
        f"- `raw_results.jsonl` SHA-256: `{_sha256(RUN_DIR / 'raw_results.jsonl')}`.",
        f"- `verdicts_blind.csv` SHA-256: `{_sha256(BLIND_PATH)}`.",
        "- Lifecycle mapping: `tp2_done=true` → `STRONG_FAVORABLE`; otherwise `tp1_done=true` → `MIXED`; otherwise terminal `SL` → `NEGATIVE`.",
        "- Alignment is evaluated only for polar outcomes: `REJECT` for `NEGATIVE`, `SUPPORT` for `STRONG_FAVORABLE`. `MIXED` remains a separate descriptive group.",
        "",
        "## Cohort",
        "",
        "| Lifecycle | Trades |",
        "| --- | ---: |",
    ]
    for lifecycle in ("NEGATIVE", "MIXED", "STRONG_FAVORABLE", "UNKNOWN"):
        if lifecycle_counts[lifecycle]:
            lines.append(f"| {lifecycle} | {lifecycle_counts[lifecycle]} |")

    lines += ["", "## Verdict distributions", "", "| Variant | SUPPORT | REJECT | UNCLEAR |", "| --- | ---: | ---: | ---: |"]
    for variant in VARIANTS:
        counts = Counter(row["verdict"] for row in blind if row["variant"] == variant)
        lines.append(f"| {variant} | {counts['SUPPORT']} | {counts['REJECT']} | {counts['UNCLEAR']} |")

    lines += [
        "",
        "## Lifecycle cross-tab",
        "",
        "| Variant | Lifecycle | SUPPORT | REJECT | UNCLEAR |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for variant in VARIANTS:
        for lifecycle in ("NEGATIVE", "MIXED", "STRONG_FAVORABLE"):
            counts = Counter(
                row["verdict"]
                for row in blind
                if row["variant"] == variant and _lifecycle(ledger[row["trade_key"]]) == lifecycle
            )
            lines.append(f"| {variant} | {lifecycle} | {counts['SUPPORT']} | {counts['REJECT']} | {counts['UNCLEAR']} |")

    lines += [
        "",
        "## Polar-outcome alignment",
        "",
        "The denominator is the 16 polar cases: ten `NEGATIVE` and six `STRONG_FAVORABLE`.",
        "",
        "| Variant | Aligned | Clear miss | UNCLEAR | Aligned rate | Miss rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant in VARIANTS:
        relevant = [row for row in blind if row["variant"] == variant and _lifecycle(ledger[row["trade_key"]]) != "MIXED"]
        buckets = Counter(_evaluation_bucket(_lifecycle(ledger[row["trade_key"]]), row["verdict"]) for row in relevant)
        denominator = len(relevant)
        lines.append(
            f"| {variant} | {buckets['ALIGNED']} | {buckets['MISS']} | {buckets['UNCLEAR']} | "
            f"{buckets['ALIGNED'] / denominator:.1%} | {buckets['MISS'] / denominator:.1%} |"
        )

    lines += [
        "",
        "## Confidence by evaluation bucket",
        "",
        "| Variant | Bucket | Count | Mean | Median |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for variant in VARIANTS:
        for bucket in ("ALIGNED", "MISS", "UNCLEAR", "MIXED_OUTCOME"):
            values = [
                float(row["confidence"])
                for row in blind
                if row["variant"] == variant
                and _evaluation_bucket(_lifecycle(ledger[row["trade_key"]]), row["verdict"]) == bucket
            ]
            if values:
                lines.append(f"| {variant} | {bucket} | {len(values)} | {_mean(values)} | {_median(values)} |")

    misses = [
        (row["trade_key"], row["variant"], _lifecycle(ledger[row["trade_key"]]), row["verdict"], float(row["confidence"]))
        for row in blind
        if _evaluation_bucket(_lifecycle(ledger[row["trade_key"]]), row["verdict"]) == "MISS"
    ]
    lines += [
        "",
        "## Clear polar misses",
        "",
        "| Trade | Variant | Lifecycle | Verdict | Confidence |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for key, variant, lifecycle, verdict, confidence in misses:
        lines.append(f"| `{key}` | {variant} | {lifecycle} | {verdict} | {confidence:.3f} |")

    disagreements = []
    for key in trade_keys:
        verdicts = {variant: by_pair[(key, variant)]["verdict"] for variant in VARIANTS}
        if len(set(verdicts.values())) > 1:
            disagreements.append((key, verdicts))
    lines += [
        "",
        "## Cross-arm disagreements",
        "",
        f"**{len(disagreements)}/{len(trade_keys)} trades** have at least two different arm verdicts.",
        "",
    ]
    for key, verdicts in disagreements:
        lines.append(
            f"### `{key}` — {_lifecycle(ledger[key])} — "
            + ", ".join(f"{variant[0]}={verdicts[variant]}" for variant in VARIANTS)
        )
        lines.append("")
        for variant in VARIANTS:
            row = by_pair[(key, variant)]
            reasons = ", ".join(_json_list(row["reason_codes"])) or "none"
            risks = ", ".join(_json_list(row["risk_flags"])) or "none"
            lines.append(f"- **{variant[0]}** confidence {float(row['confidence']):.3f}; reasons: {reasons}; risks: {risks}.")
        lines.append("")

    lines += [
        "## Per-trade compact table",
        "",
        "| Trade | Side | Lifecycle | A | B | C |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison_rows:
        lines.append(
            f"| `{row['trade_key']}` | {row['side']} | {row['lifecycle_class']} | "
            f"{row['a_verdict']} {float(row['a_confidence']):.2f} | "
            f"{row['b_verdict']} {float(row['b_confidence']):.2f} | "
            f"{row['c_verdict']} {float(row['c_confidence']):.2f} |"
        )

    lines += [
        "",
        "## Interpretation constraints",
        "",
        "- B emitted zero `SUPPORT` verdicts and concentrated 15/20 decisions in `REJECT`; this is a class-collapse warning, not proof that B is inferior.",
        "- A and C each aligned on nine polar cases. Their miss/unclear tradeoff differs, and both treated all four mixed cases as `SUPPORT`.",
        "- This 20-trade cohort is small, historical, and partially reconstructed. The result is calibration evidence, not edge proof or production authorization.",
        "- No prompt winner is selected automatically.",
        "",
    ]
    (RUN_DIR / "UNBLINDED_EVALUATION.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"UNBLINDED_EVALUATION_COMPLETE trades={len(trade_keys)} rows={len(blind)} disagreements={len(disagreements)} misses={len(misses)}")


if __name__ == "__main__":
    main()
