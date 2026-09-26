# Snapshot V2 predictive sufficiency audit

**Decision: `EXISTING_SNAPSHOT_HAS_WEAK_CLASS_SIGNAL` (B).** This is a descriptive, post-unblinding result on 19 trades. A few existing facts recur more often in one outcome group, especially the earlier directional Delta and final five-minute OI change for TP1 reachability. They overlap substantially, and the ten true TP1 reachers show no coherent frozen pre-outcome signature that reliably distinguishes the six TP2 reachers from the four TP1-only trades. This result neither validates a predictor nor justifies changing the frozen input.

## Evidence gate and immutability

Audited at HEAD `cf45a81f6cc2522933c71876da61800591b65201` after `git status --short`, `git rev-parse HEAD`, and `git log --oneline -n 30`. The direct blind checkpoint is commit `0c740d094e53b8bc29dd35eb8041e7dfe5fe1011`; the hierarchical blind checkpoint and chronology audit are in `cf45a81`. The following are local byte-level SHA-256 hashes:

| Artifact | SHA-256 |
| --- | --- |
| V1 `blind_run_v3/frozen_model_view_snapshots.jsonl` | `402de774d4a2a7705f0b2d7c79470ee5f2ca0254a84d9cd51b4bd0ed16d024dd` |
| V1 blind manifest | `9f1794687245cdacc8bb6bbd8f9965f9bc0975a033c57366448a0c6af7f47dac` |
| V1 frozen prompts | `4b488648b7d575b3785641cabde91b7e2641fc76c16dc011d575878454004c66` |
| V1 raw model results | `8a97f6dedb365446d435c8a3620cb277192ec922318f9cb0bce9c7811cfcdaf1` |
| Hierarchical blind manifest | `6412e434007d27435298049d8720168382dcd4a94b5f91b5423157b0a6caf2b8` |
| Hierarchical frozen prompts | `027844b1974d01add7163e832bd435a92f8689754345ed3a8496594880100311` |
| Hierarchical raw model results | `d2ed62862557937f9990822c328d5159b690ba27e4489cb10ff1fe21251e8e28` |
| Local V1 development evaluation | `d345ae8f57891b8fdbb601427c133fb943e070fd21148c4f1c38a8bb9930f662` |
| Local hierarchical paired evaluation | `e5a71b2da230e4fa47c4c0e68204777f15487d40c75f8b0b74be233d3f70e4bc` |
| Committed chronology audit | `7d7ab11868879a773f7096fd5371b81d5724102bb7390f48411224647e4fe2b3` |

The V1 run metadata records the same snapshot hash, and hierarchical run metadata explicitly names that snapshot hash and V1 source commit. The audit script reads those exact unchanged bytes. The two evaluation JSON files were **already untracked local work** at audit start, so they must not be described as committed evaluation artifacts; blind results and chronology audit are committed. Existing modified READMEs and other untracked evaluation files were left untouched. No GPT call was made.

## Cohort and methods

The paired evaluation and **committed hierarchical blind manifest** identify the same 19 score-eligible trades. The reproducible audit script uses the committed manifest as its membership source. Labels were independently recomputed from `canonical_trade_evaluation_snapshot/case_ledger.csv` (`tp2_done`, `tp1_done`, `outcome_reason`) and matched to every locally available paired-evaluation true lifecycle during this audit: **9 NEGATIVE, 4 MIXED, 6 STRONG_FAVORABLE**. `EX_EN_1779900918` is excluded from all primary summaries; see appendix. Target A compares 9 NEGATIVE to 10 TP1_REACHED. Target B compares 4 MIXED to 6 STRONG_FAVORABLE.

`run_audit.py` extracts 157 numeric fields or transparent analysis-only calculations and categorical states. `feature_distribution.csv` has one row per numeric feature per target (314 rows), including count, missing count, mean, median, min/max, quartiles, standard deviation, median difference, Hedges g where defined, rank-biserial effect, and interval overlap. `categorical_distribution.csv` holds the categorical counts, and `case_feature_matrix.csv` preserves every case's raw and direction-normalized fields. Rank-biserial is positive when group 2 tends to have larger values. Overlap ratios measure intersection divided by full span of the two IQRs/ranges; a zero IQR overlap does not establish a useful classifier with these small discrete or clustered distributions.

