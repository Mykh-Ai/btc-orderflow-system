# Minute Events Cross-Day Evidence Review (2026-03-17 to 2026-04-04)

## 1. Purpose

This memo reviews whether the currently implemented minute-event layers already produce useful cross-day outcome separation.

It is **not**:

- a new analyzer spec
- a taxonomy proposal
- a setup-validation document
- a PEAK reinterpretation pass

It is an evidence review over the existing M1, M2a, and M2.5 datasets to determine:

- what the current minute stack already explains
- what it still fails to explain
- whether the next analyzer move should be M2b, early typing, or outcome refinement

---

## 2. Data Coverage

### Date coverage

Target range:

- 2026-03-17 through 2026-04-04

Available datasets:

- `minute_events_base_YYYY-MM-DD.csv`
- `minute_events_mechanics_YYYY-MM-DD.csv`
- `minute_events_outcomes_YYYY-MM-DD.csv`

Coverage result:

- all dates in the target range were present
- no day was missing one of the three minute datasets

### Row counts

Total reviewed rows:

- `26,872`

Per-day rows:

| Date | Rows |
| --- | ---: |
| 2026-03-17 | 1440 |
| 2026-03-18 | 1440 |
| 2026-03-19 | 1440 |
| 2026-03-20 | 1440 |
| 2026-03-21 | 1440 |
| 2026-03-22 | 1440 |
| 2026-03-23 | 1440 |
| 2026-03-24 | 1440 |
| 2026-03-25 | 1440 |
| 2026-03-26 | 1440 |
| 2026-03-27 | 1440 |
| 2026-03-28 | 1440 |
| 2026-03-29 | 1440 |
| 2026-03-30 | 1440 |
| 2026-03-31 | 1440 |
| 2026-04-01 | 952 |
| 2026-04-02 | 1440 |
| 2026-04-03 | 1440 |
| 2026-04-04 | 1440 |

Coverage note:

- `2026-04-01` is the only partial day in the range
- all other reviewed days are full 1440-row daily minute sets

### Key field completeness

Approximate non-null coverage across the full range:

| Field | Coverage |
| --- | ---: |
| `price_vs_vwap_side` | 100.00% |
| `delta_sign` | 100.00% |
| `price_move_sign` | 100.00% |
| `delta_price_alignment_1m` | 100.00% |
| `delta_price_efficiency_1m` | 100.00% |
| `body_to_range_ratio` | 100.00% |
| `delta_pct_60m` | 99.86% |
| `delta_pct_180m` | 99.86% |
| `vol_pct_60m` | 99.86% |
| `vol_pct_180m` | 99.86% |
| `favorable_max_15m` | 99.99% |
| `adverse_max_15m` | 99.99% |
| `favorable_max_60m` | 99.99% |
| `adverse_max_60m` | 99.99% |
| `up_hit_25bp_15m_flag` | 99.99% |
| `down_hit_25bp_15m_flag` | 99.99% |
| `up_hit_50bp_60m_flag` | 99.99% |
| `down_hit_50bp_60m_flag` | 99.99% |

Health conclusion:

- the reviewed range is operationally clean
- there are no major null-pattern anomalies beyond the expected small early-window gaps in rolling percentile fields
- M2a and M2.5 are usable for cross-day evidence work in their current form

---

## 3. Mechanics Fields Reviewed

Single fields reviewed:

- `price_vs_vwap_side`
- `delta_sign`
- `price_move_sign`
- `delta_price_alignment_1m`
- `delta_price_efficiency_1m`
- `delta_pct_60m`
- `delta_pct_180m`
- `vol_pct_60m`
- `vol_pct_180m`
- `body_to_range_ratio`

Combination shortlist reviewed:

- `price_vs_vwap_side × delta_price_alignment_1m`
- `price_vs_vwap_side × delta_pct_60m bucket`
- `price_vs_vwap_side × price_move_sign`
- `delta_sign × price_move_sign`
- `delta_pct bucket × delta_price_efficiency bucket`

Primary outcome lens used:

- `favorable_max_15m`
- `adverse_max_15m`
- `favorable_max_60m`
- `adverse_max_60m`
- `up_hit_25bp_15m_flag`
- `down_hit_25bp_15m_flag`
- `up_hit_50bp_60m_flag`
- `down_hit_50bp_60m_flag`

Working summary metric used repeatedly in this review:

- `balance_H = favorable_max_H - adverse_max_H`

Important caution:

- favorable/adverse fields depend on `reference_direction`
- strong conclusions were therefore cross-checked against symmetric path behavior and not treated as full setup truth

---

## 4. Strongest Positive Evidence

### 4.1 Strongest single-field separators

