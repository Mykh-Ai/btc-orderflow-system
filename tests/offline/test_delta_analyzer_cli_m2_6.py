from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer import cli


def test_build_m2_6_rejects_date_to_without_date_from(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["delta_analyzer", "--build-m2-6", "--date-to", "2026-04-05"],
    )

    with pytest.raises(SystemExit, match="--date-to requires --date-from in --build-m2-6 mode"):
        cli.main()


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["delta_analyzer", "--build-m2-6", "--date", "2026-04-05"],
            {"date": "2026-04-05", "date_from": None, "date_to": None},
        ),
        (
            ["delta_analyzer", "--build-m2-6", "--date-from", "2026-04-01", "--date-to", "2026-04-05"],
            {"date": None, "date_from": "2026-04-01", "date_to": "2026-04-05"},
        ),
        (
            ["delta_analyzer", "--build-m2-6", "--date-from", "2026-04-05"],
            {"date": None, "date_from": "2026-04-05", "date_to": "2026-04-05"},
        ),
    ],
)
def test_build_m2_6_valid_date_scopes_keep_existing_cli_behavior(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    expected: dict[str, str | None],
):
    captured: dict[str, str | None] = {}

    def _fake_build_m2_6_outputs_for_scope(
        *,
        input_root: str,
        output_root: str,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Path]:
        captured.update(
            {
                "input_root": input_root,
                "output_root": output_root,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return {
            "candidates": Path(output_root) / "m2_6" / "minute_event_chain_candidates.csv",
            "reference_cases": Path(output_root) / "m2_6" / "minute_event_chain_reference_cases.csv",
            "cluster_summaries": Path(output_root) / "m2_6" / "chain_cluster_summaries.csv",
        }

    monkeypatch.setattr(cli, "build_m2_6_outputs_for_scope", _fake_build_m2_6_outputs_for_scope)
    monkeypatch.setattr(sys, "argv", argv)

    cli.main()

    assert captured["date"] == expected["date"]
    assert captured["date_from"] == expected["date_from"]
    assert captured["date_to"] == expected["date_to"]
