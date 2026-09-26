# TP2 continuation: six missed strong trades

The blind direct and hierarchical contracts predicted no STRONG_FAVORABLE cases. The six true strong cases and four true MIXED cases below use only frozen pre-outcome fields. Each `D/P/OI` triplet is **direction-normalized Delta percent / direction-normalized price change percent / raw OI change** for `T−60→T−15 ; T−15→T−5 ; T−5→T0`, in that order. Positive D and P mean movement in the trade direction. Values are rounded for display; `case_feature_matrix.csv` retains exact raw and normalized values and all five segments.

| True class / trade | Recent D/P/OI sequence: 45m ; 10m ; 5m | 240m directional range position | Prior cleared structure | Selected opposing zone | TP1/TP2 R; zone relation |
| --- | --- | ---: | --- | --- | --- |
| STRONG `EX_EN_1778689753` | −.122/−.533/+413.78 ; +.192/+.152/+74.27 ; +.145/+.051/−0.64 | .176 | absent | INSIDE; distance 0 | 1.111/2.167; INSIDE/INSIDE |
| STRONG `EX_EN_1779438963` | −.037/−.076/−64.69 ; −.241/+.027/+14.82 ; +.464/+.269/−72.31 | .847 | absent | INSIDE; distance 0 | 1.042/2.063; INSIDE/INSIDE |
| STRONG `EX_EN_1782306796` | +.068/+.425/−30.81 ; +.169/+.457/−95.74 ; +.250/+.478/+300.41 | .964 | absent | INSIDE; distance 0 | 1.000/2.000; INSIDE/BEYOND |
| STRONG `EX_EN_1784376441` | +.043/+.006/+14.28 ; +.492/+.166/+103.69 ; +.296/+.059/−17.30 | .892 | absent | INSIDE; distance 0 | 1.315/2.472; INSIDE/INSIDE |
| STRONG `EX_EN_1787063409` | −.009/+.294/−335.09 ; +.269/+.727/−642.01 ; +.258/+.408/+242.51 | .963 | absent | INSIDE; distance 0 | 1.059/2.088; BEYOND/BEYOND |
| STRONG `EX_EN_1789351940` | −.021/+.326/+155.27 ; +.136/+.163/−34.98 ; +.162/+.205/+80.53 | .909 | absent | INSIDE; distance 0 | .799/1.698; INSIDE/INSIDE |
| MIXED `EX_EN_1781057890` | −.046/+.082/+111.47 ; +.430/+.394/+249.39 ; +.262/+.267/−52.47 | .895 | absent | INSIDE; distance 0 | 1.118/2.177; INSIDE/BEYOND |
| MIXED `EX_EN_1781615351` | −.006/+.117/+110.55 ; −.083/+.025/+21.84 ; +.329/+.360/−246.68 | .982 | absent | INSIDE; distance 0 | .748/1.621; BEYOND/BEYOND |
| MIXED `EX_EN_1782740830` | −.040/−.313/−430.26 ; +.140/+1.062/+32.15 ; +.149/+.218/+205.18 | .921 | absent | no qualified zone | 1.159/2.239; relation unavailable |
| MIXED `EX_EN_1785025567` | +.156/+.008/−31.73 ; +.028/+.047/−3.29 ; +.488/+.043/−37.62 | .955 | absent | INSIDE; distance 0 | 1.139/2.209; INSIDE/INSIDE |

## Cohort comparison

- Directional Delta increases from the preceding 10m segment to final 5m in 3/6 strong and 3/4 mixed. Final directional Delta median is **lower** in strong (+.254) than mixed (+.295). There is no common Delta acceleration signature for strong trades.
- Final directional price change median is almost identical: +.237% strong versus +.242% mixed. One strong case has only +.051% final price progress, and one mixed case +.043%; larger progress also appears in both.
- Final OI change is positive in 3/6 strong and 1/4 mixed. The strong set also has three negative cases, including −72.31. It is a weak descriptive difference, not a reliable sign rule. Across the preceding 45m and 10m windows the signs change in both groups.
- 240m range position is not a stable separator: five strong trades are at .847–.964, overlapping all four mixed at .895–.982; one strong trade is at .176. Prior cleared structure is absent in all ten, so it cannot describe progression to TP2.
- TP2 is beyond the selected opposing zone in **2/6 strong** and **2/3 observed mixed**. The apparent frequency difference is based on three observed mixed zones and is contradicted by two TP2-reaching cases. TP2 R spans 1.698–2.472 in strong and 1.621–2.239 in mixed. Thus target distance or zone relation is not a TP2 veto.
- For approximate directional target distance beyond the 240m range extreme, rank-biserial is −.083 for both TP1 and TP2, comparing strong with mixed. This does not support the repeated blind verdict argument that TP2 being beyond a recent extreme means the trade must end after TP1.

**Answer:** no recurring and coherent frozen pre-outcome distinction separates TP1-only from TP2-reaching trades in this ten-case cohort. The selected zone's current state is the same INSIDE/already-interacted state wherever available, and the cleared-structure field is null throughout. This is a limitation of this cohort and representation, not proof that TP2 continuation is intrinsically unpredictable.
