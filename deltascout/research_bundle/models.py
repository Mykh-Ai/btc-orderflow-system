from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BUNDLE_VERSION = "0.1.0"
SPEC_VERSION = "0.3"
DATE_FORMAT = "%Y-%m-%d"
REQUIRED_INDEX_COLUMNS = [
    "date",
    "accepted_count",
    "reject_count",
    "interesting_reject_count",
    "close_outcome_count",
    "top_reject_reason_1",
    "top_reject_reason_1_count",
    "top_reject_reason_2",
    "top_reject_reason_2_count",
    "top_reject_reason_3",
    "top_reject_reason_3_count",
    "dominant_bucket_1",
    "dominant_bucket_1_count",
    "dominant_bucket_2",
    "dominant_bucket_2_count",
    "has_accepted",
    "has_close_outcome",
    "accepted_case_ts",
    "accepted_case_kind",
    "accepted_case_outcome_surface",
    "accepted_case_close_reason",
    "dominant_side_reject_bias",
    "contains_vwap_side_rejects",
    "contains_direction_mismatch_rejects",
    "contains_3of3_fail_rejects",
    "contains_possible_reversal_onset",
    "contains_possible_reversal_confirmation",
    "contains_possible_continuation_pressure",
    "contains_possible_trap_or_false_break",
    "notes_flag",
]


@dataclass(frozen=True)
class ScopeInfo:
    input_root: Path
    output_root: Path
    review_dirs: list[Path]
    scope_start: str
    scope_end: str

    @property
    def bundle_scope_id(self) -> str:
        return f"{self.scope_start}_to_{self.scope_end}"

    @property
    def bundle_dir(self) -> Path:
        return self.output_root / self.bundle_scope_id
