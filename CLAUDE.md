# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

**Executor** is an automated trading execution engine for DeltaScout PEAK signals. It operates in single-position mode, managing the full lifecycle from signal detection to position closure with support for trailing stops, margin trading, and comprehensive state invariants.

## Core Architecture Principles

### Single-Position State Machine
- **One position at a time**: ignores new PEAK signals while position is OPEN/PENDING
- **Cooldown window**: waits `COOLDOWN_SEC` (default 180s) after closure before accepting new signals
- **Position lock**: blocks for `LOCK_SEC` (default 15s) after opening to prevent duplicate entries on restarts
- **State isolation**: writes ONLY to its own state/log files, never modifies DeltaScout source logs

### Module Dependency Injection Pattern
All modules in `executor_mod/` use dependency injection via `configure()` functions called at startup from `executor.py`. This prevents circular imports and keeps modules testable:

```python
# executor.py startup sequence
binance_api.configure(ENV, fmt_qty=risk_math.fmt_qty, fmt_price=risk_math.fmt_price, round_qty=risk_math.round_qty)
event_dedup.configure(ENV, iso_utc=iso_utc, save_state=save_state, log_event=log_event)
margin_guard.configure(ENV, log_event, api=binance_api)
trail.configure(ENV, read_tail_lines, log_event)
invariants.configure(ENV, log_event_fn=log_event, send_webhook_fn=send_webhook, now_fn=_now_s, save_state_fn=save_state)
```

**Critical**: When modifying modules, preserve this pattern. Never import `executor.py` from modules.

### Deterministic Decimal Math
All price/quantity calculations use Python's `Decimal` type to avoid float artifacts:
- `floor_to_step()`, `ceil_to_step()`, `round_nearest_to_step()` in `risk_math.py`
- `split_qty_3legs_*()` works in integer "step units" before converting back to float
- Format functions `fmt_price()`, `fmt_qty()` respect `TICK_SIZE` and `QTY_STEP`

**Never** use raw float arithmetic for order prices/quantities.

### State Persistence Strategy
State file (`STATE_FN`, default `/data/state/executor_state.json`) is written atomically:
```python
tmp = STATE_FN + ".tmp"
with open(tmp, "w") as f:
    json.dump(st, f)
os.replace(tmp, STATE_FN)  # atomic on POSIX
```

State structure includes:
- `position`: active position or `None` (with status: PENDING → OPEN → OPEN_FILLED → CLOSING → CLOSED)
- `last_closed`: previous position kept for analysis while `position=None`
- `meta.seen_keys`: deduplication buffer (last `SEEN_KEYS_MAX` keys)
- `cooldown_until`, `lock_until`: timestamps for state machine guards
- `margin`: borrow/repay tracking for margin mode

### Event Deduplication
Dedup key formula in `event_dedup.py`:
```python
f"{action}|{ts_minute}|{kind}|{price_rounded_to_DEDUP_PRICE_DECIMALS}"
# Example: "PEAK|2025-01-13T20:00|long|95000.0"
```
- Buckets timestamp to minute resolution for stability
- Uses `dedup_fingerprint()` (SHA256 of source code + config) to invalidate cache on algorithm changes
- Bootstrap from last 300 lines of DeltaScout log at startup via `bootstrap_seen_keys_from_tail()`

## Testing Commands

```bash
# Run all tests
python -m pytest test/

# Run specific test file
python -m pytest test/test_executor.py
python -m pytest test/test_invariants_module.py
python -m pytest test/test_margin_policy.py

# Run specific test case
python -m pytest test/test_executor.py::TestExecutorV15::test_swing_stop_far_uses_agg_high_low

# Run with verbose output
python -m pytest -v test/

# Run with print statements visible
python -m pytest -s test/test_executor.py
```

Tests use `unittest.mock` for external dependencies (Binance API, file I/O). Key patterns:
- `_stop_after_n_sleeps(n)` helper to break infinite loops in `main_loop()` tests
- Mock `binance_api.*` functions to avoid real API calls
- Use `deepcopy()` for ENV snapshot/restore in tests that modify global config

## Running the Executor

