> **Status:** Beta testing  
> Core functionality is implemented.  
> Paper trading is fully operational; live execution is available in controlled scenarios.

### Data Flow (High Level)

Binance Trades Stream (executed trades)  
↓  
**Aggregator**
- collects executed trade events (market prints)
- aggregates and normalizes into time-based metrics (volume, delta, imbalance)
- outputs: `aggregated.csv`

↓  
**DeltaScout**
- reads `aggregated.csv`
- detects PEAK events (direction, delta, volume, imbalance)
- outputs: `deltascout.log` (JSONL signals)

↓  
**Executor**
- reads PEAK events from `deltascout.log`
- performs risk-based trade execution (paper or live)
- manages position lifecycle (entry, SL, TP, BE logic)
- outputs: state, logs, and optional webhook notifications



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


## Architecture (High Level)

The system is built as a set of loosely coupled modules with clear responsibilities
and explicit data contracts between them.

Each module can be developed, tested, and operated independently.

### Aggregator
Responsible for raw market data ingestion and normalization.

- Connects to Binance trade stream
- Collects executed trades (market prints)
- Aggregates data into fixed time intervals
- Produces normalized metrics:
  - traded volume
  - buy/sell delta
  - imbalance
- Persists results to `aggregated.csv`

The Aggregator has no trading logic and no signal awareness.

---

### DeltaScout
Responsible for signal generation only.

- Reads normalized market data from `aggregated.csv`
- Analyzes order-flow dynamics
- Detects statistically significant PEAK events
- Emits signals as immutable JSONL records

DeltaScout does not perform any execution or risk management.

---

### Executor
Responsible for execution and position lifecycle management.

- Subscribes to PEAK signals via `deltascout.log`
- Applies risk model and position sizing
- Handles order placement (paper or live)
- Manages open positions:
  - entry
  - stop-loss
  - take-profit
  - break-even logic
- Maintains persistent execution state for restart safety

The Executor is intentionally signal-agnostic and can be reused
with different signal sources.

---

### Design Principles

- **Separation of concerns**  
  Data preparation, signal generation, and execution are strictly separated.

- **Single responsibility per module**  
  Each component solves one well-defined problem.

- **Stateless signals, stateful execution**  
  Signals are immutable events; execution state is persisted and recoverable.

- **Automation as an execution layer**  
  The same signals can drive manual, semi-automatic, or fully automated workflows.

