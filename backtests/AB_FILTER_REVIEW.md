# Постійний журнал review AB-відхилень

Канонічний журнал результатів у цьому проєкті. Нові епізоди дописувати сюди;
не створювати нову зведену таблицю замість цього журналу. Датовані звіти та
backtest-артефакти — докази, а не заміна цього реєстру.

Case identity: signal_ts_utc + side + rule_id. Повторний прогін не дублює
епізод: додати нову revision із посиланням на попередній run та причиною
supersession. Висновки нижче перевірені 2026-09-18.

## Підсумок

### Revision: два UNKNOWN_KEEP окремо — 2026-09-18

Requested isolated single-position replay of both base-gate proxy PASS,
A PASS/B UNKNOWN candidates; not a combined21-candidate run. Frozen fail-open
admission keeps these two, without claiming B was known PASS or AB was live in
April (rollout Aug20). Original-side distance rejects, not actual trades.

- Apr27 15:19UTC SHORT: LIMIT fill15:20 at77031.58, SL77927.80;
  TP1 Apr28 11:54; noTP2; final exit Apr29 03:38, TP1_SL;
  model net **+6.679529481899948 USDC**.
- Apr29 18:10UTC SHORT: fill18:12 at75157.55, SL76156.74;
  noTP1/TP2; exit Apr30 00:40, PLAIN_SL;
  model net **-44.97853726422169 USDC**.
- Both FILLED and CLOSED; total model net **-38.299007782321745 USDC**.

Same execution/cost/input parameters as known19: oneOPEN/PENDING and180s
cooldown, fixed3000USDC, V8 initial1440/LR25/buffer50/cap1200/full window;
trail240/LR25/buffer50/step25/confirm20, guarded90s PlanB0.25R;
commission0.000744 and slippage0/1/2bps, before borrow interest.
First position closed before second signal; no inter-candidate position block.
These April windows carry degraded enrichment; OI remains B UNKNOWN. Lifecycle
uses actual normalized legacy structural prices/volume and official Spot,
not original synthetic SHI price rows. Existing clock/1m assumptions retained.

CLI exited0, candidate_count2, selected UTC/side identities exactly matched;
candidate_quality empty; same-bar sensitivity reviewed in linked artifact.
All original evidence and earlier runs preserved. Derived archive keeps complete
DELTA history and omits150 unselected distance terminal records, never fabricates
PEAKs. Selection manifest retains source/derived/audit/runner hashes and exact
CLI args copied from known19 reference. No server/network/trading change.

Evidence: [run manifest](vwap_distance_unknown2_single_position_20260918_v1/run_manifest.json),
[two-position ledger](vwap_distance_unknown2_single_position_20260918_v1/portfolio_trades.csv),
[same-bar sensitivity](vwap_distance_unknown2_single_position_20260918_v1/same_bar_sensitivity.csv).
Selection: `server_journals/vwap_unknown2_20260918_v1/selection_manifest.json`;
runner `backtests/run_vwap_unknown2.py`.
Do not add this isolated result to known19 to report full fail-open21 portfolio:
cross-cohort competition requires a separately requested merged run. Neither
isolated run merges actual admitted PEAKs or measures actual lost live income.
Status: UNKNOWN_KEEP2_ISOLATED_REPLAY_COMPLETE.

### Revision: known A/B PASS19 single-position replay — 2026-09-18

COMPLETED_AS_OF_CUTOFF17:04UTC, Sep18 partial day; one hypothetical position
still open. Requested strict-known cohort only: audited base-gate proxy PASS,
A=false and B=false. Both recovery B-unknown candidates excluded; no fail-open21
scenario run. This is an isolated portfolio of distance-rejected candidates,
not a reconstruction of the full strategy merged with actually admitted PEAKs.

