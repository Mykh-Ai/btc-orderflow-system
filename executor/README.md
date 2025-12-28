# Executor (V1.5) — Binance execution engine (Spot)

Executor is a stateful execution service for **Binance Spot**.  
It manages orders around a *tracked position state* (Spot has no native “position” object like futures).

What it does:
- Entry placement (`LIMIT_THEN_MARKET` supported)
- Exit plan: TP1, TP2, trailing leg (qty3)
- Stop-loss management via `STOP_LOSS_LIMIT` with a safety gap
- Order status polling + deterministic state transitions
- Cleanup of remaining orders after trade completion/abort
- State persistence in `executor_state.json`

## V1.5 highlights

✅ Correct quantity split aligned to `QTY_STEP` (integer step-units; no float artefacts)  
✅ TP1 / TP2 fill handling (robust to ordering)  
✅ Safe `STOP_LOSS_LIMIT` placement (gap between `stopPrice` and `price`)  
✅ Entry timeout logic:
- cancels unfilled entry
- optional PlanB market entry guarded by max deviation  
✅ Trailing stop on remaining leg (`qty3`) after TP2  
✅ No “ghost orders”: exits are canceled/updated as the trade evolves

## State file

`STATE_FN=/data/state/executor_state.json`

Contains:
- `position`: current trade state (OPEN/PENDING/etc.)
- `orders`: order ids for entry/tp1/tp2/sl + qty1/qty2/qty3
- `last_closed`: reason & metadata of the last completed/aborted trade
- `cooldown_until`: next allowed entry time

## Operational checks (quick)

Expected open EX_* orders:
- After entry fill: **3** (TP1, TP2, SL)
- After TP1+TP2: **1** (trailing SL for qty3)
- After trade close: **0**

## Key settings (high level)

- `ENTRY_MODE`: `LIMIT_THEN_MARKET` recommended
- `LIVE_ENTRY_TIMEOUT_SEC`: how long to wait for limit fill
- `PLANB_MAX_DEV_USD / PLANB_MAX_DEV_R_MULT`: guard for market fallback
- `QTY_STEP`: Binance lot size step
- `TP_R_LIST`: profit tiers (TP1, TP2)
- Trailing settings: activates after TP2 on remaining qty3

## Roadmap (V2.0)

- Invariant watchdog + Telegram alerts (anti-ghost orders, recovery checks)
- Restart recovery: re-hydrate state from open EX_* orders
- **Margin trading support**:
  - borrow/repay lifecycle
  - debt and interest tracking
  - margin level / liquidation safety checks
  - isolated/cross mode handling (configurable)

