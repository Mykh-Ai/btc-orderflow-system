# Last two real LLM Trade Judge cases: raw evidence

Read-only extraction from production `/root/volume-alert` journals copied on 2026-09-20. No model call, order, state edit, container restart, code edit, or test edit was made.

## Selection and provenance

The verdict journal has 26 records. 21 are primary successful real-model verdicts with a scored verdict and without exclusion/test markers. In descending `created_at` order the latest two are `EX_EN_1789351940` and `EX_EN_1788166698`. The newer 2026-09-19 record `EX_EN_1789841876` is an excluded manual test with `llm_call_status=error`, `verdict=ERROR_NOT_SCORED`; it produced no eligible model verdict. No later eligible row exists in this journal.

Sources: `/root/volume-alert/data/state/llm_trade_verdicts.jsonl`, `trade_execution_snapshots.jsonl`, `trade_outcomes.jsonl`, `executor_state.json`, `/root/volume-alert/data/logs/executor.log`, `/root/volume-alert/executor_mod/entry_snapshot.py`, and `/root/volume-alert/executor_mod/llm_trade_judge.py`. The last three sources were checked for prompt construction and case events; close journals were used only for identity/exclusion cross-check, never as entry-time market input.
The journal's `summary_ua` strings already contain Unicode replacement characters (U+FFFD). The verdict artifacts preserve those stored strings; the original Ukrainian wording cannot be recovered from them.

## Case 1 — 2026-09-14

- Trade `EX_EN_1789351940`; judgment `2026-09-14T02:14:27.557955+00:00`; model `gpt-5.5`; symbol `BTCUSDC`; signal `LONG` at `2026-09-14T02:12:00Z`.
- DeltaScout PEAK: `{"ts":"2026-09-14 04:12:00","kind":"long","source":"DeltaScout","action":"PEAK","delta":33.73,"vol":50.75,"imb":0.665,"price":77250.519382,"vwap":76991,"poc":77300,"price_usdt":77250.519382,"entry_usdt":77251.01,"sl_usdt":76450.0,"tp1_usdt":78052.01,"tp2_usdt":78853.02}`.
- Signal `strength` is absent from the stored event. The signal event has no `loss_filter_admission` field. The stored V2 snapshot marks Filter A and Filter B `UNKNOWN`, with `UPSTREAM_FILTER_PROVENANCE_MISSING`; it does not claim PASS.
- `case_1_entry_snapshot.json`: DURABLY_STORED complete `LLM_ENTRY_SNAPSHOT_V2` with `decision_cutoff_utc`, `signal`, `upstream_admission`, `execution_geometry`, full `market.monitor_snapshot`, `market.context`, `quality`, and `lineage`.
- `case_1_prompt.txt`: DETERMINISTICALLY_RECONSTRUCTED `LLM_ENTRY_PROMPT_V2` from that stored snapshot and server `entry_snapshot.py`; SHA256 `96264449e4000df66cda7752516f9921edd03fce83437267e6d9eaf56a18c15c` equals the stored `entry_prompt_sha256`. The literal prompt text itself was not durably stored.
- `case_1_verdict.json`: DURABLY_STORED parsed verdict. RAW_MODEL_RESPONSE_NOT_STORED.

## Case 2 — 2026-08-31

- Trade `EX_EN_1788166698`; judgment `2026-08-31T08:59:56.556435+00:00`; model `gpt-5.5`; symbol `BTCUSDC`; signal `LONG` at `2026-08-31T08:58:00Z`.
- DeltaScout PEAK: `{"ts":"2026-08-31 10:58:00","kind":"long","source":"DeltaScout","action":"PEAK","delta":30.3,"vol":47.97,"imb":0.632,"price":78476.726687,"vwap":78241,"poc":78100,"price_usdt":78476.726687,"entry_usdt":78477.22,"sl_usdt":77864.0,"tp1_usdt":79090.44,"tp2_usdt":79703.66}`.
- Signal `strength` and `loss_filter_admission` are absent. Filter A/B decisions and provenance are not durably stored for this older case; neither may be inferred as PASS.
- `case_2_evidence_pack.json`: DURABLY_STORED full `llm_trade_judge_open_v1` evidence pack, including its historical `market_monitor_snapshot` and `market_context`.
- No historical `LLM_ENTRY_SNAPSHOT_V2` was stored. EXACT_LITERAL_PROMPT_NOT_DURABLY_STORED; historical prompt version and SHA are absent. The later repository revision cannot prove the exact 2026-08-31 literal text. See `case_2_evidence_gap.md`; no fabricated snapshot or prompt file was written.
- `case_2_verdict.json`: DURABLY_STORED parsed verdict. RAW_MODEL_RESPONSE_NOT_STORED.

