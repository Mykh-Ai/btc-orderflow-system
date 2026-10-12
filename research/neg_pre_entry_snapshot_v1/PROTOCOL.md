# NEG_PRE_ENTRY_SNAPSHOT_V1 — revised freeze, FEED ONLY

Base d6f82fccd0ffea27831e878382eaf8f2662a39bb. Research only. User scope correction on 2026-10-12 explicitly supersedes the original zone-reconstruction / lower-structure requirements: take two snapshots from the available FEED; do not build or count zones. No Monitor reconstruction is used in the delivered analysis. No liquidation/OI proxies. No new entry filter or backtest.

Primary: all 262 independent NEG_H1_CONTROL opportunities, including portfolio-blocked opportunities. Exact candidate ID and per-trade financial parity gate is preserved. S0 is the owning raw NEG delta timestamp; S1 is signal_ts_utc, the decision time, not entry_fill_ts. No post-decision data. Raw owning delta/volume are separately retained as journal identity; current snapshot flow comes from the historical minute feed.

## Frozen feature definitions

Use exact availability/close-labelled minute timestamps from the existing replay loader. At each cutoff extract OHLC, close position within the bar, candle body/range in bps, total/buy/sell volume, signed delta=buy−sell, signed/absolute imbalance, observed AggTrades, and minute_average_price. Normalized feed column VWAP comes from AvgPrice; do not present it as session VWAP. Do not import journal POC or VWAP into this feed-only dataset. Liquidation/OI/funding/POC/session VWAP and native post-sweep evidence remain unavailable.

Use trailing 5/15/60-minute price change, volume, delta, signed imbalance, trades and price range; native-form 20-minute z-scores with population std and current minute included. Full window, contiguous minutes and valid positive volume are required; warm-up, invalid/gapped window and zero variance remain missing. Price change uses the previous close at t−window, available before cutoff. All interval measures use (S0,S1], except initial S0 price.

State change: elapsed minutes; price progress; maximum upward/downward excursion from S0; cumulative volume/delta/imbalance/trades; S1−S0 delta/volume/z-scores/imbalance/range and trailing features; immediate 1/5/15-minute downward progress only if the complete interval is available by S1. These are factual flow/price responses, not ground-truth absorption or liquidation classes. No classification thresholds.

Outcome join is one-to-one after construction of features. Preserve exact existing gross/net PnL, commission, slippage, position_r and lifecycle/TP markers. Trade outcome or fill-time information is not an input to any feature. Analyze gross and net winners separately.

## Descriptive statistics, frozen before inspection

Every numeric feature: N, mean, median, P25/P75 by gross/net label; rank-biserial Mann–Whitney effect and BH q within each label family. Global quartiles (qcut duplicates dropped) are descriptive only, never filters. For categorical variables report N, win rate, gross/trade, net/trade and PF. Monthly comparisons use the same global quartiles, not refitted monthly bins. Top post-hoc rankings require >=80% coverage and >=20 observations per outcome class. Correlated feature copies are identified and not treated as independent discoveries. Report gross vs net, costs, sample size, month concentration and missingness. No threshold optimization, new strategy, ML or production recommendation.

The original lower_structure.csv/zone tests and lower-plate conclusions are explicitly not applicable under the user's feed-only correction. REPORT_UA.md must state this, rather than manufacture structural evidence. Original repository evidence audit is retained as provenance of the scope correction.
