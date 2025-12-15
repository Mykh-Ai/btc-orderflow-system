Collects raw executed trade data from Binance,
aggregates and normalizes it into time-based metrics
(volume, buy/sell imbalance, delta),
and writes structured market data to aggregated.csv.
Note: This module processes executed trades only and does not consume
raw order book depth (bid/ask levels).

