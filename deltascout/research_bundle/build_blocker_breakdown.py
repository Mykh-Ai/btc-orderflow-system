from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import ScopeInfo
from .select_cases import SelectedCase

BLOCKER_FIELDNAMES = [
    "ts",
    "kind",
    "reject_reason",
    "price",
    "vol",
    "vwap",
    "prev_price",
    "prev_vol",
    "prev_vwap",
    "price_check_pass",
    "vol_check_pass",
    "vwap_check_pass",
    "three_of_three_pass_count",
    "decomposition_status",
    "decomposition_basis",
    "notes_short",
]


@dataclass(frozen=True)
class BlockerBreakdownResult:
    path: Path
    row_count: int
    status: str
    notes: list[str]


class BlockerBreakdownError(RuntimeError):
    """Raised when blocker breakdown build fails."""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_file(review_dir: Path, prefix: str) -> Path:
    matches = sorted(review_dir.glob(f"{prefix}_{review_dir.name}.*"))
    if not matches:
        raise BlockerBreakdownError(f"missing required file in {review_dir}: {prefix}_{review_dir.name}.*")
    return matches[0]


def _to_float(value: str) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _yn(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


def _compute_checks(kind: str, price: float | None, vol: float | None, vwap: float | None, prev_price: float | None, prev_vol: float | None, prev_vwap: float | None) -> tuple[str, str, str, str, str, str]:
    if price is None or vol is None or vwap is None:
        return "", "", "", "", "partially_available", "mixed_source"
    if prev_price is None or prev_vol is None or prev_vwap is None:
        return "", "", "", "", "partially_available", "mixed_source"

    if kind == "long":
        price_pass = price > prev_price
        vol_pass = vol > prev_vol
        vwap_pass = vwap > prev_vwap
    else:
        price_pass = price < prev_price
        vol_pass = vol > prev_vol
        vwap_pass = vwap < prev_vwap

    pass_count = int(price_pass) + int(vol_pass) + int(vwap_pass)
    return _yn(price_pass), _yn(vol_pass), _yn(vwap_pass), str(pass_count), "direct_from_source_fields", "prev_fields_present"


def build_blocker_breakdown(scope: ScopeInfo, selected_cases: list[SelectedCase]) -> BlockerBreakdownResult:
    out_path = scope.bundle_dir / f"selected_case_blocker_breakdown_{scope.scope_start}_to_{scope.scope_end}.csv"
    rows_out: list[dict[str, str]] = []
    notes: list[str] = []
    any_partial = False

    reject_cache: dict[str, list[dict[str, str]]] = {}
    for case in selected_cases:
        review_dir = scope.input_root / case.session_date
        if case.session_date not in reject_cache:
            reject_cache[case.session_date] = _read_csv_rows(_find_file(review_dir, "reject_dataset"))
        reject_rows = reject_cache[case.session_date]

        row_out = {field: "" for field in BLOCKER_FIELDNAMES}
        row_out["ts"] = case.target_ts
        row_out["kind"] = case.kind
        row_out["reject_reason"] = case.reject_reason

        if case.reject_reason != "3of3_fail":
            row_out["decomposition_status"] = "not_available"
            row_out["notes_short"] = "not a 3of3_fail case"
            rows_out.append(row_out)
            any_partial = True
            continue

        match = next((row for row in reject_rows if row.get("ts", "") == case.target_ts and row.get("kind", "") == case.kind and row.get("reject_reason", "") == case.reject_reason), None)
        if not match:
            row_out["decomposition_status"] = "not_available"
            row_out["notes_short"] = "3of3 row not found in reject_dataset"
            rows_out.append(row_out)
            any_partial = True
            notes.append("prev_fields_missing_for_some_cases")
            continue

        for field in ("price", "vol", "vwap", "prev_price", "prev_vol", "prev_vwap"):
            row_out[field] = match.get(field, "")

        price = _to_float(match.get("price", ""))
        vol = _to_float(match.get("vol", ""))
        vwap = _to_float(match.get("vwap", ""))
        prev_price = _to_float(match.get("prev_price", ""))
        prev_vol = _to_float(match.get("prev_vol", ""))
        prev_vwap = _to_float(match.get("prev_vwap", ""))
        price_pass, vol_pass, vwap_pass, pass_count, status, basis = _compute_checks(case.kind, price, vol, vwap, prev_price, prev_vol, prev_vwap)
        row_out["price_check_pass"] = price_pass
        row_out["vol_check_pass"] = vol_pass
        row_out["vwap_check_pass"] = vwap_pass
        row_out["three_of_three_pass_count"] = pass_count
        row_out["decomposition_status"] = status
        row_out["decomposition_basis"] = basis
        if status == "direct_from_source_fields":
            row_out["notes_short"] = "direct source diagnostics available"
        else:
            row_out["notes_short"] = "prev fields incomplete for direct diagnostics"
            any_partial = True
            notes.append("prev_fields_missing_for_some_cases")
        rows_out.append(row_out)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BLOCKER_FIELDNAMES)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)

    status = "complete" if rows_out and not any_partial else "partial" if rows_out else "missing"
    if any(row.get("decomposition_status") == "direct_from_source_fields" for row in rows_out):
        notes.append("direct_source_diagnostics_available")
    deduped_notes = []
    for note in notes:
        if note not in deduped_notes:
            deduped_notes.append(note)
    return BlockerBreakdownResult(path=out_path, row_count=len(rows_out), status=status, notes=deduped_notes)
