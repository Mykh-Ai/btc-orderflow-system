# Review live AB rejects — 2026-09-18

## Підсумок

| Сигнал UTC | Live blocker | Replay lifecycle | Model net USDC | Case review |
|---|---|---|---:|---|
| 2026-09-04 08:39 LONG | A | PLAIN_SL | -25.80 | REVIEWED: фільтр запобіг модельному збитку; можливий вдалий SHORT-реверс, окремий replay +34.77 USDC |
| 2026-09-14 02:09 LONG | A | TP1_TP2_TRAILING_STOP | +47.52 | REVIEWED: не рахувати як втрачений дохід — через кілька хвилин executor відкрив наступний LONG і взяв цей рух |
| 2026-09-16 17:38 SHORT | A+B | PLAIN_SL | -25.27 | REVIEWED: фільтр запобіг модельному збитку; TP1 не досягнуто |

Це три окремі case reviews, не статистичне підтвердження переваги фільтра.
Net — модель після commission/slippage, до borrow interest, для fixed notional
3000 USDC. Відхилені кандидати не були реальними відкритими угодами.

## 4 вересня: існуючий review

Перевірено попередній `rejected_peak_result_uk.md` у
`D:/Project_V/btc-orderflow-system/deltascout/research_material/backtests/scout_peak_rejected_2026-09-04_0839_v8_planb_counterfactual_v1/`.
Його corrected source of truth:
`scout_peak_rejected_2026-09-04_0839_live_agg_reference_v1/independent_trades.csv`.
LONG LIMIT fill 81074.48; SL 80513.53; TP1 не досягнуто; exit
2026-09-04 12:31 UTC; net -25.79914486127989 USDC. Попередній результат
-28.52 на enriched structural feed superseded і не використаний.

Примітка про реверс: цей епізод міг бути вдалим SHORT, а не лише відхиленим
невдалим LONG. Окремий review має мітку
`REVERSAL_SHORT_CANDIDATE / POSSIBLE_LONG_EXHAUSTION`: SHORT досяг TP1 і TP2,
а trailing закрив залишок о 16:33 UTC; modeled net +34.77 USDC до borrow
interest при 3000 USDC notional. Внутрішньохвилинний порядок перевірено за
офіційними aggTrades; використано deployed trailing 240/LR25/50/25/20.
Доказ: [reverse_short_result_uk.md](D:/Project_V/btc-orderflow-system/deltascout/research_material/backtests/scout_peak_rejected_2026-09-04_0839_reverse_short_v8_planb_v1/reverse_short_result_uk.md).
Це постфактум контрфактичний кандидат, не реальний SHORT і не правило
автоматично інвертувати всі сигнали, заблоковані A.

## 14 вересня

- Live record: `server_journals/2026-09-18/deltascout/2026-09-14.jsonl:17`.
- A=true, B=false; live percentile 33.3333%, threshold <=50%.
- LIMIT fill: 2026-09-14 02:10 UTC, 77174.08.
- Initial SL: 76425.50; TP1: 77922.66; TP2: 78671.24.
- TP1: 08:26 UTC; TP2/trailing activation: 14:32 UTC.
- Exit: 19:39 UTC; final stop 78973.97; 5 trail updates.
- Gross: +52.4269063; commission: 4.502643274812; modeled slippage: 0.40764757868.
- Net: +47.51661544650806 USDC.
- Stop-first/target-first sensitivity identical; no same-bar collision.

Review: A відхилив прибуткового кандидата. Але о 02:12 UTC був пропущений
наступний LONG, реально виконаний executor о 02:13:54 UTC; серверний log
показував net approximate +45.89476302595 USDC. Це контекст, не точне
порівняння альтернатив: replay і live PnL мають різні execution/cost models.
Не підсумовувати незалежний counterfactual із реальною угодою: single-position
executor не міг би одночасно виконати обидві.

Облікова примітка: не рахувати +47.52 USDC як втрачений дохід через AB.
Executor відкрив наступний LONG через кілька хвилин і взяв цей самий рух.
Епізод класифікується як відхилений прибутковий кандидат із подальшим
фактичним захопленням руху, а не повністю втрачена угода/дохід.

## 16 вересня

- Live record: `server_journals/2026-09-18/deltascout/2026-09-16.jsonl:31`.
- A=true, B=true; live percentile 27.2727%; OI change 60m -119.91;
  directional delta fraction 240m 0.030403967825213398 <0.06.
- LIMIT fill: 2026-09-16 17:39 UTC, 75448.07.
- Initial SL: 75955.78; TP1: 74939.73; TP2: 74431.71.
- Exit: 18:06 UTC; PLAIN_SL; neither TP filled.
- Gross: -20.1865496; commission: 4.478743904544; modeled slippage: 0.60400036256.
- Net: -25.269293867103677 USDC.
- Stop-first/target-first sensitivity identical; no same-bar collision.

Review: фільтр A+B запобіг модельному збитку приблизно 25.27 USDC:
контрфактичний SHORT закрився по початковому SL, не досягнувши TP1.
Because both A and B matched, this case does not isolate either component's edge.

## Reproducibility and boundaries

New runs:
- `ab_rejected_2026-09-14_live_agg_v8_v1/`
- `ab_rejected_2026-09-16_live_agg_v8_v1/`

Each directory contains run manifest, input/code hashes, independent trade ledger,
events, cost sensitivity and same-bar sensitivity. One rejected candidate per run.
Counterfactual admission override: `candidate-loss-filter=NONE`.
Execution: `EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2`.
Entry: `LIMIT_THEN_MARKET_90S_GUARDED_V0_1`, 90s, 0.25R guards.
V8 initial stop: volume-confirmed swing, lookback1440/LR25/buffer50/cap1200,
full window; trail: lookback240/LR25/buffer50/step25/confirm20.
Commission rate 0.000744; entry/exit/stop adverse slippage 0/1/2 bps.

Structural source: normalized archived Executor aggregator feed, converted
Europe/Bratislava to UTC. Execution source: official Binance Vision BTCUSDC
Spot 1m archives, checksum verified; open timestamps shifted +1m in memory by
the existing loader. Sep13–17 each has 1440 unique rows, zero missing/duplicates.
Normalized structural Sep12–17 each has 1440 unique rows, zero missing/duplicates.
Sep18 structural is partial; both modeled trades closed on Sep14/16.

Live AB reason/values above come from durable archive records, not replay-derived
shadow flags. The normalized structural-only feed does not contain actual OI;
derived shadow values must not replace live AB provenance.
1m OHLC replay is not exact book-ticker/partial-fill reconstruction.
No trading code, server state or live filter settings were changed.

Validation caveat: existing scout_backtester pytest suite displayed 74 test dots
and 100% without failures, but did not return a final summary/exit; interrupted
the non-terminating test process. Do not label this a clean completed suite pass.
Both replay CLI processes completed with exit code0, emitted one trade each and
empty candidate-quality issue tables. Existing dirty backtester files were preserved.