**19 candidates ->17 FILLED, 2 Plan B deviation ABORTED; 16 closed /1 open.**
No OPEN/PENDING/cooldown blocks or initial-stop-cap blocks in this selected
portfolio. Two aborts: Jul31 14:06UTC SHORT, Sep15 13:38UTC SHORT.
Closed lifecycles: 9 PLAIN_SL, 2 TP1_SL, 5 TP1_TP2_TRAILING_STOP.

- Closed-position net: **-50.62067800498671 USDC**.
- Remaining position realized partial-leg net: **+39.978509373241515 USDC**.
- Total realized net incl. those closed legs: **-10.642168631745182 USDC**.
- Closed-position max drawdown: **254.140698030365 USDC** (not intratrade MTM DD).

Open third-leg mark-to-market is not included; do not describe -10.64 as the
final result of all17 positions. Net includes pinned commission/slippage,
before margin borrow interest. Fixed3000USDC notional per position, no compounding.
Do not infer a validated edge or lost live income from this sparse counterfactual.

Sep18 13:41UTC LONG is **actually modeled FILLED in this corrected cohort**,
not blocked by the inadmissible Sep17/13:39 raw DELTAs from earlier forced runs:

- LIMIT fill Sep18 13:42UTC, 78924.88; modeled improvement versus planned limit.
- Initial SL77860.93; TP180099.16 at13:52UTC, TP281218.28 at16:34UTC.
- Remaining third qty0.01267, trailing still open through17:04UTC; one trail
  update, final observed modeled stop80433.98. Realized partial net+39.98.
- This is not an exchange position or exact exchange fill chronology.

Source selection is explicit and reproducible: local derived raw archive
retains all187 daily files, every original DELTA_MAX/MIN and all non-distance
records; retains only19 selected distance terminal rejects and omits133 other
distance rejects. No reject renamed/fabricated as PEAK and immutable originals
unchanged. Full same-side DELTA history preserved. The normal CLI compiles19;
candidate-loss-filter NONE prevents reapplying structural-only shadow B UNKNOWN.
Authoritative preselection A/B comes from prior enriched-feed audit, not the
normalized replay shadow flags (which remain structural-only and may say UNKNOWN).
Selection manifest records audited cases, source/derived hashes, runner hash,
audit hash and exact CLI arguments.

Policy unchanged from prior152 run: V8 initial1440/LR25/buffer50/cap1200/full
window; trail240/LR25/buffer50/step25/confirm20; guarded90s Plan B,0.25R,
one OPEN/PENDING plus180s cooldown. Commission0.000744; slippage0/1/2bps.
Same structural/official Spot snapshot and recovery sidecar; cutoff17:04UTC.
Prior feed-quality/segment-threshold/EMA-proxy/historical frozen-AB caveats remain.

Validation: CLI exited0; manifest candidate_count19 and cooldown180 confirmed;
selected timestamp/side identities match normalized candidates exactly;
candidate_quality empty, zero filled-position overlaps, same-bar target-first
sensitivity unchanged for all19; offline backtester suite **86 passed in0.90s**.
Generic generated summary.md targets ALMOST cohorts and is not an authoritative
summary for this experiment; use portfolio_trades and this journal revision.
Parity table against actual outcomes is not proof of live execution of these
rejected DELTAs; no actual full-strategy opportunity-cost attribution performed.

Evidence: [manifest](vwap_distance_admitted19_single_position_20260918_v1/run_manifest.json),
[portfolio ledger](vwap_distance_admitted19_single_position_20260918_v1/portfolio_trades.csv),
[same-bar sensitivity](vwap_distance_admitted19_single_position_20260918_v1/same_bar_sensitivity.csv),
[cost sensitivity](vwap_distance_admitted19_single_position_20260918_v1/cost_sensitivity.csv),
[drawdown](vwap_distance_admitted19_single_position_20260918_v1/drawdown.csv).
Run fingerprint `d9f6229f554eb389e042082470530fc063c93bada2e4761cc8b67bdda299772b`.
Selection manifest: `server_journals/vwap_known19_20260918_v1/selection_manifest.json`;
runner: `backtests/run_vwap_known19.py`. No server/network operation, runtime
change, commit or push. Earlier raw152/96 runs preserved but not the answer to
this admission-screened cohort. Next only when requested: fresh closed-candle
revision for remaining trail, or full strategy comparison with admitted PEAKs.

