from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_OUTPUT_ROOT = Path("market_monitor_runs")
DEFAULT_RUN_ID = "run"
BOUNDARY_STATEMENT = (
    "No trading signals, entries, exits, position sizing, orders, execution "
    "instructions, or live-trading actions were produced."
)


@dataclass(frozen=True)
class MonitorConfig:
    input_path: Path
    output_dir: Path
    run_timestamp: str

