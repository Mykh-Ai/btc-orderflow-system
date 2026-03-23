from __future__ import annotations

from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parent
DELTA_ROOT = MODULE_ROOT.parent
DEFAULT_RESEARCH_ROOT = DELTA_ROOT / "research_material"
DEFAULT_ARCHIVE_GLOB = str(DEFAULT_RESEARCH_ROOT / "raw_archive" / "*.jsonl")
DEFAULT_FEED_GLOB = "/opt/aitrader/feed/*.csv"
LEGACY_DEFAULT_FEED_GLOB = str(DEFAULT_RESEARCH_ROOT / "raw_feed" / "*.csv")

RAW_DELTA_EVENTS = {"DELTA_MAX", "DELTA_MIN"}
