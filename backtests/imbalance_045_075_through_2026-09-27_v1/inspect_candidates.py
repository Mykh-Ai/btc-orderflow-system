from __future__ import annotations

import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"D:\Project_V\btc-orderflow-system")

from deltascout.research_bundle.scout_backtester.candidate_compiler import compile_candidates
from deltascout.research_bundle.scout_backtester.feed_loader import load_feed
from deltascout.research_bundle.scout_backtester.shadow_features import enrich_shadow_flags


candidates, quality = compile_candidates(
    HERE / "source" / "candidate_index",
    date_from="2026-03-17",
    date_to="2026-09-27",
    raw_archive_root=HERE / "source" / "deltascout",
    candidate_groups=("PEAK_EMIT_BASELINE", "GATE_REJECT"),
)
pool = [
    c for c in candidates
    if (
        c.candidate_group == "PEAK_EMIT_BASELINE"
        or (c.candidate_group == "GATE_REJECT" and c.reject_reason == "imb_band")
    )
]
bars = load_feed(
    HERE / "source" / "effective_feed",
    date_from="2026-03-16",
    date_to="2026-09-27",
    quality_sidecar_root=Path(
        r"D:\Project_V\btc-orderflow-system\deltascout\research_material\recovery_reports"
    ),
)
enriched = enrich_shadow_flags(
    pool,
    bars,
    raw_archive_root=HERE / "source" / "deltascout",
    date_from="2026-03-17",
    date_to="2026-09-27",
)
counts = collections.Counter()
for c in enriched:
    counts[("group", c.candidate_group, c.reject_reason)] += 1
    if c.imbalance is not None:
        if 0.54 <= c.imbalance <= 0.69:
            band = "baseline"
        elif 0.45 <= c.imbalance < 0.54:
            band = "low_added"
        elif 0.69 < c.imbalance <= 0.75:
            band = "high_added"
        else:
            band = "outside"
        counts[("band", band, c.side)] += 1
        union = c.shadow_flags.get("loss_avoidance_conservative_union")
        counts[("union", band, c.side, str(union))] += 1

print("compiled", len(candidates), "pool", len(pool), "quality", len(quality), "bars", len(bars))
for key, value in sorted(counts.items(), key=lambda item: str(item[0])):
    print(key, value)
print("sample_baseline")
for c in [x for x in enriched if x.imbalance is not None and 0.54 <= x.imbalance <= 0.69][:10]:
    print(
        c.signal_ts_utc.isoformat(),
        c.side,
        c.candidate_group,
        c.reject_reason,
        c.imbalance,
        c.shadow_flags,
    )