### Revision: A/B audit після базових gates — 2026-09-18

Перевірено 27 base-gate proxy PASS та окремий rounded-imb UNKNOWN за frozen
`DS_PEAK_LOSS_AVOIDANCE_UNION_V1`. Це offline counterfactual, не запис live
виклику AB для distance rejects. Rollout AB задокументований Aug20; застосування
цієї політики до березня–серпня до rollout є ретроспективним порівнянням,
а не твердженням, що тоді AB працював у veto mode.

Для основних27: **19 KEEP, 6 BLOCK, 2 UNKNOWN_KEEP**.
A matches4, B matches4, overlap2, union6. True means blocker match.
Шість додаткових veto-кандидатів (UTC):

- Mar30 08:06 LONG: B.
- Apr02 08:49 SHORT: A.
- May23 07:08 SHORT: A.
- May24 06:52 LONG: A+B.
- Jun07 22:15 LONG: B.
- Aug25 20:45 SHORT: A+B.

UNKNOWN_KEEP: Apr27 15:19 SHORT та Apr29 18:10 SHORT. A PASS; B UNKNOWN:
240m window overlaps recovered WS-gap data with copied/forward-filled OI.
Corrected recovery flow remains a diagnostic, not a trusted B determination.
Do not count these two as both-known PASS. Frozen unknown/fail-open scenario
would retain them (21 policy-kept candidates), strict-known-only cohort has19.
This does not reconstruct actual historical circuit, elapsed-budget, state/audit
I/O failures or deployment mode; no exact historical effective_action invented.

Resolved prior remaining base UNKNOWN: Apr02 09:00 UTC SHORT has exact legacy
imbalance0.6902230579700575 > observed upper0.69; **base BLOCKED_IMB**.
Its A/B values both PASS do not rescue it. Updated funnel all152:
125 base blockers +6 additional frozen AB blockers +19 known-policy KEEP
+2 B-unknown =152. Base gates retain the segment-config/EMA-proxy caveats of
the previous revision. This is not yet a filled-trade count or PnL.

**Sep18 13:41 UTC LONG: A PASS, B PASS.** Same-side24h sample12,
percentile83.3333 >50. OI change60m -283.69; directional flow240m
0.08675252188769061 (8.6753%) >=0.06, so falling OI alone does not trigger B.
Base gates also proxy PASS; candidate remains eligible for a corrected entry
replay, subject to Executor stop/fill/state guards. No borrowing/order implied.

Method A: include every same-side DELTA_MAX/MIN in inclusive trailing24h,
deduplicate timestamp/side/abs-delta, rank <= rounded signal delta. Reconstruct
full-precision runtime-recorded deltas from legacy BuyQty-SellQty for the active
sequence segment; older bootstrap values remain rounded archive values. The
current sample is counted but can exceed its rounded signal delta and therefore
not contribute to the percentile numerator. Naively rounding all history had
produced wrong rank values; corrected reconstruction matches all6 archived live
DECISION controls exactly for count/rank/A/B and numerical B values within1e-7.
Additional all-prior-rounded bootstrap sensitivity: A blocker classifications
unchanged for all28 reviewed cases. Runtime cache recovery/persistence itself is
not replayed; controls support the calculation, not perfect historical cache proof.

Method B: source actual enriched SHI CSV with UTC completed-minute labels, exact
240 contiguous bars from cutoff-239 through cutoff, no future rows/duplicates/
synthetic rows; directional(Buy-Sell)/(Buy+Sell), sign adjusted for SHORT.
OI change uses final60 bars' last minus first (cutoff minus cutoff-59m), matching
the inspected runtime. Consult corrected recovery quality sidecar; untrusted
overlap stays B UNKNOWN. No OI inferred from structural-only legacy feed.