#### `price_vs_vwap_side`

This is one of the clearest existing separators in the current stack.

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `below` | 13,519 | +6.51 | +12.82 |
| `above` | 13,346 | -0.80 | -10.95 |

Interpretation:

- the current stack already captures meaningful structural asymmetry around VWAP side
- minutes occurring `below` VWAP show materially better favorable/adverse balance than minutes `above`
- this difference remains visible at both 15m and 60m horizons

#### `price_move_sign`

This is also a strong separator.

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `down` | +6.83 | +19.59 |
| `up` | -1.07 | -17.75 |

Interpretation:

- current directional price response already carries real explanatory value
- the signal is not subtle at 60m

#### `delta_sign`

This is weaker than structure or price move sign, but still meaningful.

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `negative` | +6.11 | +11.86 |
| `positive` | -0.35 | -9.84 |

Interpretation:

- even raw delta direction is already informative across the reviewed period
- but it becomes more useful when paired with structural or efficiency context

#### `delta_price_efficiency_1m`

This is one of the more useful “quality of move” fields.

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `strong` | +3.36 | +2.41 |
| `mid` | +2.22 | -7.09 |
| `weak` | -2.37 | -2.91 |

Interpretation:

- efficiency is not the strongest standalone field, but it clearly helps separate better vs worse continuation quality
- weak efficiency is a useful warning sign

#### `delta_pct_180m`

The 180m delta percentile is more useful than the 60m version as a standalone separator.

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `high` | +3.39 | +3.66 |
| `mid` | +3.58 | +2.03 |
| `low` | +0.01 | -5.25 |

Interpretation:

- longer local context seems more stable than the shorter 60m percentile for raw delta significance
- very low delta percentile is consistently less useful

### 4.2 Strongest combination evidence

#### `price_vs_vwap_side × price_move_sign`

This is one of the cleanest and most stable combination seams found in the review.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `below × down` | 10,728 | +7.67 | +20.28 |
| `above × down` | 2,681 | +3.36 | +16.97 |
| `below × up` | 2,788 | +1.60 | -17.63 |
| `above × up` | 10,553 | -1.73 | -17.77 |

Interpretation:

- structural side plus immediate price direction already explains a large share of short-horizon asymmetry
- `below × down` is especially strong across both horizons
- `above × up` is consistently weak

#### `delta_sign × price_move_sign`

This combination also shows meaningful separation.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `negative × down` | 10,054 | +7.91 | +20.86 |
| `positive × down` | 3,351 | +3.52 | +15.67 |
| `negative × up` | 2,674 | +0.89 | -15.12 |
| `positive × up` | 10,777 | -1.70 | -18.59 |

Interpretation:

- price move sign dominates more than raw delta sign
- but negative delta paired with down price move is clearly more informative than either field alone

#### `price_vs_vwap_side × delta_pct_60m bucket`

This combination identifies one of the best-performing interpretable pockets.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `below × mid` | 7,907 | +11.52 | +17.54 |
| `below × high` | 2,920 | +3.26 | +16.06 |
| `above × mid` | 7,918 | -2.17 | -7.56 |
| `above × high` | 1,370 | +0.35 | -17.48 |
| `below × low` | 2,673 | -3.93 | -3.64 |

Interpretation:

- not all “extreme” delta minutes are best
- `below × mid percentile delta` actually outperforms `below × high percentile delta` at 15m and remains strong at 60m
- this suggests that moderate but contextually coherent activity may currently be more informative than raw local extremeness alone

#### `delta percentile × price efficiency`

This is the most useful “quality control” combination in the current stack.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `delta_pct_60m high × strong efficiency` | 3,801 | +4.30 | +7.55 |
| `delta_pct_180m high × strong efficiency` | 3,655 | +6.76 | +12.93 |
| `delta_pct_60m mid × strong efficiency` | 13,436 | +5.21 | +5.84 |

Interpretation:

- high or moderate delta significance becomes much more meaningful once price efficiency is added
- this is one of the clearest examples that M2a is already carrying real explanatory power

---

## 5. Weak / Misleading Evidence

### 5.1 Weak standalone fields

#### `delta_price_alignment_1m`

This field looks intuitively important, but in current form it is not a strong standalone separator.

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `aligned` | +3.11 | +1.16 |
| `opposed` | +2.21 | +0.35 |

Interpretation:

- alignment alone is too weak to justify strong explanatory claims
- it becomes more useful only when paired with stronger structural context

#### `body_to_range_ratio`

This is currently a weak field for cross-day outcome separation.

Review conclusion:

- bucket-level differences were small
- it did not stand out as a reliable separator for favorable/adverse balance or threshold-hit behavior
- it should not currently be treated as a high-priority explanatory field

