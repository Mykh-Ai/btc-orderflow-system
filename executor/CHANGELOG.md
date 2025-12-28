# Changelog (Executor)

All notable changes to the **Executor** module will be documented here.

## [1.5] - 2025-12-28

### Added
- Live Spot execution cycle validated end-to-end: **ENTRY → TP1 → TP2 → trailing qty3 → cleanup**
- Entry mode `LIMIT_THEN_MARKET` with entry timeout + safe abort logic
- Trailing stop leg (qty3) activated after TP2

### Fixed
- Quantity split now uses **integer step-units** aligned to `QTY_STEP` (no float rounding loss; exact sums)
- TP1 / TP2 fill detection works reliably (independent order, no “must fill TP1 first” assumption)
- Stop-loss limit safety: `STOP_LOSS_LIMIT` uses a price gap vs `stopPrice` (avoids edge cases)

### Improved
- More consistent state transitions and tracking via `executor_state.json`
- Better protection against “chasing price” on PlanB market fallback using max deviation guard

## [1.0] - 2025-12 (early beta)

### Added
- Executor module created (single-position execution model)
- Risk-based SL/TP logic (R-multiples)
- Paper trading mode
- Controlled live testing (initial)