## Model market view: factual values

All values below are from the stored V2 snapshot for case 1 or stored v1 evidence pack for case 2. The full nested market payloads, including every zone and quality field, are in the JSON artifacts. The 5m and 30m windows are absent from both stored market views; the local monitor supplies 15m, 60m, 240m.

### Case 1: `EX_EN_1789351940`

- Market state: `ACCUMULATION`; structure state `COMPRESSION_ABOVE_SUPPORT`; candidate bias `UP`; dominant side and range quality are in `evidence_summary`: `price_change_pct=0.570; range_pct=1.214; close_position=1.000; delta_pct=-0.874; support_strength=70.0; resistance_strength=100.0; seller_pressure_score=3.1; buyer_response_score=48.3; overhead_supply_score=71.1; underlying_demand_score=49.7; dominant_side=BUYER; range_quality=BIASED; support_context=present; resistance_context=present; buyer response holds above support_upper=75969.100`.
- Current feed price: market structure `price_close=77277.0`; aggregated `last_close=77300.0`; PEAK `price=77250.519382`. These are distinct stored fields.
- Aggregated feed context: `{"rows_used":1441,"last_close":77300.0,"return_15m_pct":0.4443982431975883,"return_60m_pct":0.575086523198626,"return_240m_pct":0.43395785151885247,"volatility_60m":0.05625425580284112,"high_60m":77300.0,"low_60m":76636.0,"high_240m":77300.0,"low_240m":76389.0,"buy_qty_sum_60m":347.5877300000001,"sell_qty_sum_60m":319.41792000000004,"buy_sell_delta_60m":28.16981000000004,"buy_sell_imbalance_60m":0.042233240453060684,"cumulative_delta_24h_approx":206.7165799999994,"rolling_vwap_approx":76978.06343232344,"price_vs_rolling_vwap_pct":0.4182185850383144,"data_gaps":[]}`.
- Structure support: `{"zone_id":"significant_zone_000008","role":"SUPPORT","price_lower":73869.6,"price_upper":75969.1,"strength_score":70.0,"confidence_tier":"MEDIUM","status":"SIGNIFICANT"}`; resistance: `{"zone_id":"significant_zone_000002","role":"RESISTANCE","price_lower":78766.0,"price_upper":81377.7,"strength_score":100.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"}`.
- Data quality: `{"current":"RAW=133","context":"RAW=38881, RECOVERED_DEGRADED=4320","current_rows":133,"context_rows":43201}`; context conflicts: `[{"type":"LOCAL_BUY_FLOW_WITH_BROAD_DISTRIBUTION_CONTEXT","severity":"MEDIUM","description":"Local buy-flow context differs from broad 3d/7d market context.","evidence":{"local_60m_delta":226.403,"context_3d":"MIXED","context_7d":"BEARISH_FLOW"}}]`; signal/context gaps: `[]`.

- V2 quality: `{"status":"PARTIAL","gaps":["UPSTREAM_FILTER_PROVENANCE_MISSING"],"monitor_data_gaps":[],"entry_assessment_only":true,"future_data_allowed":false}`.