#### `vol_pct_60m`

This field was weaker than expected.

Review conclusion:

- the 60m local volume percentile adds less useful separation than delta significance or efficiency
- it may still have supporting value, but it is not a leading driver in this range

### 5.2 False-friend combinations

#### High delta percentile × weak price efficiency

This is one of the clearest misleading zones in the current stack.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `delta_pct_60m high × weak efficiency` | 489 | -19.39 | -40.54 |
| `delta_pct_180m high × weak efficiency` | 480 | -18.75 | -40.01 |

Interpretation:

- raw delta significance without price efficiency is often actively misleading
- this is exactly the kind of pattern that would look intuitively “important” but currently behaves poorly in outcome terms

#### `above × up`

This looks directionally natural but is weak in current data.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `above × up` | 10,553 | -1.73 | -17.77 |

Interpretation:

- this is a large-sample weak zone
- the current stack does not support treating it as a favorable continuation pocket

#### `above × aligned`

This also underperforms.

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `above × aligned` | 9,980 | -1.37 | -11.00 |

Interpretation:

- this again shows that alignment by itself is not enough
- without better participation context, some “clean-looking” minutes are currently over-rated

---

## 6. Cross-Day Stability

The strongest findings are not based on one isolated day.

What repeated across the reviewed range:

- `price_vs_vwap_side` kept showing meaningful asymmetry
- `price_move_sign` and `delta_sign × price_move_sign` repeated as useful separators
- efficiency repeatedly improved the meaning of delta significance
- the negative behavior of `high delta × weak efficiency` repeated often enough to be taken seriously

What looked less stable:

- pure alignment effects
- pure body/range-shape effects
- some high-percentile buckets when sample size became small

Important stability note:

- some of the strongest negative pockets, especially `high delta × weak efficiency`, have relatively small counts per day
- they still matter because their effect size is large and they repeat across multiple days
- but they should be treated as evidence of a real weak zone, not yet as a final production rule

Overall stability conclusion:

- the broad directional/structural findings look repeated enough to be trusted as research evidence
- the smaller extreme buckets are promising but still need one more layer of explanation before they should be grouped into hard event types

---

## 7. Explanatory Gaps

Current M2a already explains a meaningful share of short-horizon path behavior.

What it explains reasonably well already:

- structural side relative to VWAP
- immediate directional price response
- whether delta significance comes with efficient or inefficient price movement

What it still does **not** explain well:

- why some high-delta minutes still produce poor directional payoff
- whether aggressive movement is driven by new participation, unwind, or liquidation pressure
- whether weak or misleading pockets are participation failures, forced-flow moves, or crowded-side effects

This is the strongest evidence in favor of M2b.

Specifically, the review now justifies adding:

- OI mechanics
- liquidation mechanics

Funding context is still relevant, but the current evidence suggests OI and liquidation are more urgent than funding for the next explanatory step.

Why M2b looks justified:

- the current stack can already locate “interesting but still unresolved” pockets
- the remaining gap is less about better forward outcomes math and more about missing participation-state explanation

Why early typing still looks premature:

- some mechanically interesting combinations clearly separate outcomes
- but the unresolved false-friend zones show that the current stack is still missing an important explanatory layer
- typing too early would risk turning partial mechanics into unstable narrative classes

Why immediate M2.5 refinement does **not** look like the first need:

- current outcome fields were sufficient to surface strong and weak mechanics zones
- the bottleneck is not primarily the outcome contract
- the bottleneck is the missing participation explanation above the current price/delta/VWAP layer

---

## 8. Practical Next-Step Recommendation

### Recommended next step

- proceed to **M2b participation mechanics**

Priority order:

1. add OI mechanics
2. add liquidation mechanics
3. re-run the same cross-day evidence review
4. only then consider early evidence-based grouping / typing

### Why not jump straight to typing

Because the current review shows both:

- real explanatory power already present in M2a
- real unresolved blind spots that likely belong to participation mechanics rather than to taxonomy design

### Why not prioritize outcome refinement first

Because the current M2.5 layer is already good enough to expose useful asymmetry and false-friend pockets.

It may deserve later refinement, but it is not the main blocker for the next analyzer decision.

---

## 9. Final Verdict

The current minute-event stack is already useful for identifying **structural and directional asymmetry pockets**, especially around VWAP side, immediate price direction, and the interaction between delta significance and price efficiency.

What it still cannot explain well is **participation quality**: whether a mechanically interesting minute is backed by new positioning, unwind, or forced flow.

Because of that, the strongest evidence-based next move is:

- **M2b first**

not early typing and not immediate outcome-layer redesign.
