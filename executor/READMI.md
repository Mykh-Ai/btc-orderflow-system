# Executor (V1.5 production snapshot)

Hi! 👋  
This folder contains a **production snapshot** of the trade execution module (**Executor**) for the *btc-orderflow-system*.

`executor.py` is responsible for:
- placing orders (entry / TP / SL),
- managing open positions (stop-loss moves, trailing logic),
- restoring state after restarts and performing basic execution integrity checks,
- operating in coordination with other system components (signals / state / notifications).

## Contents
- `executor.py` — a **single-file** production version of Executor **V1.5**, used in a live environment.

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
Ongoing refactoring (V2.0), modularization, and tests are developed in separate branches.  
The `main` branch is kept as a stable production baseline.

## Questions / ideas
If you have questions or suggestions, feel free to open an **Issue** or start a **Discussion** in the repository 🙂
