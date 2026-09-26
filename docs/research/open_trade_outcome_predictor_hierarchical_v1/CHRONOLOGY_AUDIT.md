# Chronology audit before the milestone experiment

`EX_EN_1779900918` is retained in the 20-call paired comparison but excluded from the primary scored comparison for **both** predictors. The frozen Snapshot V2 bytes are unchanged.

Observed source evidence:

- Server `llm_trade_verdicts.jsonl` evidence pack for this exact key has raw `src_evt.ts` and `peak_ts_raw` of `2026-05-27 16:55:16`, without a timezone. The pack records `ts_source_timezone=Europe/Bratislava` and `timestamp_contract=legacy_feed_local_naive`; the Judge converted it to `peak_ts=2026-05-27T14:55:16Z`.
- The trade-key epoch is `2026-05-27T16:55:18Z`, two seconds after the raw signal clock. The Executor-observed fill is `2026-05-27T16:56:56.128756Z`, about 98 seconds after the key. The historical Judge verdict was created at `16:57:11Z`.
- The Executor's `event_dedup._dt_utc()` parses naive event timestamps with `utc=True`, and `open_entry_flow.handle_open_entry_event()` rejects a PEAK older than `MAX_PEAK_AGE_SEC` (default 600 seconds). This runtime path treated the raw `16:55:16` clock as current when opening the trade.
- The verified raw feed's `16:54` bar spans 75195.3–75224.5, containing the signal price 75200.0. Its `14:55` bar spans 75058.7–75083.9. This price comparison supports the 16:55 market context; it is corroboration, not a substitute for the timestamp evidence.

The frozen model view contains `peak_timestamp_utc=14:55:16Z` and `signal_to_fill_elapsed_seconds=7300.128756`, while the operational evidence supports a signal near `16:55:16Z`. The mismatch arose from incompatible interpretations of the same naive timestamp. Changing the snapshot would violate the frozen-input comparison. Both prompts will receive the same flawed input, and the trade will be shown separately as an audit case rather than counted in primary accuracy. The original 20-case result remains recorded as originally evaluated.
