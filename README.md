### Data Flow (High Level)

Binance Trades Stream (executed trades) ↓ Aggregator

- collects executed trade events (market prints)
- aggregates + normalizes into time-based metrics (volume, delta, imbalance)
- outputs: aggregated.csv ↓ DeltaScout

DeltaScout
- reads: aggregated.csv
- detects PEAK events (signals)


---

## Core Idea

> For traders, the real value is the **entry logic**.  
> Automation is only an execution convenience.

The system is designed with a clear separation between:
- market data preparation,
- signal generation,
- risk planning,
- execution,
- and human interaction.

This allows the same signals to be used in **manual, semi-automatic, or fully
automated** workflows.

---

## Architecture (High Level)
