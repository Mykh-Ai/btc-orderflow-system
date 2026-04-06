# Minute Events Cross-Day Evidence Review After M2b (2026-03-17 to 2026-04-04)

## 1. Purpose

This memo re-runs the earlier cross-day minute-event evidence review after M2b added:

- OI mechanics
- liquidation mechanics

The purpose is not to create taxonomy or setup labels.
It is to test whether the new participation mechanics materially improve explanation of the same cross-day path behavior reviewed previously.

Important execution note:

- the existing daily `minute_events_mechanics` and `minute_events_outcomes` CSVs were still pre-M2b
- before this review, both datasets were rebuilt locally for `2026-03-17` through `2026-04-04`
- this memo therefore reflects the rebuilt post-M2b dataset state, not the older files

---

## 2. Data Coverage

### Date coverage

Reviewed range:

- 2026-03-17 through 2026-04-04

Coverage result:

- all days in the target range were present
- no reviewed day was missing `minute_events_mechanics` or `minute_events_outcomes`

### Row counts

Total reviewed rows:

- `26,872`

Per-day rows:

- full 1440-row days across the range except:
- `2026-04-01` = `952` rows

### New M2b field completeness

| Field | Non-null | Coverage |
| --- | ---: | ---: |
| `oi_change_1m` | 26,871 | 99.996% |
| `abs_oi_change_1m` | 26,871 | 99.996% |
| `oi_change_pct_60m` | 26,833 | 99.855% |
| `oi_change_pct_180m` | 26,833 | 99.855% |
| `delta_oi_alignment_flag` | 26,872 | 100.000% |
| `price_oi_alignment_flag` | 26,872 | 100.000% |
| `liq_total_1m` | 26,872 | 100.000% |
| `liq_imbalance_1m` | 26,872 | 100.000% |
| `liq_dominant_side` | 26,872 | 100.000% |
| `liq_burst_flag` | 26,834 | 99.859% |
| `delta_vs_liq_relation_flag` | 26,872 | 100.000% |

Health note:

- the only expected OI gap is the first globally sorted row, where no previous minute exists
- percentile gaps follow the same early-history behavior already seen in M2a
- no suspicious per-day null anomaly appeared after rebuild

---

## 3. M2b Field Evidence

### Strongest new OI evidence

#### `delta_oi_alignment_flag`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `opposed` | 13,770 | +4.91 | +7.50 |
| `aligned` | 12,932 | +0.94 | -5.35 |
| `flat_or_unknown` | 170 | -13.77 | -41.86 |

This is one of the strongest new explanatory fields.
The gap between `opposed` and `aligned` is large enough to matter at both horizons.

#### `price_oi_alignment_flag`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `opposed` | 13,431 | +6.93 | +10.01 |
| `aligned` | 12,978 | -1.08 | -7.83 |
| `flat_or_unknown` | 463 | -3.76 | -12.89 |

This is even cleaner than raw OI percentile fields.
It strongly suggests that OI alignment is already doing real explanatory work rather than adding passive metadata.

#### `oi_change_pct_180m`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `mid` | 15,924 | +3.43 | +2.39 |
| `high` | 5,495 | +2.69 | +1.77 |
| `low` | 5,414 | +1.09 | -4.33 |

`oi_change_pct_180m` is useful, but less decisive than the alignment fields.
Its main value is that very low OI change is meaningfully weaker, especially at 60m.

### Strongest new liquidation evidence

#### `liq_burst_flag`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `True` | 2,706 | +10.15 | +13.47 |
| `False` | 24,128 | +2.00 | -0.52 |

This is the strongest new liquidation field.
It adds a very clear event-intensity split.
The effect is especially strong at 15m and still positive at 60m.

#### `liq_dominant_side`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `sell` | 3,868 | +8.02 | +11.82 |
| `balanced_or_unknown` | 19,826 | +2.16 | +0.06 |
| `buy` | 3,178 | +1.10 | -6.25 |

This is useful but directionally asymmetric.
`Sell` liquidation dominates as a clearly stronger bucket than `buy` liquidation in this reviewed range.

#### `delta_vs_liq_relation_flag`