- Local 15m: `{"start_timestamp":"2026-09-14T01:58:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":15,"expected_minutes":15,"data_quality":"RAW=15","price_change_pct":0.441789,"total_qty":2592.808,"delta":305.444,"delta_pct":0.11780433,"open_interest_change":-86.85,"funding_last":0.0001,"liq_buy_qty":9.902,"liq_sell_qty":0.004}`.
- Local 60m: `{"start_timestamp":"2026-09-14T01:13:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":60,"expected_minutes":60,"data_quality":"RAW=60","price_change_pct":0.583375,"total_qty":5916.005,"delta":226.403,"delta_pct":0.03826958,"open_interest_change":96.34,"funding_last":0.0001,"liq_buy_qty":10.778,"liq_sell_qty":0.071}`.
- Local 240m: `{"start_timestamp":"2026-09-14T00:00:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":133,"expected_minutes":240,"data_quality":"RAW=133","price_change_pct":0.5695,"total_qty":14259.467,"delta":-124.579,"delta_pct":-0.00873658,"open_interest_change":25.64,"funding_last":0.0001,"liq_buy_qty":11.723,"liq_sell_qty":36.214}`.
- Broad 1d: `{"start_timestamp":"2026-09-13T02:12:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":1441,"data_quality":"RAW=1441","data_quality_flags":"OK","price_change_pct":0.033398,"total_qty":79047.587,"delta":-2372.623,"delta_pct":-0.03001512,"open_interest_change":1488.0,"funding_last":0.0001,"funding_mean":6.79713e-05,"liq_buy_qty":52.801,"liq_sell_qty":216.603,"regime_bias":"MIXED","confidence_tier":"LOW"}`.
- Broad 3d: `{"start_timestamp":"2026-09-11T02:12:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":4321,"data_quality":"RAW=4321","data_quality_flags":"OK","price_change_pct":0.492861,"total_qty":321318.227,"delta":-5780.857,"delta_pct":-0.01799106,"open_interest_change":-1888.5,"funding_last":0.0001,"funding_mean":5.49556e-05,"liq_buy_qty":479.403,"liq_sell_qty":580.449,"regime_bias":"MIXED","confidence_tier":"LOW"}`.
- Broad 7d: `{"start_timestamp":"2026-09-07T02:12:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":10081,"data_quality":"RAW=10081","data_quality_flags":"OK","price_change_pct":-3.144298,"total_qty":840558.89,"delta":-20575.966,"delta_pct":-0.02447891,"open_interest_change":-699.72,"funding_last":0.0001,"funding_mean":5.80482e-05,"liq_buy_qty":755.021,"liq_sell_qty":1685.842,"regime_bias":"BEARISH_FLOW","confidence_tier":"HIGH"}`.
- Broad 30d: `{"start_timestamp":"2026-08-15T02:12:00Z","end_timestamp":"2026-09-14T02:12:00Z","rows_used":43201,"data_quality":"RAW=38881, RECOVERED_DEGRADED=4320","data_quality_flags":"RECOVERED_DEGRADED","price_change_pct":22.620058,"total_qty":4568789.019,"delta":32122.987,"delta_pct":0.00703096,"open_interest_change":-7159.4,"funding_last":0.0001,"funding_mean":6.78304e-05,"liq_buy_qty":14540.982,"liq_sell_qty":7022.949,"regime_bias":"BULLISH_FLOW","confidence_tier":"MEDIUM"}`.
- Significant market zones: complete arrays in `case_1_entry_snapshot.json`
- Liquidity zones: `{"above_price":[],"below_price":[{"zone_id":"zone_000001","side":"SELL_SIDE","zone_type":"M15_SWING_LOW_ZONE","price_lower":76571.39515,"price_upper":76648.00485,"confidence_tier":"LOW","status":"ACTIVE","data_quality":"RAW"}]}`.

### Case 2: `EX_EN_1788166698`

- Market state: `EXPANSION_UP`; structure state `COMPRESSION_ABOVE_SUPPORT`; candidate bias `UP`; dominant side and range quality are in `evidence_summary`: `price_change_pct=1.027; range_pct=1.445; close_position=0.983; delta_pct=1.084; support_strength=100.0; resistance_strength=95.0; seller_pressure_score=3.1; buyer_response_score=62.8; overhead_supply_score=85.3; underlying_demand_score=94.7; dominant_side=BUYER; range_quality=BIASED; support_context=present; resistance_context=present; buyer response holds above support_upper=78099.000`.
- Current feed price: market structure `price_close=78448.6`; aggregated `last_close=78492.0`; PEAK `price=78476.726687`. These are distinct stored fields.
- Aggregated feed context: `{"rows_used":1441,"last_close":78492.0,"return_15m_pct":0.16973161985221863,"return_60m_pct":0.33875771792347914,"return_240m_pct":1.1025812767272916,"volatility_60m":0.051259735735507884,"high_60m":78493.0,"low_60m":77982.0,"high_240m":78493.0,"low_240m":77514.0,"buy_qty_sum_60m":428.05928000000006,"sell_qty_sum_60m":283.73875999999996,"buy_sell_delta_60m":144.3205200000001,"buy_sell_imbalance_60m":0.20275487131153114,"cumulative_delta_24h_approx":-232.54458000000037,"rolling_vwap_approx":78241.92940567645,"price_vs_rolling_vwap_pct":0.3196119986087779,"data_gaps":[]}`.
- Structure support: `{"zone_id":"significant_zone_000004","role":"SUPPORT","price_lower":77053.5,"price_upper":78099.0,"strength_score":100.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"}`; resistance: `{"zone_id":"significant_zone_000005","role":"RESISTANCE","price_lower":78958.0,"price_upper":81500.0,"strength_score":95.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"}`.
- Data quality: `{"current":"RAW=539","context":"RAW=40321, RECOVERED_DEGRADED=2880","current_rows":539,"context_rows":43201}`; context conflicts: `[{"type":"LOCAL_BUY_FLOW_WITH_BROAD_DISTRIBUTION_CONTEXT","severity":"MEDIUM","description":"Local buy-flow context differs from broad 3d/7d market context.","evidence":{"local_60m_delta":576.212,"context_3d":"BEARISH_FLOW","context_7d":"MIXED"}}]`; signal/context gaps: `[]`.