```bash
# Minimal spot trading setup
export SYMBOL=BTCUSDC
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TRADE_MODE=spot
export QTY_USD=100.0
python executor.py

# Margin trading (manual borrow/repay)
export TRADE_MODE=margin
export MARGIN_ISOLATED=FALSE
export MARGIN_BORROW_MODE=manual
export MARGIN_SIDE_EFFECT=NO_SIDE_EFFECT
python executor.py
```

## Critical Modules Deep Dive

### margin_guard.py - Lifecycle Hooks
Provides 4 hooks for margin mode:
1. `on_startup(state)` - validates config
2. `on_before_entry(state, symbol, side, qty, plan)` - calls `margin_policy.ensure_borrow_if_needed()`
3. `on_after_entry_opened(state, trade_key)` - marks trade_key active
4. `on_after_position_closed(state, trade_key)` - calls `margin_policy.repay_if_any()`

**Mode behavior**:
- `MARGIN_BORROW_MODE=auto`: hooks are no-ops, Binance handles via `MARGIN_SIDE_EFFECT=AUTO_BORROW_REPAY`
- `MARGIN_BORROW_MODE=manual`: hooks call `margin_borrow()` / `margin_repay()` explicitly

Runtime state tracked in `state["mg_runtime"]` dict to prevent re-execution on restarts.

### invariants.py - Detector-Only System
13 invariant checks (I1-I13) run every `INVAR_EVERY_SEC` (default 20s):
- **I1-I10**: position state consistency checks (SL present, price hierarchy, qty accounting, trailing state)
- **I11-I12**: margin config and trade key consistency
- **I13**: exchange-truth debt check after position close (calls `binance_api.get_margin_debt_snapshot()`)

**Critical**: Invariants NEVER take corrective actions. They only:
- `log_event("INVARIANT_FAIL", ...)`
- `send_webhook({"event": "INVARIANT_FAIL", ...})`
- Throttle alerts per `invariant_id:position_key` (configurable via `INVAR_THROTTLE_SEC`)

Exception: I13 can halt executor if `I13_KILL_ON_DEBT=true` and ERROR severity reached.

Metadata persisted separately to `/data/state/invariants_state.json` to avoid polluting main state with throttle timestamps.

### trail.py - Swing-Based Trailing Stop
Uses aggregated.csv (v2 schema) for swing detection:
- **LONG**: finds last swing low in `LowPrice` column via `_find_last_fractal_swing()`
- **SHORT**: finds last swing high in `HiPrice` column
- **Fractal logic**: `x[i] < x[i-lr..i-1] and x[i] < x[i+1..i+lr]` (configurable `lr` via `TRAIL_SWING_LR`)
- Stop placement: `swing_low - TRAIL_SWING_BUFFER_USD` (LONG) or `swing_high + TRAIL_SWING_BUFFER_USD` (SHORT)

**Bar-close confirmation** (optional via `trail_wait_confirm`):
- Uses `ClosePrice` column to confirm breakout above/below `trail_ref_price` before activating new stop
- Controlled by `TRAIL_CONFIRM_BUFFER_USD`

**Fail-loud** on schema mismatch (header != expected AGG_HEADER_V2), **fail-closed** on missing file (startup/rotation).

## Order Flow Patterns

### Entry Flow (in `executor.py:open_flow()`)
1. Validate signal freshness (`MAX_PEAK_AGE_SEC`)
2. Check dedup (`stable_event_key()` in `seen_keys`)
3. Build entry price via `build_entry_price()` (adds `ENTRY_OFFSET_USD`, rounds directionally)
4. Calculate quantity via `notional_to_qty()`, validate with `validate_qty()`
5. **Margin hook**: `margin_guard.on_before_entry()` → borrow if needed
6. Place entry order (LIMIT or MARKET depending on `ENTRY_MODE`)
7. Poll status every `LIVE_STATUS_POLL_EVERY` iterations
8. **Plan B**: if timeout, check executable price via `bookTicker`, abort if too far or past TP1
9. On fill: calculate exit prices, place exits via `exits_flow.ensure_exits()`
10. Set position lock and save state

