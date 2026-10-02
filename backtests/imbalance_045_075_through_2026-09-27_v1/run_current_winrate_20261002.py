from __future__ import annotations

# Run the established LONG 0.50-0.69 / SHORT 0.54-0.69 selector through the
# current local Scout backtester without overwriting the frozen Sep-28 run.

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_imbalance_variant as runner  # noqa: E402


original_run = runner.cli.run


def run_with_unique_id(args):
    args.experiment_id = "long_lower_050_currentcode_20261002_v1"
    args.description = (
        "Current-code verification of LONG imbalance 0.50-0.69 / SHORT "
        "0.54-0.69; upstream-pass candidates only; A/B union reapplied; "
        "Executor V15 dual-feed replay through 2026-09-27."
    )
    return original_run(args)


runner.cli.run = run_with_unique_id
sys.argv = [sys.argv[0], "--variant", "long_lower_050"]
runner.main()
