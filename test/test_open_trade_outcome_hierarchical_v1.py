"""Characterization gates for the separate milestone decision contract."""
from __future__ import annotations

import json
import unittest

from docs.research.open_trade_outcome_predictor_hierarchical_v1.milestone_prompt import (
    prompt_record, validate_and_derive,
)
from docs.research.open_trade_outcome_predictor_hierarchical_v1.prepare import (
    SOURCE_BUNDLE, _check_committed_source,
)
from docs.research.open_trade_outcome_predictor_v1.run_blind import _verify_bundle


def _answer(first: str, second: str | None, *, reason=None, missing=None) -> dict:
    return {"question_1": first, "question_2": second, "confidence": 0.5,
            "primary_evidence_for": ["observed pre-cutoff fact"],
            "primary_evidence_against": ["observed counterevidence"],
            "uncertainty_reason": reason, "missing_evidence": missing or []}


class TestHierarchicalMilestoneContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pairs = _verify_bundle(SOURCE_BUNDLE)
        cls.snapshot = cls.pairs[0][1]

    def test_same_20_committed_snapshot_inputs(self) -> None:
        _check_committed_source()
        self.assertEqual(len(self.pairs), 20)
        self.assertEqual(len({row["snapshot_sha256"] for row, _, _ in self.pairs}), 20)

    def test_model_prompts_never_show_lifecycle_class_names(self) -> None:
        for _, snapshot, _ in self.pairs:
            prompt = prompt_record(snapshot)["prompt"]
            for label in ("NEGATIVE", "MIXED", "STRONG_FAVORABLE"):
                self.assertNotIn(label, prompt)
            self.assertIn("QUESTION 1", prompt)
            self.assertIn("QUESTION 2", prompt)

    def test_code_derived_classes(self) -> None:
        cases = (("SL_FIRST", None, "NEGATIVE"),
                 ("TP1_FIRST", "TP2_NOT_REACHED", "MIXED"),
                 ("TP1_FIRST", "TP2_REACHED", "STRONG_FAVORABLE"))
        for first, second, expected in cases:
            self.assertEqual(validate_and_derive(_answer(first, second), self.snapshot), expected)

    def test_second_question_is_conditional(self) -> None:
        with self.assertRaisesRegex(ValueError, "question_2 required"):
            validate_and_derive(_answer("TP1_FIRST", None), self.snapshot)
        with self.assertRaisesRegex(ValueError, "question_2 must be null"):
            validate_and_derive(_answer("SL_FIRST", "TP2_NOT_REACHED"), self.snapshot)

    def test_unclear_requires_actual_snapshot_missing_code(self) -> None:
        complete = next(snapshot for _, snapshot, _ in self.pairs if not snapshot["quality"]["missing_evidence"])
        with self.assertRaisesRegex(ValueError, "INVALID_UNCLEAR_CONTRACT"):
            validate_and_derive(_answer("UNCLEAR_MISSING_EVIDENCE", None, reason="evidence absent", missing=["invented"]), complete)
        partial = next(snapshot for _, snapshot, _ in self.pairs if snapshot["quality"]["missing_evidence"])
        code = partial["quality"]["missing_evidence"][0]
        self.assertEqual(validate_and_derive(_answer("UNCLEAR_MISSING_EVIDENCE", None, reason="specific missing fact", missing=[code]), partial), "UNCLEAR")
        self.assertEqual(validate_and_derive(_answer("TP1_FIRST", "UNCLEAR_MISSING_EVIDENCE", reason="specific missing fact", missing=[code]), partial), "UNCLEAR")


if __name__ == "__main__":
    unittest.main()