### Exit Flow (in `exits_flow.py:ensure_exits()`)
1. `validate_exit_plan()`: ensures `sl < entry < tp1 < tp2` (LONG) with minimum tick separation
2. `place_exits_v15()`: places 3 legs (SL=33%, TP1=33%, TP2=34% with qty degradation to 50/50/0 if needed)
3. Uses `STOP_LOSS_LIMIT` for SL with `limit_price = stop_price - SL_LIMIT_GAP_TICKS * TICK_SIZE` (LONG)
4. On error: retries every `EXITS_RETRY_EVERY_SEC` up to `FAILSAFE_EXITS_MAX_TRIES`
5. **Failsafe**: if retries exhausted and `FAILSAFE_FLATTEN=true`, closes via `flatten_market()` MARKET order

### Trailing Activation (in `executor.py:manage_position()`)
Triggered when:
- `TRAIL_ACTIVATE_AFTER_TP2=true`
- TP2 order is FILLED
- Remaining qty > 0

Process:
1. Cancel existing SL via `cancel_order()`
2. Calculate new stop via `trail._trail_desired_stop_from_agg(pos)` (swing-based)
3. Set `trail_active=True`, `trail_sl_price=desired_stop`, `trail_qty=remaining`
4. Place new SL via `place_spot_limit()` or `place_order_raw()`

Updates every `TRAIL_UPDATE_EVERY_SEC` if price moves favorably by `TRAIL_STEP_USD`.

## File I/O Patterns

### Tail Reading (Performance Critical)
`read_tail_lines(path, n)` reads last N lines **without scanning from start**:
- Seeks to EOF, reads backwards in 8KB blocks until N newlines found
- Used for DeltaScout log (`TAIL_LINES=80`) and aggregated.csv trailing
- **Never** use `open(path).readlines()` for large logs in main loop

### Log Cap Pattern
`append_line_with_cap(path, line, cap)`:
- Appends line
- If file exceeds `cap` lines, truncates to last `cap` lines
- Used for `EXEC_LOG` (default `LOG_MAX_LINES=200`)

## Modifying Modules

### Adding New Invariants
1. Add check function `_check_iN_description(st)` in `invariants.py`
2. Call from `run(st)` after configure check
3. Use `_emit(st, "IN", severity, message, details)` for alerts
4. Add tests in `test/test_invariants_module.py`

### Adding Binance API Endpoints
1. Add function to `binance_api.py` (use `_binance_signed_request()` for authenticated)
2. Handle margin vs spot mode via `ENV["TRADE_MODE"]` check
3. Inject margin params: `isIsolated`, `sideEffectType` via `_margin_side_effect(env)`
4. Add smoke test in `test/test_binance_api_smoke.py` with mock

### Modifying State Structure
**High risk** - affects persistence across restarts:
1. Add migration logic in `state_store.load_state()` to handle old state format
2. Use `st.setdefault(key, default)` pattern for backward compatibility
3. Test with actual state file from production (if available)
4. Update `invariants.py` checks that reference state fields

## Configuration Patterns

### Environment Variable Precedence
All config in `ENV` dict built from `os.getenv()` at startup. Use typed getters:
- `_get_bool()` - accepts "1", "true", "yes", "on"
- `_get_int()` - with fallback
- `_get_float()` - with fallback
- `_get_str()` - with empty string handling

**Never** read `os.getenv()` directly in modules - always pass via `ENV` dict to `configure()`.

### Trade Mode Configuration
Two valid modes:
1. **spot**: `TRADE_MODE=spot` (default)
2. **margin**: `TRADE_MODE=margin` + `MARGIN_ISOLATED=TRUE/FALSE` + `MARGIN_BORROW_MODE=manual/auto`

Validated at startup via `_validate_trade_mode()` - raises `RuntimeError` if invalid.

## Common Pitfalls

1. **Float arithmetic**: Always use `Decimal` via `risk_math` functions, never `float(price) * qty`
2. **Circular imports**: Modules must NOT import `executor.py` - use dependency injection
3. **State mutation without save**: Always call `save_state(st)` after modifying `st["position"]`
4. **Missing margin hooks**: When adding new order placement, check if `margin_guard.on_before_entry()` needed
5. **Dedup key changes**: Update `dedup_fingerprint()` if modifying `stable_event_key()` logic
6. **Invariant actions**: Invariants should ONLY log/alert, never modify state or place orders
7. **Binance string types**: Use `_tf()` helper in `binance_api.py` to normalize bools to "TRUE"/"FALSE" strings
