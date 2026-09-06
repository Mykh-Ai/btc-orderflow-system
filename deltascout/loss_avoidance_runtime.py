from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

try:
    from .loss_avoidance_policy import (
        RULE_ID,
        LossAvoidanceDecision,
        evaluate_loss_avoidance_policy,
    )
except ImportError:  # pragma: no cover - direct /app/delta_scout.py execution
    from loss_avoidance_policy import (  # type: ignore
        RULE_ID,
        LossAvoidanceDecision,
        evaluate_loss_avoidance_policy,
    )


VALID_MODES = {"off", "shadow", "veto"}
STATE_SCHEMA = "deltascout_loss_filter_state_v1"
REAL_VALUES = {"0", "false", "no", "n"}


@dataclass(frozen=True)
class LossAvoidanceRuntimeConfig:
    mode: str = "off"
    rule_id: str = RULE_ID
    enriched_feed_dir: Path = Path("/opt/aitrader/feed")
    state_path: Path = Path("/data/state/deltascout/loss_filter_state.json")
    research_archive_dir: Path = Path("/data/archive/deltascout")
    source_timezone: str = "Europe/Bratislava"
    enriched_timezone: str = "UTC"
    evaluation_budget_ms: float = 500.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LossAvoidanceRuntimeConfig":
        values = os.environ if env is None else env
        raw_mode = str(values.get("LOSS_FILTER_MODE", "off") or "off").strip().lower()
        mode = raw_mode if raw_mode in VALID_MODES else "off"
        try:
            budget = float(values.get("LOSS_FILTER_EVAL_BUDGET_MS", "500") or "500")
        except (TypeError, ValueError):
            budget = 500.0
        return cls(
            mode=mode,
            rule_id=str(values.get("LOSS_FILTER_RULE_ID", RULE_ID) or RULE_ID).strip(),
            enriched_feed_dir=Path(str(values.get("LOSS_FILTER_ENRICHED_FEED_DIR", "/opt/aitrader/feed"))),
            state_path=Path(str(values.get("LOSS_FILTER_STATE_PATH", "/data/state/deltascout/loss_filter_state.json"))),
            research_archive_dir=Path(
                str(values.get("LOSS_FILTER_RESEARCH_ARCHIVE_DIR", "/data/archive/deltascout"))
            ),
            source_timezone=str(values.get("LOSS_FILTER_SOURCE_TIMEZONE", "Europe/Bratislava")),
            enriched_timezone=str(values.get("LOSS_FILTER_ENRICHED_TIMEZONE", "UTC")),
            evaluation_budget_ms=max(1.0, budget),
        )


@dataclass(frozen=True)
class PeakHistoryEvent:
    event_ts_utc: datetime
    side: str
    abs_delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_ts_utc": self.event_ts_utc.isoformat(),
            "side": self.side,
            "abs_delta": self.abs_delta,
        }


@dataclass(frozen=True)
class EnrichedFeatureWindow:
    oi_change_60m: float | None
    oi_trusted_60m: bool
    directional_delta_pct_240m: float | None
    feature_status: str
    enriched_last_ts_utc: datetime | None
    detail: str = ""


@dataclass(frozen=True)
class RuntimeFilterEvaluation:
    configured_mode: str
    rule_id: str
    signal_ts_utc: datetime | None
    decision: LossAvoidanceDecision
    same_side_peak_count_24h: int
    same_side_peak_percentile_24h: float | None
    oi_change_60m: float | None
    oi_trusted_60m: bool
    directional_delta_pct_240m: float | None
    feature_status: str
    enriched_last_ts_utc: datetime | None
    evaluation_ms: float
    fail_open_reason: str | None = None
    detail: str = ""
    peak_history_status: str = "UNKNOWN"

    @property
    def may_veto(self) -> bool:
        return (
            self.configured_mode == "veto"
            and self.decision.union is True
            and self.fail_open_reason is None
        )

    def to_audit_fields(self) -> dict[str, Any]:
        fields = {
            "signal_ts_utc": self.signal_ts_utc.isoformat() if self.signal_ts_utc else None,
            "rule_id": self.rule_id,
            "configured_mode": self.configured_mode,
            "decision": self.decision.decision,
            "component_a": self.decision.component_a,
            "component_b": self.decision.component_b,
            "union": self.decision.union,
            "reason_codes": list(self.decision.reason_codes),
            "same_side_peak_count_24h": self.same_side_peak_count_24h,
            "same_side_peak_percentile_24h": self.same_side_peak_percentile_24h,
            "oi_change_60m": self.oi_change_60m,
            "oi_trusted_60m": self.oi_trusted_60m,
            "directional_delta_pct_240m": self.directional_delta_pct_240m,
            "feature_status": self.feature_status,
            "enriched_last_ts_utc": self.enriched_last_ts_utc.isoformat() if self.enriched_last_ts_utc else None,
            "evaluation_ms": round(self.evaluation_ms, 3),
            "fail_open_reason": self.fail_open_reason,
            "detail": self.detail,
            "peak_history_status": self.peak_history_status,
        }
        return fields


