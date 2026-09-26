# Near-matched pre-outcome case pairs

These pairs were selected **after** opening outcomes to inspect counterexamples, not to derive a prediction rule. Values below come from the unchanged frozen Snapshot V2. Delta and price percentages have been multiplied by trade direction for comparable signs. Differences are observations, not causes.

## 1. NEGATIVE versus STRONG_FAVORABLE, similar entry geometry and side

| Pre-outcome fact | `EX_EN_1782076213` (NEGATIVE) | `EX_EN_1782306796` (STRONG_FAVORABLE) |
| --- | ---: | ---: |
| Side; TP1 R / TP2 R | SHORT; 1.000000 / 2.000000 | SHORT; 1.000008 / 2.000008 |
| 240m directional range position | .970 | .964 |
| T−240→T−60 directional Delta percent | −.062 | +.043 |
| T−15→T−5 directional Delta percent | −.109 | +.169 |
| Final 5m directional Delta percent | +.288 | +.250 |
| Final 5m directional price change percent | +.397 | +.478 |
| Final 5m OI change | −11.42 | +300.41 |
| TP1/TP2 relative to selected zone | BEYOND / BEYOND | INSIDE / BEYOND |

Both trades have virtually identical 1R/2R geometry, a near-extreme 240m position, and positive final Delta and price. The frozen earlier Delta signs, final OI change, and TP1 zone relation differ. These facts support inspecting temporal history and target relation rather than treating similar R distances as a shared outcome.

## 2. MIXED versus STRONG_FAVORABLE, similar target distances and side

| Pre-outcome fact | `EX_EN_1781057890` (MIXED) | `EX_EN_1779438963` (STRONG_FAVORABLE) |
| --- | ---: | ---: |
| Side; TP1 R / TP2 R | SHORT; 1.118 / 2.177 | SHORT; 1.042 / 2.063 |
| 240m directional range position | .895 | .847 |
| T−15→T−5 directional Delta percent | +.430 | −.241 |
| Final 5m directional Delta percent | +.262 | +.464 |
| Final 5m directional price change percent | +.267 | +.269 |
| Final 5m OI change | −52.47 | −72.31 |
| TP1/TP2 relative to selected zone | INSIDE / BEYOND | INSIDE / INSIDE |

Final price progress and falling OI are nearly matched while target distances are close. Preceding directional Delta and the TP2 zone relation differ. The stronger final Delta belongs to the TP2-reaching case here, but the cohort table shows this is not a class-wide rule.

## 3. NEGATIVE versus MIXED, similar recent directional Delta and side

| Pre-outcome fact | `EX_EN_1782076213` (NEGATIVE) | `EX_EN_1781057890` (MIXED) |
| --- | ---: | ---: |
| Side; TP1 R / TP2 R | SHORT; 1.000 / 2.000 | SHORT; 1.118 / 2.177 |
| Final 5m directional Delta percent | +.288 | +.262 |
| Final 5m directional price change percent | +.397 | +.267 |
| T−240→T−60 directional Delta percent | −.062 | +.029 |
| T−15→T−5 directional Delta percent | −.109 | +.430 |
| Final 5m OI change | −11.42 | −52.47 |
| TP1/TP2 relative to selected zone | BEYOND / BEYOND | INSIDE / BEYOND |

The final directional Delta is similar, while the negative case actually has more final price progress. Earlier Delta signs and TP1 zone relation differ. This pair illustrates why final impulse magnitude alone did not correctly determine TP1 reachability.

All pair comparisons are descriptive and do not establish that the listed differences caused the lifecycle outcome. Exact fields, including raw market-coordinate values, are in `case_feature_matrix.csv`.
