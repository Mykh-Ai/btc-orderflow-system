# Case 2 evidence gap

Trade: `EX_EN_1788166698` (2026-08-31).

`LLM_ENTRY_SNAPSHOT_V2` did not exist in this verdict's durably stored evidence pack. The journal stores the complete `evidence_pack` instead; see `case_2_evidence_pack.json`. Do not relabel that pack as an ENTRY_ONLY V2 snapshot.

EXACT_LITERAL_PROMPT_NOT_DURABLY_STORED. No prompt version or prompt SHA256 was recorded. The available repository revision of the older prompt code is dated after this trade, and no historical prompt text or matching hash was found in the examined journals or Executor log. Therefore `case_2_prompt.txt` is deliberately absent.

RAW_MODEL_RESPONSE_NOT_STORED. The parsed verdict is in `case_2_verdict.json`.