- Local 15m: `{"start_timestamp":"2026-08-31T08:44:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":15,"expected_minutes":15,"data_quality":"RAW=15","price_change_pct":0.147959,"total_qty":1530.512,"delta":186.87,"delta_pct":0.1220964,"open_interest_change":124.9,"funding_last":0.0001,"liq_buy_qty":0.528,"liq_sell_qty":0.0}`.
- Local 60m: `{"start_timestamp":"2026-08-31T07:59:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":60,"expected_minutes":60,"data_quality":"RAW=60","price_change_pct":0.319699,"total_qty":5685.614,"delta":576.212,"delta_pct":0.10134561,"open_interest_change":217.66,"funding_last":0.0001,"liq_buy_qty":9.45,"liq_sell_qty":3.868}`.
- Local 240m: `{"start_timestamp":"2026-08-31T04:59:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":240,"expected_minutes":240,"data_quality":"RAW=240","price_change_pct":1.088606,"total_qty":19268.941,"delta":1001.131,"delta_pct":0.05195568,"open_interest_change":-216.76,"funding_last":0.0001,"liq_buy_qty":32.648,"liq_sell_qty":4.349}`.
- Broad 1d: `{"start_timestamp":"2026-08-30T08:58:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":1441,"data_quality":"RAW=1441","data_quality_flags":"OK","price_change_pct":0.521774,"total_qty":121336.64,"delta":-2615.526,"delta_pct":-0.02155595,"open_interest_change":-2173.28,"funding_last":0.0001,"funding_mean":8.01961e-05,"liq_buy_qty":136.648,"liq_sell_qty":259.123,"regime_bias":"MIXED","confidence_tier":"LOW"}`.
- Broad 3d: `{"start_timestamp":"2026-08-28T08:58:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":4321,"data_quality":"RAW=4321","data_quality_flags":"OK","price_change_pct":-1.255071,"total_qty":343081.265,"delta":-7261.921,"delta_pct":-0.02116677,"open_interest_change":-2631.89,"funding_last":0.0001,"funding_mean":8.90234e-05,"liq_buy_qty":267.479,"liq_sell_qty":921.817,"regime_bias":"BEARISH_FLOW","confidence_tier":"HIGH"}`.
- Broad 7d: `{"start_timestamp":"2026-08-24T08:58:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":10081,"data_quality":"RAW=10081","data_quality_flags":"OK","price_change_pct":1.84162,"total_qty":1123440.486,"delta":-8850.448,"delta_pct":-0.00787799,"open_interest_change":-240.72,"funding_last":0.0001,"funding_mean":8.54727e-05,"liq_buy_qty":1580.204,"liq_sell_qty":2152.288,"regime_bias":"MIXED","confidence_tier":"LOW"}`.
- Broad 30d: `{"start_timestamp":"2026-08-01T08:58:00Z","end_timestamp":"2026-08-31T08:58:00Z","rows_used":43201,"data_quality":"RAW=40321, RECOVERED_DEGRADED=2880","data_quality_flags":"RECOVERED_DEGRADED","price_change_pct":24.288399,"total_qty":4214093.419,"delta":60308.303,"delta_pct":0.0143111,"open_interest_change":-2655.28,"funding_last":0.0001,"funding_mean":6.75389e-05,"liq_buy_qty":13343.888,"liq_sell_qty":5505.449,"regime_bias":"BULLISH_FLOW","confidence_tier":"MEDIUM"}`.
- Significant market zones: complete arrays in `case_2_evidence_pack.json`.
- Liquidity zones: `{"above_price":[],"below_price":[{"zone_id":"zone_000005","side":"SELL_SIDE","zone_type":"M15_SWING_LOW_ZONE","price_lower":77911.025,"price_upper":77988.975,"confidence_tier":"LOW","status":"ACTIVE","data_quality":"RAW"},{"zone_id":"zone_000003","side":"SELL_SIDE","zone_type":"M15_SWING_LOW_ZONE","price_lower":77722.5193,"price_upper":77800.2807,"confidence_tier":"LOW","status":"ACTIVE","data_quality":"RAW"},{"zone_id":"zone_000002","side":"SELL_SIDE","zone_type":"M15_SWING_LOW_ZONE","price_lower":77388.4864,"price_upper":77563.3623,"confidence_tier":"LOW","status":"TOUCHED","data_quality":"RAW"},{"zone_id":"zone_000001","side":"SELL_SIDE","zone_type":"M15_SWING_LOW_ZONE","price_lower":77312.02465,"price_upper":77389.37535,"confidence_tier":"LOW","status":"ACTIVE","data_quality":"RAW"},{"zone_id":"zone_000004","side":"SELL_SIDE","zone_type":"DOUBLE_BOTTOM_LIQUIDITY_ZONE","price_lower":77312.02465,"price_upper":77389.37535,"confidence_tier":"HIGH","status":"ACTIVE","data_quality":"RAW"}]}`.

