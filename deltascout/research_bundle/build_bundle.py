from __future__ import annotations

import argparse

from .build_blocker_breakdown import BlockerBreakdownError, build_blocker_breakdown
from .build_index_summary import build_index_summary
from .build_manifest import build_manifest
from .build_raw_micro import build_raw_micro
from .build_sequence_context import build_sequence_context
from .discover_scope import ScopeDiscoveryError, discover_scope
from .select_cases import CaseSelectionError, build_selected_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeltaScout research bundle builder (P3+optional blocker diagnostics)")
    parser.add_argument("--input-root", required=True, help="Root with daily review folders")
    parser.add_argument("--output-root", required=True, help="Root where bundle outputs will be written")
    parser.add_argument("--raw-feed-root", help="Root with local raw feed CSV files")
    parser.add_argument("--max-selected-cases", type=int, default=12, help="Deterministic cap for selected cases")
    parser.add_argument("--include-blocker-breakdown", action="store_true", help="Build optional 3-of-3 diagnostics artifact")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        scope = discover_scope(args.input_root, args.output_root)
        index_path = build_index_summary(scope)
        selected_cases_path, selected_cases = build_selected_cases(scope, args.max_selected_cases)
        sequence_result = build_sequence_context(scope, selected_cases)
        raw_micro_result = build_raw_micro(scope, selected_cases, raw_feed_root=args.raw_feed_root)
    except ScopeDiscoveryError as exc:
        raise SystemExit(str(exc)) from exc
    except CaseSelectionError as exc:
        raise SystemExit(f"selected-case build failed: {exc}") from exc
    except Exception as exc:
        raise SystemExit(f"bundle build failed: {exc}") from exc

    blocker_result = None
    blocker_error = ""
    if args.include_blocker_breakdown:
        try:
            blocker_result = build_blocker_breakdown(scope, selected_cases)
        except BlockerBreakdownError as exc:
            blocker_error = str(exc)
        except Exception as exc:
            blocker_error = str(exc)

    notes = "P3 bundle: selected cases, sequence context, and raw micro built"
    note_parts = []
    if sequence_result.status == "partial":
        note_parts.append("partial sequence coverage")
    if raw_micro_result.status == "partial":
        note_parts.append("partial raw micro coverage")
    if args.include_blocker_breakdown:
        if blocker_result is not None:
            note_parts.extend(blocker_result.notes)
        elif blocker_error:
            note_parts.append(f"blocker_breakdown_unavailable: {blocker_error}")
    if note_parts:
        notes = f"{notes}; {'; '.join(note_parts)}"
    manifest_path = build_manifest(
        scope,
        index_path,
        selected_cases_path=selected_cases_path,
        sequence_context_path=sequence_result.path,
        raw_micro_path=raw_micro_result.path,
        blocker_breakdown_path=blocker_result.path if blocker_result else None,
        blocker_breakdown_requested=args.include_blocker_breakdown,
        selected_case_count=len(selected_cases),
        missing_raw_micro_case_count=raw_micro_result.missing_case_count,
        missing_sequence_case_count=sequence_result.missing_case_count,
        sequence_context_status_override=sequence_result.status,
        raw_feed_micro_status_override=raw_micro_result.status,
        blocker_breakdown_status_override=blocker_result.status if blocker_result else ("missing" if args.include_blocker_breakdown else None),
        notes=notes,
    )

    print("DeltaScout Research Bundle Build (P3)")
    print(f"bundle_scope_id={scope.bundle_scope_id}")
    print(f"scope_start={scope.scope_start}")
    print(f"scope_end={scope.scope_end}")
    print(f"daily_folder_count={len(scope.review_dirs)}")
    print(f"index_summary={index_path}")
    print(f"selected_cases={selected_cases_path}")
    print(f"selected_case_count={len(selected_cases)}")
    print(f"sequence_context={sequence_result.path}")
    print(f"sequence_context_rows={sequence_result.row_count}")
    print(f"missing_sequence_case_count={sequence_result.missing_case_count}")
    print(f"sequence_context_status={sequence_result.status}")
    print(f"raw_micro={raw_micro_result.path}")
    print(f"raw_micro_rows={raw_micro_result.row_count}")
    print(f"missing_raw_micro_case_count={raw_micro_result.missing_case_count}")
    print(f"raw_micro_status={raw_micro_result.status}")
    if args.include_blocker_breakdown:
        if blocker_result is not None:
            print(f"blocker_breakdown={blocker_result.path}")
            print(f"blocker_breakdown_rows={blocker_result.row_count}")
            print(f"blocker_breakdown_status={blocker_result.status}")
        else:
            print("blocker_breakdown=unavailable")
            print(f"blocker_breakdown_error={blocker_error}")
    print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