Evidence: [A/B summary](vwap_ab_admission_audit_20260918_v2/summary.json),
[all28 records](vwap_ab_admission_audit_20260918_v2/cases.jsonl),
[six live controls](vwap_ab_admission_audit_20260918_v2/live_validation.jsonl).
Reproducible script `backtests/audit_vwap_ab.py`; summary retains script/pure
policy/quality hashes, all187 legacy source hashes and every enriched input path/
hash. Research JSONL hashes are retained in the preceding base audit summary.
No network/server operation, no runtime imports/state writes, no trading-code
changes, commits or pushes. Pure stateless policy function imported offline only.
Status: FROZEN_AB_AUDITED; two B values UNKNOWN; CORRECTED_PORTFOLIO_NOT_RUN.
Next only when requested: rerun single-position portfolio after this admission
selection, report known19 and fail-open21 separately, merge/contextualize actual
admitted PEAKs if assessing the full strategy rather than the isolated cohort.

### Revision: admission audit усіх 152 DELTA — 2026-09-18

**Попередні PnL -273.94 / -432.11 не є результатом вимкнення лише
VWAP-distance.** Це примусовий replay сирих DELTA без решти Scout admission
gates; їхня інтерпретація як ефект distance-фільтра superseded. Immutable
run directories нижче збережені, самі розрахунки не переписані.

Перевірено всі 152 recorded distance rejects з того самого snapshot:

- 44 не виконують 3/3. Серед них 39 мають недостатній об'єм, 11 — неправильний
  рух ціни, 1 — VWAP; компоненти перетинаються, їх не підсумовувати.
- Зі 108, що виконують 3/3, 70 не виконують imbalance band за єдиними
  thresholds, спостереженими в тому самому research-sequence segment.
- Ще 10 із решти блокуються реконструйованими EMA/VWAP або chop/coherence gates.
- 27 проходять реконструйовані базові gates; **historical AB unresolved**.
- 1 має UNKNOWN на округленій межі imbalance; не зараховувати до PASS.

Це 124 additional base blockers, 27 base-gate proxy PASS і 1 unresolved.
Не називати 27 допущеними PEAK чи втраченими угодами: OI/історичний AB,
актуальна версія політики та взаємодія з реально допущеними PEAK не доведені.
Правильний новий portfolio потребує відбору після admission; просте віднімання
PnL відкинутих рядків неправильне через зміну single-position competition.

Method: sequential reconstruction of prev_peak from DELTA_MAX/MIN, resets on
non-increasing seq and explicit no_prev_peak; every candidate retains current/
previous records and source line. Rounded volumes near equality remain UNKNOWN;
SHORT requires falling price/VWAP but rising volume. 410 recorded 3of3_fail
previous-value references matched reconstructed predecessor; zero mismatches.
7 sequence segments, 6 explicit no_prev resets. Segment thresholds are inferred
from actual PEAK/gate records, not assumed current defaults; this is not a
deployment-history proof. Imbalance rounding boundary remains UNKNOWN.

Market context reconstructed offline from immutable legacy ClosePrice, BuyQty,
SellQty using the inspected Scout formulas: EMA50 adjust=False continuous proxy,
chop over 30 closes, coherence over 10 buy/sell bars; current research VWAP retained.
Checked against 335 recorded live gate/PEAK contexts: zero price, EMA (>0.01 USD),
chop (>0.00501), coherence (>0.000501) mismatches. This supports the reconstruction
but does not prove exact rolling-file EMA for unobserved cases. Existing feed
gaps/quality caveats remain; no historical OI substituted or AB PASS fabricated.

Specific corrections:

