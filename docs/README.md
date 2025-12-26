## Safe Execution & Order-Flow Analytics for Binance Spots (R&D)

This repository demonstrates a production-oriented trading pipeline designed to
handle real-market edge cases: partial fills, TP/SL sequencing, retries,
and exchange-specific quirks.

It is not a "profit bot".
It is an execution-first architecture built to avoid the most common reasons
trading systems fail in live environments.

### Scope
This is a demonstration / research project focused on:

- real-time market data ingestion and aggregation
- order-flow based signal detection
- execution flow with explicit risk and state control
- safe separation between data, signals, and execution
- designing systems that can survive partial fills, latency, and API failures

## Important
- This repository is **not a complete trading bot**
- No trading strategy or profitability claims are included
- Production-ready execution logic and integrations are developed
  separately and adapted within individual client projects

## Components
- `aggregator` — real-time market data ingestion
- `deltascout` — order flow / imbalance signal detection
- `executor` — execution flow demo (orders, state, risk handling)
- `buyer` — example alert / action handling module

## Notes
This repository is intended as a **portfolio and technical showcase**
to demonstrate system design and engineering approach.



