"""Cross-platform integrity tests for the frozen GPT-5.6 A/B/C research inputs."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from docs.research.gpt56_prompt_abc.run_blind_eval import (
    TEXT_FILE_HASH_CONTRACT,
    _sha256_utf8_lf_normalized_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_COMMIT = "1ff6833f01bdb80ef0d483f8f92784c6194e4e9d"
SNAPSHOTS_REL = "docs/research/canonical_trade_evaluation_snapshot/frozen_trade_evaluation_snapshots.jsonl"
MANIFEST_REL = "docs/research/gpt56_prompt_abc/eval_manifest_blind.csv"
RENDERER_REL = "docs/research/gpt56_prompt_abc/canonical_prompt_variants.py"
PROMPTS_REL = "docs/research/gpt56_prompt_abc/rendered_prompts.jsonl"
METADATA = ROOT / "docs" / "research" / "gpt56_prompt_abc" / "run_metadata.json"


def _git_blob(relative_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "cat-file", "blob", f"{PROBLEM_COMMIT}:{relative_path}"],
        cwd=ROOT,
    )


@pytest.mark.parametrize("relative_path", [MANIFEST_REL, SNAPSHOTS_REL, RENDERER_REL])
def test_normalized_hash_is_identical_for_lf_and_crlf(relative_path: str) -> None:
    lf = _git_blob(relative_path).replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    assert _sha256_utf8_lf_normalized_bytes(lf) == _sha256_utf8_lf_normalized_bytes(crlf)


def test_non_eol_change_changes_normalized_hash() -> None:
    original = _git_blob(MANIFEST_REL)
    changed = original.replace(b"ELIGIBLE", b"ELIGIBLF", 1)
    assert changed != original
    assert _sha256_utf8_lf_normalized_bytes(changed) != _sha256_utf8_lf_normalized_bytes(original)


def test_immutable_git_tree_satisfies_metadata_hashes() -> None:
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    assert metadata["source_text_hash_contract"] == TEXT_FILE_HASH_CONTRACT == "UTF8_LF_NORMALIZED_SHA256_V1"
    assert metadata["manifest_sha256"] == _sha256_utf8_lf_normalized_bytes(_git_blob(MANIFEST_REL))
    assert metadata["snapshots_file_sha256"] == _sha256_utf8_lf_normalized_bytes(_git_blob(SNAPSHOTS_REL))
    assert metadata["renderer_source_sha256"] == _sha256_utf8_lf_normalized_bytes(_git_blob(RENDERER_REL))


def test_prepare_only_preserves_frozen_cohort_and_prompt_hashes(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m", "docs.research.gpt56_prompt_abc.run_blind_eval",
        "--manifest", str(ROOT / MANIFEST_REL),
        "--snapshots", str(ROOT / SNAPSHOTS_REL),
        "--output-dir", str(tmp_path),
        "--renderer", str(ROOT / RENDERER_REL),
        "--prepare-only",
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    assert "BLIND_PROMPTS_FROZEN trades=20 prompts=60" in completed.stdout

    prepared = [json.loads(line) for line in (tmp_path / "rendered_prompts.jsonl").read_text(encoding="utf-8").splitlines()]
    frozen = [json.loads(line) for line in _git_blob(PROMPTS_REL).decode("utf-8").splitlines()]
    assert len(prepared) == len(frozen) == 60
    assert {(row["trade_key"], row["variant"]) for row in prepared} == {
        (row["trade_key"], row["variant"]) for row in frozen
    }
    assert [row["prompt_sha256"] for row in prepared] == [row["prompt_sha256"] for row in frozen]
    assert all(row["prompt_sha256"] == hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest() for row in prepared)