| Bucket | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `aligned` | 5,164 | +5.99 | +5.38 |
| `opposed` | 1,881 | +1.93 | -1.02 |
| `flat_or_unknown` | 19,827 | +2.16 | +0.06 |

Useful, but not as strong as `liq_burst_flag`.
Its main value is as a supporting field rather than a primary separator.

### Comparative M2b conclusion

- OI mechanics improved explanation materially
- liquidation mechanics also improved explanation materially
- OI alignment fields were the stronger broad explanatory addition
- liquidation burst was the strongest short-horizon event-intensity addition

---

## 4. Re-test of Prior Strongest Separators

The original M2a winners remain real.
They did not collapse after adding participation fields.

### `price_vs_vwap_side`

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `below` | +6.51 | +12.82 |
| `above` | -0.80 | -10.95 |

### `price_move_sign`

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `down` | +6.83 | +19.59 |
| `up` | -1.07 | -17.75 |

### `delta_sign`

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `negative` | +6.11 | +11.86 |
| `positive` | -0.35 | -9.84 |

### `delta_price_efficiency_1m`

| Bucket | Balance 15m | Balance 60m |
| --- | ---: | ---: |
| `mid` | +3.30 | +7.44 |
| `strong` | +3.24 | -1.48 |
| `weak` | +1.67 | -3.25 |

Post-M2b conclusion:

- the earlier M2a structural/directional winners still remain strong
- M2b does not replace them
- M2b adds useful explanation on top of them, especially inside the previously weak pockets

---

## 5. Re-test of False-Friend Pockets

This was the most important part of the rerun.

### A. `above × up`

Earlier review baseline:

- large-sample weak zone
- `balance_15m = -1.73`
- `balance_60m = -17.77`

Post-M2b splits:

| Split | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `liq_burst=True` | 1,060 | +14.19 | -3.59 |
| `delta_oi_alignment=opposed` | 5,222 | +0.84 | -7.26 |
| `delta_oi_alignment=aligned` | 5,325 | -4.21 | -28.14 |
| `oi_change_pct_180m=high` | 2,107 | -5.05 | -40.36 |
| `oi_change_pct_180m=low` | 2,161 | -2.95 | -3.87 |

Conclusion:

- yes, M2b splits this weak pocket into more interpretable subcases
- liquidation burst sharply improves the 15m picture
- OI alignment sharply separates the better subcase from the much worse one
- this pocket is no longer just a single undifferentiated weak zone

### B. `above × aligned`

Earlier review baseline:

- weak and misleading
- `balance_15m = -1.37`
- `balance_60m = -11.00`

Post-M2b splits:

| Split | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `liq_burst=True` | 1,051 | +13.28 | +5.86 |
| `delta_oi_alignment=opposed` | 4,846 | +1.13 | -0.14 |
| `delta_oi_alignment=aligned` | 5,056 | -3.29 | -20.70 |
| `oi_change_pct_180m=high` | 2,042 | -5.26 | -30.36 |
| `oi_change_pct_180m=mid` | 5,939 | +0.35 | -7.12 |

Conclusion:

- this is one of the clearest M2b wins
- the old false-friend pocket now decomposes into a strongly bad OI-aligned subcase and a much better burst / OI-opposed subcase

### C. `high delta percentile × weak efficiency`

Earlier review baseline:

- one of the clearest false-friend zones
- strongly negative favorable/adverse balance

Post-M2b splits:

| Split | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `liq_burst=True` | 618 | +17.69 | -6.35 |
| `liq_burst=False` | 2,085 | -6.54 | -10.25 |
| `delta_oi_alignment=opposed` | 1,377 | +5.37 | +2.38 |
| `delta_oi_alignment=aligned` | 1,311 | -5.60 | -20.95 |
| `oi_change_pct_180m=low` | 269 | +8.69 | +14.34 |
| `oi_change_pct_180m=high` | 1,296 | -3.04 | -24.62 |

Conclusion:

- this is the strongest proof that M2b closed part of the earlier explanatory gap
- the old weak pocket is now visibly splitting into:
  - bad aligned / no-burst / high-OI-change subcases
  - materially better opposed / burst / low-OI-change subcases