- Sep17 12:32 UTC LONG: volume125.22 ->107.91; 3/3 FAIL; imbalance also outside
  observed band. Even without distance this is not a base-admissible LONG.
  The previous modeled +41.17 and hypothetical carry-forward blocking Sep18
  illustrate forced raw-DELTA replay only, not a distance-only counterfactual.
- Sep18 13:39 UTC: 3/3 PASS, imbalance0.760 outside observed band0.54–0.69.
- Sep18 13:41 UTC: reconstructed base gates PASS, AB NOT_EVALUATED.
  An entry here cannot be rejected merely because the inadmissible13:39 DELTA
  produced a hypothetical pending position in the previous raw-DELTA run.
- Sep18 13:51 UTC: volume249.97 ->249.67; 3/3 FAIL.

Evidence: [audit summary](vwap_admission_audit_20260918_v3/summary.json),
[all152 admission records](vwap_admission_audit_20260918_v3/cases.jsonl),
offline reproducible script `backtests/audit_vwap_admission.py` (hash retained
in summary), hashes of all187 input JSONLs retained. Initial v1 3/3-only audit
and v2 market-context audit are preserved as intermediate artifacts.
No live imports/API calls, server writes, trading changes, commits or pushes.
Status: BASE_ADMISSION_AUDITED; FULL_ADMISSION_AND_CORRECTED_PORTFOLIO_PENDING.

### VWAP-distance DELTA tooling — 2026-09-18

IMPLEMENTED; historical replay completed below (closed candles through 17:04 UTC).
Це окрема non-AB вибірка:
`VWAP_DISTANCE_REJECT`, direct raw JSONL counterfactual original-side DELTA,
`PRE_ADMISSION_REJECT`; наступні gates не доведені. Опція
`--vwap-distance-min-usd 1200` вибирає строго >1200; без опції всі recorded
distance rejects. Live DeltaScout/Executor не змінені. Виявлені раніше 152
історичні кандидати (96 >1200) мають результати single-position replay нижче.
Validation: 86 offline scout_backtester tests passed; actual Sep18 raw archive
compiled 3 LONG candidates at 13:39/13:41/13:51 UTC, zero quality issues.
Source/runbook: `D:/Project_V/btc-orderflow-system/docs/runbooks/SCOUT_REPLAY_BACKTESTER.md`.
Надалі дописати aggregate replay/run links і data coverage в окремий non-AB
розділ цього журналу; не змішувати статистику з трьома AB reviews нижче.

### VWAP-distance single-position portfolio — run 2026-09-18

Reviewed_at_utc: 2026-09-18; evidence collected 17:04 UTC. COMPLETED_AS_OF_CUTOFF,
not a final full-day result: the current day is partial and one position remains open.
These are original-side DELTA counterfactuals, not actual trades or AB rejections.
Only VWAP_DISTANCE_REJECT candidates compete in this hypothetical portfolio;
actual admitted PEAKs are not merged into it. Start flat at beginning of history;
carry a position across days, allow one OPEN/PENDING position and 180s cooldown.

| Isolated cohort | Candidates | Filled positions | Closed / still open | Blocked OPEN/PENDING | Closed-position model net USDC | Realized model net including open-position closed legs |
|---|---:|---:|---|---:|---:|---:|
| All distance rejects | 152 | 59 | 58 / 1 | 79 (76 OPEN, 3 PENDING) | -315.11 | -273.94 |
| Distance strictly >1200 | 96 | 39 | 39 / 0 | 45 (42 OPEN, 3 PENDING) | -432.11 | -432.11 |

All cohort closed lifecycle: 30 PLAIN_SL, 13 TP1_SL, 15 TP1_TP2_TRAILING_STOP.
Remaining position is TP1_TP2_OPEN_TRAIL, with realized partial-leg net +41.17.
Other outcomes: 9 candidates blocked by NO_SWING_WITHIN_INITIAL_STOP_CAP,
5 Plan B entries aborted for excessive deviation. Model max drawdown 489.84 USDC.
>1200 cohort: 23 PLAIN_SL, 5 TP1_SL, 11 TP1_TP2_TRAILING_STOP;
9 initial-stop-cap blocks, 3 Plan B aborts; model max drawdown 491.41 USDC.
Do not add cohort PnLs: they overlap and have different position competition.
No mark-to-market PnL for the remaining third leg is included.