LONG values keep their market sign; SHORT price change and Delta are multiplied by −1 for directional comparison. Raw fields remain beside them. OI change is kept in its raw sign. Two **predeclared, analysis-only diagnostics** are calculated from existing non-overlapping segments: final 5m directional Delta percent minus preceding 10m directional Delta percent; and final 5m directional price change percent per minute minus preceding 10m counterpart per minute. Other analysis-only arithmetic is deterministic sign/quote normalization, signal price relative to VWAP/POC, risk percent, and target distance beyond directional range extremes. These are not Snapshot V2 additions or validated model features. No threshold tuning or diagnostic model was run.

## Target A: reaching TP1

| Frozen evidence | NEGATIVE (n=9) | TP1_REACHED (n=10) | Reading |
| --- | ---: | ---: | --- |
| T−240→T−60 directional Delta percent median | −0.0013 | +0.0340 | Positive in 4/9 vs 8/10; rank-biserial +0.356. Weak recurring difference. |
| Final 5m OI change median | −149.76 | −8.97 | Negative in 8/9 vs 6/10; rank-biserial +0.578. Magnitudes have outliers and signs overlap. |
| Final 5m directional Delta percent median | +0.288 | +0.260 | Positive in every case; rank-biserial −0.133. The final Delta impulse alone does not separate. |
| Final 5m directional price change percent median | +0.261 | +0.242 | Positive in every case; rank-biserial −0.178. Final price progress alone does not separate. |
| 240m directional range position median | 0.939 | 0.915 | Both usually close to the directional extreme; rank-biserial −0.156. |
| TP1 relation to selected zone: BEYOND | 5/9 | 2/9 observed | Weak geometric difference, with one reaching case lacking a selected zone. |
| TP2 relation to selected zone: BEYOND | 7/9 | 4/9 observed | Substantial overlap. |
| TP1 R median | 1.000 | 1.085 | Rank-biserial +0.400; both outcomes include approximately 1R targets. |

The earlier Delta and final OI are the strongest **descriptive** candidates. They do not form a consistent rule: four negatives have positive earlier directional Delta, and six TP1 reachers have declining final OI. Negative final impulses often have substantial price progress. Thus no observed pre-outcome sign consistently says the impulse will fail before TP1. The negative-case detail is in `negative_failure_analysis.md`.

## Target B: continuation from TP1 to TP2

| Frozen evidence | MIXED (n=4) | STRONG_FAVORABLE (n=6) | Reading |
| --- | ---: | ---: | --- |
| Final 5m directional Delta percent median | +0.295 | +0.254 | Strong cases are not consistently stronger; rank-biserial −0.333. |
| Final 5m directional price change percent median | +0.242 | +0.237 | Similar; rank-biserial +0.167. |
| Final 5m OI change median | −45.05 | +39.95 | Negative in 3/4 vs 3/6; rank-biserial +0.500, but signs split in both. |
| 3d directional price change percent median | −1.449 | +0.139 | Rank-biserial +0.417; strong cases also include −2.759 and −0.709. |
| 240m directional range position median | 0.938 | 0.901 | Strong cases span 0.176–0.964; weak stability. |
| TP2 relation to selected zone: BEYOND | 2/3 observed | 2/6 | A possible difference, but two TP2-reaching trades have TP2 beyond the zone. |
| TP2 R median | 2.193 | 2.076 | Rank-biserial −0.250; heavy overlap. |

There is **no recurring, coherent TP2-reaching pattern** in the ten frozen inputs. Final Delta, price, and OI sequences vary among the six strong trades. The strongest apparent differences use four mixed cases, are sensitive to individual cases, and conflict across feature families. See `tp2_failure_analysis.md` for all ten case sequences.

## Geometry, structure, and effort/result

The model's repeated “TP1 closer, TP2 farther or beyond range/zone ⇒ MIXED” argument is **not supported as a reliable class discriminator**. TP1 and TP2 R overlap, and approximate directional target distance beyond the 240m extreme has near-zero rank-biserial for MIXED versus STRONG (−0.083 for both targets). Selected-zone TP2 BEYOND occurs in two strong cases. Zone geometry has a weak Target A association, but it does not justify calling all strong cases mixed. The selected qualified zone itself has current price INSIDE and zero distance for every one of the 18 cases where it exists; none has a selected-zone accepted-beyond fact or recently cleared structure. The *matched registry zone* is a different, overlapping object: it has accepted-beyond-in-direction in 8/9 negatives, 2/3 observed mixed, and 3/6 strong. Its first-sweep and resweep fields also vary, but the matching is by geometric overlap, not zone identity. These counts cannot be treated as an accepted transition through the selected opposing zone.

