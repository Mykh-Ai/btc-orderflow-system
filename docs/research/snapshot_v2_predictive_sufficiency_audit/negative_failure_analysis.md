# Negative trades mistaken for TP1 reachability

Nine chronology-valid trades terminated before TP1. Both blind predictors frequently assigned them MIXED. The table records **pre-outcome** frozen facts only. Delta and price percentages are normalized to trade direction; OI change keeps its raw sign. `D240` is T−240→T−60 directional Delta percent; `D5/P5/OI5` describe T−5→T0. Rounded values are for display; exact values and preceding segments are in `case_feature_matrix.csv`.

| NEGATIVE trade | D240 | D5 / P5 / OI5 | 240m directional position | TP1/TP2 R | TP1/TP2 vs selected zone |
| --- | ---: | --- | ---: | --- | --- |
| `EX_EN_1779805524` | −.037 | +.224 / +.472 / −456.30 | .939 | .659/1.489 | BEYOND/BEYOND |
| `EX_EN_1780067415` | −.072 | +.284 / +.503 / −216.17 | .950 | .821/1.732 | BEYOND/BEYOND |
| `EX_EN_1781221266` | −.035 | +.335 / +.261 / −149.76 | .743 | 1.000/2.000 | INSIDE/INSIDE |
| `EX_EN_1782076213` | −.062 | +.288 / +.397 / −11.42 | .970 | 1.000/2.000 | BEYOND/BEYOND |
| `EX_EN_1782477849` | +.030 | +.302 / +.833 / +22.96 | .993 | 1.106/2.159 | BEYOND/BEYOND |
| `EX_EN_1785961338` | +.066 | +.614 / +.122 / −1035.79 | .868 | 1.002/2.004 | INSIDE/BEYOND |
| `EX_EN_1786107369` | +.064 | +.385 / +.056 / −283.61 | .938 | 1.202/2.303 | BEYOND/BEYOND |
| `EX_EN_1786131443` | −.001 | +.007 / +.094 / −116.61 | .877 | 1.000/2.000 | INSIDE/BEYOND |
| `EX_EN_1788166698` | +.028 | +.238 / +.085 / −16.39 | .995 | 1.000/2.000 | INSIDE/INSIDE |

## Comparison with the ten true TP1 reachers

The earlier T−240→T−60 directional Delta is positive in **4/9 negatives versus 8/10 reachers**. Its median is −.0013 versus +.0340 and rank-biserial +.356. This is a weak, recurring difference; `EX_EN_1785961338` and `EX_EN_1786107369` are negative despite strong positive earlier Delta.

Final 5m OI change is negative in **8/9 negatives versus 6/10 reachers**. Median is −149.76 versus −8.97, rank-biserial +.578. Yet `EX_EN_1782076213` has only −11.42 and several TP1-reaching trades have substantial declines (e.g. MIXED `EX_EN_1781615351`: −246.68). Absolute OI changes have large outliers; no scale-normalized OI inference was introduced after unblinding.

Every NEGATIVE and every TP1-reaching trade has positive final directional Delta percent and price change percent. The NEGATIVE medians (+.288 and +.261) are not smaller than reaching medians (+.260 and +.242). Seven of nine negatives have final Delta percent above the preceding 10m segment, and eight of nine have a larger direction-normalized price percent *per minute* in the final 5m than in the preceding 10m. A visually strong final impulse therefore does not establish TP1 reachability in this cohort.

Effort and price progress do not yield a consistent failure signature. `EX_EN_1785961338` combines +.614 Delta percent with only +.122 price percent; `EX_EN_1782477849` combines +.302 Delta percent with +.833 price percent, and both are negative. True TP2 reacher `EX_EN_1784376441` also has +.296 Delta with just +.059 price. These facts differ, but the same effort/result relationship can appear on either side of Target A.

Geometry contributes an overlapping hint: TP1 is beyond the selected zone in 5/9 negatives and 2/9 observed reachers; TP2 beyond in 7/9 negatives and 4/9 observed reachers. Negative cases also occur when both targets are INSIDE (`EX_EN_1781221266`, `EX_EN_1788166698`). The target-R values cluster around 1R and 2R in both groups. The chosen qualified zone is INSIDE with zero distance for every observed case, and no recent cleared-structure fact is populated.

**Answer:** no single recurring pre-outcome sign shows that the final impulse lacks enough continuation to reach TP1. Earlier directional Delta and final OI change give weak, overlapping clues. The frozen final Delta and price impulse themselves are misleading if treated as sufficient evidence for TP1.
