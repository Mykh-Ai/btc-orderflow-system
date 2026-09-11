"""Build a research-only data snapshot and immutable input manifest."""
import argparse
import hashlib
import json
from pathlib import Path

from . import monitor_feed_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-root", type=Path, required=True)
    parser.add_argument("--cutoff", required=True, help="Explicit timezone, e.g. 2026-07-26T00:26:00Z")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--history-minutes", type=int, default=30 * 1440)
    parser.add_argument("--recovery-quality", type=Path)
    parser.add_argument("--recovery-manifest", type=Path)
    parser.add_argument("--recovery-lineage")
    args = parser.parse_args()
    frame, manifest = monitor_feed_contract.load_shi_prefix(
        args.feed_root, args.cutoff, history_minutes=args.history_minutes,
        recovery_quality=args.recovery_quality, recovery_manifest=args.recovery_manifest,
        recovery_lineage=args.recovery_lineage)
    snapshot = monitor_feed_contract.build_data_snapshot(frame, args.cutoff)
    manifest["code"] = [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in (Path(__file__), Path(monitor_feed_contract.__file__))]
    args.output_root.mkdir(parents=True, exist_ok=False)
    for name, value in (("snapshot.json", snapshot), ("manifest.json", manifest)):
        (args.output_root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output_root": str(args.output_root), "readiness": snapshot["local_window_readiness"],
                      "gaps": snapshot["gaps"], "live_decision_eligible": False}))


if __name__ == "__main__":
    main()