---

## 6. Strongest New Combinations

### `price_vs_vwap_side × price_oi_alignment_flag`

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `below × opposed` | 7,107 | +10.96 | +20.07 |
| `below × aligned` | 6,186 | +1.54 | +5.19 |
| `above × opposed` | 6,322 | +2.40 | -1.31 |
| `above × aligned` | 6,790 | -3.43 | -19.57 |

This is one of the best new participation-aware seams.

### `price_move_sign × delta_oi_alignment_flag`

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `down × opposed` | 7,056 | +8.01 | +23.80 |
| `down × aligned` | 6,186 | +5.89 | +16.32 |
| `up × opposed` | 6,567 | +1.68 | -9.72 |
| `up × aligned` | 6,599 | -3.76 | -26.07 |

This combination is especially useful because it cleanly separates better and worse directional follow-through.

### `delta_price_efficiency bucket × liq_burst_flag`

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `strong × True` | 809 | +12.87 | +15.42 |
| `mid × True` | 983 | +2.38 | +19.91 |
| `weak × True` | 914 | +16.11 | +4.82 |
| `weak × False` | 5,565 | -0.67 | -4.79 |

This is the best liquidation-aware seam found in the rerun.
`liq_burst_flag` does real explanatory work, especially as a short-horizon discriminator.

### `delta_sign × liq_dominant_side`

| Combination | Count | Balance 15m | Balance 60m |
| --- | ---: | ---: | ---: |
| `negative × sell` | 2,759 | +11.75 | +21.37 |
| `negative × buy` | 772 | +6.52 | +14.71 |
| `positive × buy` | 2,405 | -0.62 | -12.97 |
| `positive × sell` | 1,109 | -1.26 | -11.95 |

This adds useful direction/participation detail but is still secondary to the OI alignment seams.

---

## 7. Remaining Blind Spots

M2b improved the stack, but it did not make it fully explanatory.

What is better explained now:

- previously weak directional pockets are no longer monolithic
- OI alignment clearly distinguishes better vs worse participation subcases
- liquidation burst clearly identifies a stronger event-intensity subset

What still remains unresolved:

- some strong 15m burst-related improvements do not persist cleanly to 60m
- `buy`-side liquidation remains weaker and less intuitively useful than `sell`
- OI percentile magnitude alone is less informative than OI alignment
- some structurally weak `above` pockets still stay weak even after M2b splitting

Practical interpretation:

- M2b materially improved explanation
- but the stack still is not fully mature enough to pretend the mechanics are already a stable taxonomy

---

## 8. Strategic Next-Step Recommendation

### Recommendation

- proceed toward **early evidence-based grouping / typing**, but only in a narrow research form

Why this now makes sense:

- M2a winners remained strong
- M2b materially improved the main blind spots that the previous review said were unresolved
- M2.5 outcomes are already sufficient for comparative evidence work
- the stack now has enough structure plus participation context to begin small, evidence-first grouping experiments

Why not prioritize funding next:

- funding may still help later
- but the current rerun shows that the main requested participation gap was already materially improved by OI and liquidation
- funding no longer looks like the immediate bottleneck before any grouping work can begin

Why not prioritize M2.5 refinement first:

- current outcome fields were sufficient to show the M2b gain clearly
- the main improvement came from mechanics, not from missing outcome math

Recommended next move in practice:

1. keep current M2.5 as-is
2. define a small shortlist of evidence-based grouping candidates
3. test those candidate groups against the same cross-day outcome lens
4. add funding only if those early groups still show unexplained crowding/context drift

---

## 9. Final Verdict

M2b delivered real explanatory improvement.

What improved:

- OI alignment fields materially improved outcome separation
- liquidation burst materially improved event-intensity separation
- previously weak false-friend pockets now split into more interpretable participation subcases

What did not fully resolve:

- some weak `above` regimes remain weak even after participation splits
- liquidation helps more at short horizons than at long horizons
- the stack still does not justify hard taxonomy claims yet

Best next analyzer move:

- **begin narrow early evidence-based grouping / typing experiments**

not outcome redesign, and not funding-first expansion.
