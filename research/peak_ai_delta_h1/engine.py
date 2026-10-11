"""Delta-first, frozen-zone, four-hour H1 research candidate lifecycle."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import math

from deltascout.research_bundle.scout_backtester.contracts import Candidate

FAMILY = "PEAK_AI_DELTA_H1_SHORT_V1"
HORIZON = timedelta(hours=4)


class DeltaH1Engine:
    def __init__(self, monitor):
        self.monitor = monitor
        self.pending = {}
        self.attempted = set()
        self.audit = []
        self.events = []
        self.zone_evidence = []
        self.candidates = []
        self.last_bar = None
        self.hour = []
        self.confirmed_keys = {}

    def _event(self, row, ts, event, **fields):
        self.events.append({"seed_id": row["seed_id"], "ts": ts.isoformat(),
                            "event": event, "zone_id": row.get("zone_id", ""), **fields})

    def _finish(self, row, ts, status):
        row["status"] = status
        row["finished_at"] = ts.isoformat()
        self._event(row, ts, status)
        self.pending.pop(row["zone_id"], None)

    def step(self, bar, seeds=()):
        if self.last_bar is not None and bar.ts <= self.last_bar.ts:
            raise ValueError("feed must advance strictly")
        valid = (not bar.is_synthetic and bar.volume > 0
                 and all(math.isfinite(x) for x in (bar.open,bar.high,bar.low,bar.close,bar.volume))
                 and 0 < bar.low <= min(bar.open,bar.close) <= max(bar.open,bar.close) <= bar.high)
        gap = self.last_bar is not None and bar.ts-self.last_bar.ts != timedelta(minutes=1)
        if gap or not valid:
            for row in list(self.pending.values()):
                self._finish(row, bar.ts, "CANCELLED_FEED_GAP" if gap else "CANCELLED_INVALID_BAR")
            self.hour = []
        bucket = (bar.ts-timedelta(minutes=1)).replace(minute=0,second=0,microsecond=0)
        if self.hour and (self.hour[0].ts-timedelta(minutes=1)).replace(minute=0,second=0,microsecond=0) != bucket:
            self.hour = []
        if valid:
            self.hour.append(bar)
        closed_h1 = (valid and bar.ts.minute == 0 and bar.ts.second == 0
                     and len(self.hour) == 60 and self.hour[0].ts == bar.ts-timedelta(minutes=59))
        for row in list(self.pending.values()):
            if bar.ts > row["_deadline"]:
                self._finish(row, row["_deadline"], "EXPIRED")
                continue
            row["sweep_high"] = max(row["sweep_high"], bar.high)
            if closed_h1 and bar.ts > row["_seed"].ts:
                self._event(row, bar.ts, "H1_CLOSE", close=bar.close, lower=row["lower"],
                            deadline=row["deadline"], complete_minutes=60)
                if bar.close < row["lower"]:
                    self._confirm(row, bar)
                    continue
            if bar.ts == row["_deadline"]:
                self._finish(row, bar.ts, "EXPIRED")
        for seed in seeds:
            if seed.ts != bar.ts:
                raise ValueError("seed must be evaluated at its exact minute")
            row = {"seed_id": seed.seed_id, "seed_ts": seed.ts.isoformat(), "event": seed.event,
                   "delta": seed.delta, "volume": seed.volume, "price": bar.close,
                   "source_path": seed.source_path, "source_line": seed.source_line}
            self.audit.append(row)
            if abs(seed.delta-(bar.buy_qty-bar.sell_qty)) > .011 or abs(seed.volume-bar.volume) > .011:
                raise ValueError(f"journal/feed mismatch {seed.seed_id}")
            if seed.event != "DELTA_MAX":
                row["status"] = "OUT_OF_SCOPE_LONG_HYPOTHESIS"
                continue
            if not valid or gap:
                row["status"] = "INVALID_TRIGGER_CONTEXT"
                continue
            zones, counts, evidence = self.monitor.query(seed.ts)
            row.update(counts)
            self.zone_evidence.extend(dict(seed_id=seed.seed_id, **e) for e in evidence)
            if not zones:
                row["status"] = "NO_ELIGIBLE_ZONE"
                self._event(row, bar.ts, row["status"])
                continue
            zone = zones[0]
            zone_id = zone["zone_id"]
            episode = (zone_id, zone["crossed_at"])
            row.update(zone_id=zone_id, lower=float(zone["price_lower"]), upper=float(zone["price_upper"]),
                       bucket=zone["bucket"], significance_score=zone["significance_score"],
                       level_available_at=zone["available_at"], crossed_at=zone["crossed_at"],
                       sweep_start_ts=zone["sweep_start_ts"], sweep_high=zone["sweep_high"])
            if zone_id in self.pending:
                row.update(status="DUPLICATE_PENDING_ZONE", parent_seed_id=self.pending[zone_id]["seed_id"])
                self._event(row, bar.ts, row["status"], parent_seed_id=row["parent_seed_id"])
                continue
            if episode in self.attempted:
                row["status"] = "EPISODE_ALREADY_ATTEMPTED"
                continue
            self.attempted.add(episode)
            deadline = seed.ts+HORIZON
            row.update(status="PENDING", deadline=deadline.isoformat(), _deadline=deadline, _seed=seed)
            self.pending[zone_id] = row
            self._event(row, bar.ts, "ARMED", lower=row["lower"], upper=row["upper"], deadline=row["deadline"])
        self.last_bar = bar

    def _confirm(self, row, bar):
        seed = row["_seed"]
        key = (bar.ts, "SHORT")
        if key in self.confirmed_keys:
            row["parent_candidate_id"] = self.confirmed_keys[key]
            self._finish(row, bar.ts, "DUPLICATE_CONFIRMATION")
            return
        candidate_id = "PAH1_"+hashlib.sha256(f"{seed.seed_id}|{row['zone_id']}|{bar.ts.isoformat()}".encode()).hexdigest()[:20]
        self.confirmed_keys[key] = candidate_id
        self._finish(row, bar.ts, "CONFIRMED")
        row.update(candidate_id=candidate_id, confirmation_price=bar.close,
                   stop_anchor=row["sweep_high"]*1.0001)
        flags = {k:v for k,v in row.items() if not k.startswith("_")}
        flags.update(sweep_stop_price=row["stop_anchor"], sweep_high=row["sweep_high"],
                     sweep_end_ts=bar.ts.isoformat(), stop_buffer_fraction=.0001)
        self.candidates.append(Candidate(candidate_id, seed.local_ts, bar.ts, "SHORT", FAMILY,
            FAMILY, None, bar.close, seed.delta, seed.volume, abs(seed.delta)/seed.volume,
            None,None,None,None,flags,seed.source_path,seed.row_hash))

    def finish(self):
        if self.last_bar:
            for row in list(self.pending.values()):
                self._finish(row, self.last_bar.ts, "RIGHT_CENSORED_END_OF_DATA")
        return [{k:v for k,v in r.items() if not k.startswith("_")} for r in self.audit]
