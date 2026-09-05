# Executor (current modular production snapshot)

Hi! 👋  
This folder contains a **production snapshot** of the trade execution module (**Executor**) for the *btc-orderflow-system*.

`executor.py` is responsible for:
- placing orders (entry / TP / SL),
- managing open positions (stop-loss moves, trailing logic),
- restoring state after restarts and performing basic execution integrity checks,
- operating in coordination with other system components (signals / state / notifications).

## Contents

- `executor/executor.py` — the production entry point.
- `executor_mod/` — the production runtime modules used by that entry point.

The local snapshot was synchronized with the active VPS runtime on `2026-09-03`
after the Executor V8 rollout. Keep both paths together when testing or preparing a
deployment; `executor.py` is no longer a standalone implementation.

## Security notes
- This repository contains **no real API keys or secrets**.
- **Deployment details (VPS paths, private configs, exact environment parameters) are intentionally not published.**

## Financial disclaimer
This is primarily an **engineering and research project**.  
The code and information provided here are **not financial advice** and do not guarantee profitability. Trading with real funds involves significant risk — use at your own discretion and responsibility.

## Running
Executor is run as a standalone process/container as part of the system.  
(Installation and configuration details are available upon request.)

## Development

The production runtime is modular. Changes to `executor.py` must be tested together
with `executor_mod/`, especially `market_data.py`, order lifecycle modules, margin
guarding, state persistence, and invariants.

## V8 structural initial stop

The current local research implementation replaces the legacy 180-minute close
extreme with `VOLUME_SWING_24H_LR25`:

- exact 1,440-row BTCUSDT window ending at the exact signal minute;
- strict 25/25 `LowPrice`/`HiPrice` swing confirmation;
- highest one-minute `TotalQty` among eligible swings;
- `$50` structural buffer, existing 0.2% far-stop floor, and `$1,200` maximum
  finished distance;
- no legacy fallback when the window or swing contract fails.

Initial SL/TP geometry is built in BTCUSDT and converted once with a frozen
`BTCUSDC_mid / BTCUSDT_mid` entry ratio. USDT-derived trailing swings use a fresh
ratio before every BTCUSDC cancel/replace and are checked against the current
BTCUSDC mid. See
`docs/Executor_V8_Initial_Stop_USDT_USDC_Spec_v0_1.md` for the full contract and
deployment and validation record.

## Questions / ideas
If you have questions or suggestions, feel free to open an **Issue** or start a **Discussion** in the repository 🙂