Today's illustration, historical carry-forward run: hypothetical LONG from
2026-09-17 12:32 UTC filled 12:33 at 76968.73, TP1 Sep18 08:59,
TP2 Sep18 13:45, remaining trail open through the cutoff. Therefore all three
Sep18 candidates (13:39,13:41,13:51 UTC) are POSITION_ALREADY_OPEN blocks;
none creates an additional trade. This is simulated carry-forward, not a claim
that production held this position.

Separate today's-flat diagnostic (do not sum with historical run): zero fills.
13:39 LIMIT did not fill; guarded Plan B aborts because modeled deviation
442.46 > allowed151.6475 USDC (0.25R). 13:41 is POSITION_PENDING_ENTRY under
the conservative completed-minute timeout proxy. 13:51 has no eligible initial
swing inside the $1200 stop cap. The first delta does not guarantee an entry:
single-position restrictions coexist with entry/initial-stop guards. Exact 90s
ordering requires finer data; completed-minute proxy conservatively includes
the timeout bar when testing concurrent candidates.

Run evidence:
- [All152 manifest](vwap_distance_single_position_20260918_v1/run_manifest.json)
- [All152 portfolio trades](vwap_distance_single_position_20260918_v1/portfolio_trades.csv)
- [>1200 manifest](vwap_distance_single_position_gt1200_20260918_v1/run_manifest.json)
- [>1200 portfolio trades](vwap_distance_single_position_gt1200_20260918_v1/portfolio_trades.csv)
- [Today-flat manifest](vwap_distance_single_position_today_flat_20260918_v1/run_manifest.json)
- [Today-flat trades](vwap_distance_single_position_today_flat_20260918_v1/portfolio_trades.csv)

Inputs: immutable archive snapshot under
`server_journals/vwap_portfolio_2026-09-18/`, 187 daily research JSONLs and
legacy feed files, normalized Europe/Bratislava to UTC; 152 compiled candidates,
zero candidate-quality issues. Reused official cached/checksum-verified BTCUSDC
Spot 1m daily files through Sep17, plus public Spot REST closed Sep18 bars
(1024 rows, open labels, cutoff completed17:04 UTC; not Vision daily archive).
Collection manifest retains raw-response/archive hashes and cache provenance.
Signal sidecar: research_material/recovery_clock_v2_2026-09-08/quality, labeling
the known Apr23–May6 window degraded; structural prices/volume are actual
normalized legacy archive, no trusted historical OI/funding inferred.
Structural archive has 2 missing minutes Jun15 and 1 Aug12; no duplicate minutes.
Do not claim perfectly gap-free coverage. No portfolio-unknown/feed blocks were
reported by the existing engine, but its classification does not remove this caveat.
Stop-first/target-first independent sensitivity: no lifecycle/PnL changes for
all152 or96 candidates. Concurrent filled-position overlap check: zero violations.
All three replay CLI processes exited0; existing offline suite previously86 passed.

Policy: V8 initial1440/LR25/buffer50/cap1200/full-window; deployed
trail240/LR25/buffer50/step25/confirm20; guarded LIMIT_THEN_MARKET90s,0.25R;
3000USDC per position, commission0.000744, slippage entry/exit/stop0/1/2bps.
Net is modeled realized PnL after costs, before borrow interest. This is not
historical exchange PnL or the isolated causal effect of removing VWAP admission.
Conclusion: this isolated distance-reject portfolio is net negative at cutoff;
no filter/strategy change is justified from this run alone. Next action only
when requested: append a fresh cutoff revision once remaining trailing position
closes; preserve all current run directories and snapshots.