## Side-by-side raw comparison

| FIELD | TRADE 1 | TRADE 2 |
| --- | --- | --- |
| trade_key | EX_EN_1789351940 | EX_EN_1788166698 |
| judgment timestamp UTC | 2026-09-14T02:14:27.557955+00:00 | 2026-08-31T08:59:56.556435+00:00 |
| PEAK timestamp UTC | 2026-09-14T02:12:00Z | 2026-08-31T08:58:00Z |
| side / symbol | long / BTCUSDC | long / BTCUSDC |
| model | gpt-5.5 | gpt-5.5 |
| prompt version | LLM_ENTRY_PROMPT_V2 | not stored |
| snapshot schema | LLM_ENTRY_SNAPSHOT_V2 | not stored |
| signal price | 77250.519382 | 78476.726687 |
| delta | 33.73 | 30.3 |
| volume / vol | 50.75 | 47.97 |
| imbalance / imb | 0.665 | 0.632 |
| VWAP / POC | 76991 / 77300 | 78241 / 78100 |
| Filter A | UNKNOWN | not stored |
| Filter B | UNKNOWN | not stored |
| market state | ACCUMULATION | EXPANSION_UP |
| current feed price / PEAK price | 77277.0 / 77250.519382 | 78448.6 / 78476.726687 |
| candidate bias | UP | UP |
| dominant side | BUYER | BUYER |
| range quality | BIASED | BIASED |
| 15m price change / delta / OI | 0.441789 / 305.444 / -86.85 | 0.147959 / 186.87 / 124.9 |
| 60m delta / delta_pct | 226.403 / 0.03826958 | 576.212 / 0.10134561 |
| 240m delta / delta_pct / rows | -124.579 / -0.00873658 / 133 | 1001.131 / 0.05195568 / 240 |
| 1440m (1d) delta / OI / quality | -2372.623 / 1488.0 / OK | -2615.526 / -2173.28 / OK |
| 1d / 3d / 7d / 30d regime | MIXED / MIXED / BEARISH_FLOW / BULLISH_FLOW | MIXED / BEARISH_FLOW / MIXED / BULLISH_FLOW |
| support | {"zone_id":"significant_zone_000008","role":"SUPPORT","price_lower":73869.6,"price_upper":75969.1,"strength_score":70.0,"confidence_tier":"MEDIUM","status":"SIGNIFICANT"} | {"zone_id":"significant_zone_000004","role":"SUPPORT","price_lower":77053.5,"price_upper":78099.0,"strength_score":100.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"} |
| resistance | {"zone_id":"significant_zone_000002","role":"RESISTANCE","price_lower":78766.0,"price_upper":81377.7,"strength_score":100.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"} | {"zone_id":"significant_zone_000005","role":"RESISTANCE","price_lower":78958.0,"price_upper":81500.0,"strength_score":95.0,"confidence_tier":"HIGH","status":"SIGNIFICANT"} |
| quality gaps | ["UPSTREAM_FILTER_PROVENANCE_MISSING"] | V2 quality block not stored; 30d recovered/degraded in market data |
| verdict | UNCLEAR | REJECT |
| confidence | 0.48 | 0.74 |
| setup_class | continuation_pressure | continuation_pressure |
| reason_codes | ["LOCAL_15M_60M_BUY_FLOW_SUPPORTS_LONG","PRICE_AT_60M_240M_HIGH_WITH_POSITIVE_60M_OI","DELTASCOUT_LONG_PEAK_STRONG_BUT_SAMPLE_SIZE_LOW","240M_DELTA_NEGATIVE_DESPITE_PRICE_UP","BROAD_3D_7D_CONTEXT_NOT_ALIGNED_WITH_LONG","ENTRY_INSIDE_SIGNIFICANT_NEAR_PRICE_ZONE","OVERHEAD_SUPPLY_RESISTANCE_NEAR_TARGETS","UPSTREAM_FILTER_STATUSES_UNKNOWN_NOT_PASS"] | ["local_15m_60m_240m_buy_flow_supports_direction_but_is_already_extended","entry_near_60m_and_240m_high_with_close_position_0_9825","delta_peak_is_not_strong_enough_to_justify_late_continuation_chase","price_above_vwap_and_rolling_vwap_by_about_0_3pct_indicates_stretched_entry_not_discount","high_confidence_resistance_78958_81500_sits_before_and_around_tp1","broad_3d_bearish_flow_and_1d_negative_delta_conflict_with_local_long"] |
| risk_flags | ["UPSTREAM_FILTER_PROVENANCE_MISSING","QUALITY_STATUS_PARTIAL","CONTEXT_CONFLICT_LOCAL_BUY_FLOW_VS_BROAD_DISTRIBUTION","LONG_ENTRY_NEAR_RANGE_HIGH","SIGNIFICANT_OVERHEAD_ZONE_78766_81377","TP1_BELOW_1R","30D_CONTEXT_RECOVERED_DEGRADED"] | ["late_chase_into_local_extreme","overhead_supply_resistance_near_target","tp1_inside_significant_resistance_zone","local_bullish_flow_vs_broad_bearish_context_conflict","30d_context_recovered_degraded","support_below_entry_but_not_enough_for_fresh_edge"] |
| summary_ua | Локальний імпульс підтримує лонг: 15m/60m дельта позитивна, ціна біля максимумів, OI за 60m зростає. Але 240m дельта негативна, 3d/7d фон не підтверджує лонг, вхід відбувається всередині значущої зони з близьким верхнім опором, а upstream-фільтри мають UNKNOWN provenance. Чіткого краю для SUPPORT немає, але й прямого блокера для REJECT не видно. | Лонг має локальне підтвердження потоком, але вхід зроблено майже на 60m/240m максимумі після вже розтягнутого руху. Поточний peak помірний, ціна ~0.3% вище VWAP, а сильна зона опору 78958–81500 починається до/біля TP1. Ширший 3d контекст ведмежий, тому чистої свіжої переваги для long на вході немає. |

## Factual answers

1. Latest eligible trades: `EX_EN_1789351940` (2026-09-14) and `EX_EN_1788166698` (2026-08-31).
2. DeltaScout signaled LONG for both.
3. Case 1 received the stored V2 entry snapshot in `case_1_entry_snapshot.json`; case 2 predates V2 storage and its stored historical evidence pack is in `case_2_evidence_pack.json`.
4. Yes. Their raw prices, flow windows, OI changes, broad context, zones, and quality values differ; the comparison above records values without scoring them.
5. Model verdicts: UNCLEAR and REJECT.
6. Confidence: 0.48 and 0.74.
7. Setup classes: `continuation_pressure` and `continuation_pressure`.
8. Exact reason codes and risk flags are in the comparison table and parsed verdict JSON files.
9. Case 1 literal prompt is reproducible and hash verified, but not stored as text. Case 2 exact literal prompt is neither stored nor proven reconstructable.
10. Raw unparsed model responses are not stored for either case; only parsed verdict fields remain.