| Structure progression fact | NEGATIVE | MIXED | STRONG_FAVORABLE |
| --- | ---: | ---: | ---: |
| Selected qualified opposing zone present | 9/9 | 3/4 | 6/6 |
| Selected zone current price INSIDE / already interacted | 9/9 | 3/3 observed | 6/6 |
| Selected zone first sweep / accepted beyond / resweep / failed acceptance | 0/9 for each | 0/3 for each | 0/6 for each |
| Recent cleared structure present | 0/9 | 0/4 | 0/6 |
| **Separate matched registry zone** accepted beyond direction | 8/9 | 2/3 observed | 3/6 |
| **Separate matched registry zone** first sweep, resweep>0, failed acceptance>0 | 4/9 for each | 0/3 for each | 2/6 for each |

The matched-registry differences are real frozen fields, but there is no proven one-to-one identity with the selected significant zone. Their interpretation is therefore a provenance question, not an established predictive signal. No first-approach selected zone can be contrasted with an already-interacted one in this cohort: every observed selected zone is already interacted and currently INSIDE.

For effort versus result, all 19 final segments have positive directional Delta percent and positive directional price change. Negative trades include high Delta with low price progress (`EX_EN_1785961338`: +0.614 Delta percent, +0.122 price percent), but a strong trade does too (`EX_EN_1784376441`: +0.296, +0.059). The opposite combination also occurs among negatives (`EX_EN_1782477849`: +0.302, +0.833). Final OI decline is more frequent in negatives but also occurs in TP1 and TP2 reachers. These are factual combinations, not an inferred market mechanism.

## Data quality and limits

The cohort is analyzable: all five non-overlapping segments are complete in all 19, OI is marked available in all 19, and all have the historical prediction-cutoff proxy. The broad 7d context is incomplete in two cases. Three cases have a degraded/recovered-feed flag (2 NEGATIVE, 1 MIXED). One MIXED lacks a selected qualified opposing zone, and one STRONG case lacks signal measurements. `signal_strength` is absent in all 19; recently cleared structure is null in all 19. Selected-zone first-sweep and acceptance timestamps do not vary. Matched-registry facts *do* vary but come from another overlapping zone. Selected significant-zone interaction counts are reconstructed as bar-overlap counts; without normalizing zone age/width, they cannot be interpreted as comparable approach or sweep counts. The zone counts cannot be given a causal market interpretation without confirming the underlying provenance and lifecycle semantics.

All comparisons use labels after outcomes were opened. There are only 19 cases, and only four MIXED; individual trades can reverse medians and rank effects. There are many correlated features, and descriptive differences were not pre-registered as predictive rules. No significance or out-of-sample performance claim is made. The exact data are in the CSVs; pairwise counterexamples are in `case_pair_analysis.md`. `feature_usefulness.csv` classifies each major family for both targets.

### Excluded chronology case: `EX_EN_1779900918`

The committed chronology audit found a raw naive signal clock of `2026-05-27 16:55:16`, interpreted by the Judge as Europe/Bratislava and converted to `14:55:16Z`, while Executor timing and the trade-key epoch support about `16:55:16Z`. The frozen snapshot consequently reports signal-to-fill delay `7300.128756` seconds, about two hours too long. It remains in the immutable 20-case model-call archive but is excluded from both A and B statistics. Its bytes were neither corrected nor re-rendered here.

## Decision and handoff

**`EXISTING_SNAPSHOT_HAS_WEAK_CLASS_SIGNAL`**: there are recurring but overlapping hints for TP1 reachability; TP2 continuation has no robust, coherent separation in the frozen fields. Continue only with the explicitly bounded hypotheses in `NEXT_RESEARCH.md` on a new frozen cohort. Do not merge the rejected predictor V1, alter Snapshot V2, or infer that a new prompt alone can recover TP2 information from these results.