| Сигнал UTC | Live blocker | Replay lifecycle | Model net USDC | Case review |
|---|---|---|---:|---|
| 2026-09-04 08:39 LONG | A | PLAIN_SL | -25.80 | REVIEWED: фільтр запобіг модельному збитку; можливий вдалий SHORT-реверс, окремий replay +34.77 USDC |
| 2026-09-14 02:09 LONG | A | TP1_TP2_TRAILING_STOP | +47.52 | REVIEWED: не рахувати як втрачений дохід — через кілька хвилин executor відкрив наступний LONG і взяв цей рух |
| 2026-09-16 17:38 SHORT | A+B | PLAIN_SL | -25.27 | REVIEWED: фільтр запобіг модельному збитку; TP1 не досягнуто |
| 2026-09-25 11:08 LONG | B | PLAIN_SL | -45.88 | REVIEWED: B ізолюється; фільтр запобіг модельному збитку; TP1 не досягнуто |

Це чотири окремі case reviews, не статистичне підтвердження переваги фільтра.
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

## 25 вересня

- Live record:
  `D:/Project_V/btc-orderflow-system/deltascout/research_material/server_journals/2026-09-25_ab_reject/deltascout/2026-09-25.jsonl:33`.
- A=false, B=true; live percentile 100% on 11 same-side peaks.
- B inputs: trusted OI change 60m `−339.44`; direction-adjusted 240m delta
  fraction `−0.007374200820933429` (`−0.73742%`) < `0.06`.
- LIMIT fill: 2026-09-25 11:09 UTC, `85047.66` BTCUSDC.
- Initial SL: `83889.32`; TP1: `86206.00`; TP2: `87364.34`.
- Exit: 12:18 UTC completed-minute replay label; `PLAIN_SL`; neither TP filled.
- Gross: `−40.8546518`; commission: `4.4330550197424`; modeled slippage:
  `0.59175526328`.
- Net: **`−45.879462083022275 USDC`** before borrow interest.
- Stop-first/target-first sensitivity identical; no same-bar collision.

Review: це перший ізольований у постійному case-review реєстрі епізод, де
спрацював лише B і актуальний V8 replay завершився Plain SL. На цьому конкретному
сигналі B запобіг модельному збитку приблизно 45.88 USDC. Один випадок не є
статистичним підтвердженням самостійної переваги B.

Coverage check: daily archives за Sep17–25 не містять інших
`PEAK_LOSS_FILTER_REJECT`; це єдине нове A/B-відхилення після review Sep16.

Full evidence:
`D:/Project_V/btc-orderflow-system/deltascout/research_material/backtests/ab_rejected_2026-09-25_1108_live_agg_v8_v1/rejected_peak_result_uk.md`.

## Reproducibility and boundaries

New runs:
- `ab_rejected_2026-09-14_live_agg_v8_v1/`
- `ab_rejected_2026-09-16_live_agg_v8_v1/`
- `D:/Project_V/btc-orderflow-system/deltascout/research_material/backtests/ab_rejected_2026-09-25_1108_live_agg_v8_v1/`

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
derived shadow values must not replace live AB provenance. For Sep25 the replay
therefore intentionally used `candidate-loss-filter=NONE`; the archived live
record remains the source of truth for B=true.
1m OHLC replay is not exact book-ticker/partial-fill reconstruction.
No trading code, server state or live filter settings were changed.

Validation caveat: existing scout_backtester pytest suite displayed 74 test dots
and 100% without failures, but did not return a final summary/exit; interrupted
the non-terminating test process. Do not label this a clean completed suite pass.
The Sep25 case was run after a separate clean completed suite result of
`86 passed in 0.92s`; this validates the current local backtester code for that
case but does not retroactively change the older run fingerprint.
Both replay CLI processes completed with exit code0, emitted one trade each and
empty candidate-quality issue tables. Existing dirty backtester files were preserved.

## 28 вересня: контрфактична A/B-перевірка двох VWAP-distance кандидатів