def _unknown_decision() -> LossAvoidanceDecision:
    return evaluate_loss_avoidance_policy(
        same_side_peak_percentile_24h=None,
        oi_change_60m=None,
        oi_trusted_60m=False,
        directional_delta_pct_240m=None,
    )


def parse_runtime_timestamp(value: Any, source_timezone: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    zone = ZoneInfo(source_timezone)
    fold0 = parsed.replace(tzinfo=zone, fold=0)
    fold1 = parsed.replace(tzinfo=zone, fold=1)
    if fold0.utcoffset() != fold1.utcoffset():
        raise ValueError(f"ambiguous local timestamp={text}")
    result = fold0.astimezone(timezone.utc)
    if result.astimezone(zone).replace(tzinfo=None) != parsed:
        raise ValueError(f"nonexistent local timestamp={text}")
    return result


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _dates_inclusive(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


class LossAvoidanceRuntimeEvaluator:
    def __init__(
        self,
        config: LossAvoidanceRuntimeConfig,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._peaks: list[PeakHistoryEvent] = []
        self._tracking_started_at_utc = self._now_utc()
        self._state_error: str | None = None
        self._peak_history_status = "WARMING"
        self._load_state()
        if self.config.mode != "off":
            self._bootstrap_from_research_archive()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LossAvoidanceRuntimeEvaluator":
        return cls(LossAvoidanceRuntimeConfig.from_env(env))

    @property
    def mode(self) -> str:
        return self.config.mode

    def _now_utc(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _load_state(self) -> None:
        path = self.config.state_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if payload.get("schema") != STATE_SCHEMA:
                raise ValueError("unsupported state schema")
            if payload.get("rule_id") != self.config.rule_id:
                raise ValueError("state rule_id mismatch")
            tracking = datetime.fromisoformat(str(payload["tracking_started_at_utc"]).replace("Z", "+00:00"))
            if tracking.tzinfo is None:
                tracking = tracking.replace(tzinfo=timezone.utc)
            peaks: list[PeakHistoryEvent] = []
            for row in payload.get("peaks", []):
                event_ts = datetime.fromisoformat(str(row["event_ts_utc"]).replace("Z", "+00:00"))
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=timezone.utc)
                side = str(row["side"]).upper()
                if side not in {"LONG", "SHORT"}:
                    raise ValueError("invalid peak side")
                peaks.append(PeakHistoryEvent(event_ts.astimezone(timezone.utc), side, abs(_finite(row["abs_delta"]))))
            self._tracking_started_at_utc = tracking.astimezone(timezone.utc)
            self._peaks = self._dedupe_and_prune(peaks, self._now_utc())
            self._peak_history_status = "STATE_LOADED"
        except Exception as exc:
            self._peaks = []
            self._tracking_started_at_utc = self._now_utc()
            self._state_error = f"STATE_LOAD_FAILED:{type(exc).__name__}:{exc}"

    def _bootstrap_from_research_archive(self) -> bool:
        """Hydrate the bounded runtime cache from the canonical JSONL archive."""
        cutoff = self._now_utc()
        lower = cutoff - timedelta(hours=24)
        zone = ZoneInfo(self.config.source_timezone)
        required_dates = list(
            _dates_inclusive(lower.astimezone(zone).date(), cutoff.astimezone(zone).date())
        )
        paths = [
            self.config.research_archive_dir / f"{day.isoformat()}.jsonl"
            for day in required_dates
        ]
        missing = [path.name for path in paths if not path.exists()]
        if missing:
            self._peak_history_status = "ARCHIVE_INCOMPLETE"
            return False

        archive_peaks: list[PeakHistoryEvent] = []
        try:
            for path in paths:
                with path.open("r", encoding="utf-8-sig") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"invalid JSON at {path.name}:{line_number}"
                            ) from exc
                        event = str(row.get("event") or "")
                        if event not in {"DELTA_MAX", "DELTA_MIN"}:
                            continue
                        event_ts_utc = parse_runtime_timestamp(
                            row.get("ts"), self.config.source_timezone
                        )
                        if not lower <= event_ts_utc <= cutoff:
                            continue
                        expected_side = "LONG" if event == "DELTA_MAX" else "SHORT"
                        raw_side = str(row.get("kind") or expected_side).upper()
                        if raw_side != expected_side:
                            raise ValueError(
                                f"event/side mismatch at {path.name}:{line_number}"
                            )
                        archive_peaks.append(
                            PeakHistoryEvent(
                                event_ts_utc=event_ts_utc,
                                side=expected_side,
                                abs_delta=abs(_finite(row.get("delta"))),
                            )
                        )
        except Exception as exc:
            self._state_error = (
                f"ARCHIVE_BOOTSTRAP_FAILED:{type(exc).__name__}:{exc}"
            )
            self._peak_history_status = "ARCHIVE_INVALID"
            return False

        self._peaks = self._dedupe_and_prune([*self._peaks, *archive_peaks], cutoff)
        self._tracking_started_at_utc = min(self._tracking_started_at_utc, lower)
        self._state_error = None
        if not self._persist_state():
            self._peak_history_status = "ARCHIVE_BOOTSTRAP_STATE_WRITE_FAILED"
            return False
        self._peak_history_status = "ARCHIVE_BOOTSTRAPPED"
        return True

    def _dedupe_and_prune(self, peaks: Iterable[PeakHistoryEvent], cutoff: datetime) -> list[PeakHistoryEvent]:
        lower = cutoff - timedelta(hours=24)
        unique: dict[tuple[datetime, str, float], PeakHistoryEvent] = {}
        for peak in peaks:
            if lower <= peak.event_ts_utc <= cutoff:
                unique[(peak.event_ts_utc, peak.side, peak.abs_delta)] = peak
        return sorted(unique.values(), key=lambda item: (item.event_ts_utc, item.side, item.abs_delta))

    def _persist_state(self) -> bool:
        path = self.config.state_path
        temp_path = path.with_name(path.name + ".tmp")
        payload = {
            "schema": STATE_SCHEMA,
            "rule_id": self.config.rule_id,
            "tracking_started_at_utc": self._tracking_started_at_utc.isoformat(),
            "updated_at_utc": self._now_utc().isoformat(),
            "peaks": [peak.to_dict() for peak in self._peaks],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(path)
            return True
        except Exception as exc:
            self._state_error = f"STATE_WRITE_FAILED:{type(exc).__name__}:{exc}"
            return False

    def record_peak(self, *, event_ts: Any, side: str, delta: float) -> bool:
        if self.config.mode == "off":
            return True
        try:
            event_ts_utc = parse_runtime_timestamp(event_ts, self.config.source_timezone)
            side_value = str(side).upper()
            if side_value not in {"LONG", "SHORT"}:
                raise ValueError("invalid side")
            peak = PeakHistoryEvent(event_ts_utc, side_value, abs(_finite(delta)))
            self._peaks = self._dedupe_and_prune([*self._peaks, peak], event_ts_utc)
            return self._persist_state()
        except Exception as exc:
            self._state_error = f"STATE_RECORD_FAILED:{type(exc).__name__}:{exc}"
            return False

    def _peak_percentile(self, *, cutoff: datetime, side: str, delta: float) -> tuple[int, float | None]:
        self._peaks = self._dedupe_and_prune(self._peaks, cutoff)
        values = [peak.abs_delta for peak in self._peaks if peak.side == side]
        history_complete = self._tracking_started_at_utc <= cutoff - timedelta(hours=24)
        if not history_complete or not values:
            return len(values), None
        current = abs(_finite(delta))
        percentile = sum(value <= current for value in values) / len(values) * 100.0
        return len(values), percentile

    def _parse_enriched_ts(self, value: Any) -> datetime:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.config.enriched_timezone))
        return parsed.astimezone(timezone.utc)

    def _load_enriched_features(self, cutoff: datetime, side: str) -> EnrichedFeatureWindow:
        start_240 = cutoff - timedelta(minutes=239)
        bars: dict[datetime, dict[str, Any]] = {}
        duplicate = False
        paths_found = 0
        last_ts: datetime | None = None
        try:
            for day in _dates_inclusive(start_240.date(), cutoff.date()):
                path = self.config.enriched_feed_dir / f"{day.isoformat()}.csv"
                if not path.exists():
                    continue
                paths_found += 1
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    required = {"Timestamp", "BuyQty", "SellQty", "OpenInterest", "IsSynthetic"}
                    missing = required.difference(reader.fieldnames or [])
                    if missing:
                        return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, f"missing_columns={sorted(missing)}")
                    for row in reader:
                        ts = self._parse_enriched_ts(row.get("Timestamp"))
                        if ts > cutoff:
                            continue
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                        if ts < start_240:
                            continue
                        if ts in bars:
                            duplicate = True
                        bars[ts] = row
        except Exception as exc:
            return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, f"feed_read_failed:{type(exc).__name__}:{exc}")

        if paths_found == 0:
            return EnrichedFeatureWindow(None, False, None, "MISSING", None, "no_enriched_feed_files")
        if duplicate:
            return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, "duplicate_minutes")
        if last_ts is None or last_ts < cutoff:
            return EnrichedFeatureWindow(None, False, None, "STALE", last_ts, "exact_cutoff_missing")

        expected_240 = [start_240 + timedelta(minutes=index) for index in range(240)]
        if any(ts not in bars for ts in expected_240):
            return EnrichedFeatureWindow(None, False, None, "MISSING", last_ts, "non_contiguous_240m")
        rows_240 = [bars[ts] for ts in expected_240]
        try:
            if any(str(row.get("IsSynthetic") or "").strip().lower() not in REAL_VALUES for row in rows_240):
                return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, "synthetic_240m")
            buy = sum(_finite(row.get("BuyQty")) for row in rows_240)
            sell = sum(_finite(row.get("SellQty")) for row in rows_240)
            total = buy + sell
            if total <= 0:
                return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, "non_positive_240m_volume")
            raw_delta_pct = (buy - sell) / total
            directional = raw_delta_pct if side == "LONG" else -raw_delta_pct

            rows_60 = rows_240[-60:]
            oi = [_finite(row.get("OpenInterest")) for row in rows_60]
            oi_change = oi[-1] - oi[0]
            return EnrichedFeatureWindow(oi_change, True, directional, "EXACT", last_ts)
        except Exception as exc:
            return EnrichedFeatureWindow(None, False, None, "INVALID", last_ts, f"invalid_numeric:{type(exc).__name__}:{exc}")

    def evaluate(self, *, signal_ts: Any, side: str, delta: float) -> RuntimeFilterEvaluation:
        started = time.monotonic()
        if self.config.mode == "off":
            return RuntimeFilterEvaluation(
                configured_mode="off",
                rule_id=self.config.rule_id,
                signal_ts_utc=None,
                decision=_unknown_decision(),
                same_side_peak_count_24h=0,
                same_side_peak_percentile_24h=None,
                oi_change_60m=None,
                oi_trusted_60m=False,
                directional_delta_pct_240m=None,
                feature_status="DISABLED",
                enriched_last_ts_utc=None,
                evaluation_ms=(time.monotonic() - started) * 1000.0,
                peak_history_status=self._peak_history_status,
            )
        try:
            if self.config.rule_id != RULE_ID:
                raise ValueError(f"unsupported rule_id={self.config.rule_id}")
            cutoff = parse_runtime_timestamp(signal_ts, self.config.source_timezone)
            side_value = str(side).upper()
            if side_value not in {"LONG", "SHORT"}:
                raise ValueError("invalid side")
            count, percentile = self._peak_percentile(cutoff=cutoff, side=side_value, delta=delta)
            window = self._load_enriched_features(cutoff, side_value)
            decision = evaluate_loss_avoidance_policy(
                same_side_peak_percentile_24h=percentile,
                oi_change_60m=window.oi_change_60m,
                oi_trusted_60m=window.oi_trusted_60m,
                directional_delta_pct_240m=window.directional_delta_pct_240m,
            )
            elapsed = (time.monotonic() - started) * 1000.0
            fail_open: str | None = None
            if self._state_error:
                fail_open = self._state_error
            elif window.feature_status != "EXACT":
                fail_open = f"ENRICHED_{window.feature_status}"
            elif elapsed > self.config.evaluation_budget_ms:
                fail_open = "EVALUATION_BUDGET_EXCEEDED"
            return RuntimeFilterEvaluation(
                configured_mode=self.config.mode,
                rule_id=self.config.rule_id,
                signal_ts_utc=cutoff,
                decision=decision,
                same_side_peak_count_24h=count,
                same_side_peak_percentile_24h=percentile,
                oi_change_60m=window.oi_change_60m,
                oi_trusted_60m=window.oi_trusted_60m,
                directional_delta_pct_240m=window.directional_delta_pct_240m,
                feature_status=window.feature_status,
                enriched_last_ts_utc=window.enriched_last_ts_utc,
                evaluation_ms=elapsed,
                fail_open_reason=fail_open,
                detail=window.detail,
                peak_history_status=self._peak_history_status,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            return RuntimeFilterEvaluation(
                configured_mode=self.config.mode,
                rule_id=self.config.rule_id,
                signal_ts_utc=None,
                decision=_unknown_decision(),
                same_side_peak_count_24h=0,
                same_side_peak_percentile_24h=None,
                oi_change_60m=None,
                oi_trusted_60m=False,
                directional_delta_pct_240m=None,
                feature_status="INVALID",
                enriched_last_ts_utc=None,
                evaluation_ms=elapsed,
                fail_open_reason=f"EVALUATION_FAILED:{type(exc).__name__}",
                detail=str(exc),
                peak_history_status=self._peak_history_status,
            )