Ці два SHORT-кандидати не є live A/B-відхиленнями: DeltaScout зупинив їх раніше
на `CANDIDATE_COMPARISON_REJECT / vwap_distance`, тому live
`PEAK_LOSS_FILTER_DECISION` не існує. На запит виконано cutoff-safe офлайн
оцінку точної чинної політики `DS_PEAK_LOSS_AVOIDANCE_UNION_V1` на архівних
DeltaScout/legacy feed та production enriched feed. Усі 240 enriched хвилин в
обох вікнах присутні, унікальні й `IsSynthetic=0`.

| Signal UTC | Bratislava | A percentile / sample | OI change 60m | Directional delta 240m | A | B | Counterfactual |
|---|---|---:|---:|---:|---|---|---|
| 2026-09-28 05:39 SHORT | 07:39 | 77.7778% / 9 | -163.92 | 0.13101015 | PASS | PASS | KEEP |
| 2026-09-28 09:21 SHORT | 11:21 | 90.0000% / 10 | +78.48 | 0.02757399 | PASS | PASS | KEEP |

A блокує лише percentile `<=50%`; обидва кандидати сильніші за цю межу. Для B
потрібні одночасно `OI change 60m < 0` та directional delta fraction `<0.06`.
О 05:39 OI падав, але directional flow `0.1310` був сильнішим за межу. О 09:21
flow був слабшим за межу, але OI зростав. Тому B=false в обох випадках, union
false, рішення `KEEP`.

Окрема cutoff-safe реконструкція решти detector gates виконана тими самими
формулами, порядком хвилин і чинними production thresholds
`CHOP30_MAX=3`, `COH10_MIN=0.30`, `IMB_MIN=0.54`,
`IMB_MAX=0.69`. Live-код не дійшов до цих перевірок через попередній
`vwap_distance`, тому значення нижче є офлайн-контрфактом.

| Signal UTC | Close / EMA50 | Close / VWAP | CHOP30 | COH10 | Imbalance | Result after 3/3 |
|---|---:|---:|---:|---:|---:|---|
| 2026-09-28 05:39 SHORT | 82706 / 83192.386 | 82706 / 84319 | 1.4529 PASS | 0.5521 PASS | 0.67236 PASS | all remaining gates PASS |
| 2026-09-28 09:21 SHORT | 82908 / 82876.227 | 82908 / 83899 | 2.8973 PASS | 0.3664 PASS | 0.67345 PASS | EMA50 regime FAIL |

Отже CHOP і COH проходять в обох випадках. 05:39 UTC пройшов би всі наступні
detector gates, після чого A/B дав би `KEEP`. 09:21 UTC, навіть без
VWAP-distance reject, зупинився б на SHORT EMA50 regime: detector використовує
`ClosePrice`, а `82908` вище EMA50 `82876.227` на `31.773`. Він не
дійшов би до live A/B admission і PEAK не був би емітований.

Evidence: `backtests/ab_counterfactual_2026-09-28_vwap_distance_v1/results.json`.
Detector-gate evidence:
`backtests/ab_counterfactual_2026-09-28_vwap_distance_v1/detector_gate_results.json`.
No production files, state, configuration, services or orders were changed.

V8 initial-stop follow-up: обидва кандидати мали eligible structural swing і не
були б скасовані через cap `$1200`. Для 05:39 UTC planned entry `82818.40`,
selected swing high `83534` о 07:01 Bratislava, stop `83584`, distance `$765.60`;
1 eligible із 10 confirmed. Для 09:21 UTC planned entry `82888.99`, selected
swing high `83030` о 10:55 Bratislava, stop `83080`, distance `$191.01`; 4
eligible із 13 confirmed. Це перевірка лише V8 stop selection; вона не доводить
проходження проміжних detector gates. Evidence:
`backtests/ab_counterfactual_2026-09-28_vwap_distance_v1/v8_stop_results.json`.
