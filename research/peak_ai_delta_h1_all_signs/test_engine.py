"""Regression coverage for the omitted negative-trigger correction."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from deltascout.research_bundle.scout_backtester.contracts import FeedBar

T = datetime(2026,3,20,12,tzinfo=timezone.utc)
def bars(minutes=360):
    return [FeedBar(T+timedelta(minutes=i),102,103,101,102,10,8,2,False,"TEST",False,"test",i)
            for i in range(1,minutes+1)]
def seed(bar, identity="seed", event="DELTA_MAX"):
    return SimpleNamespace(seed_id=identity,ts=bar.ts,local_ts=bar.ts.isoformat(),event=event,
                           delta=6.,volume=10.,source_path="test",source_line=1,row_hash=identity)
class Monitor:
    def query(self,ts):
        return [dict(zone_id="zone",price_lower=99.,price_upper=101.,bucket="PRIMARY",
                     significance_score=90.,available_at=(T-timedelta(days=1)).isoformat(),
                     crossed_at=(T+timedelta(minutes=1)).isoformat(),sweep_start_ts=(T+timedelta(minutes=1)).isoformat(),
                     sweep_high=103.)],{},[]
from research.peak_ai_delta_h1_all_signs.engine import DeltaH1Engine


def test_both_numeric_signs_and_both_event_names_confirm_only_short(event, sign):
    sequence = bars(120)
    sequence[16] = replace(sequence[16], buy_qty=8 if sign > 0 else 2, sell_qty=2 if sign > 0 else 8)
    sequence[-1] = replace(sequence[-1], low=97., close=98.)
    trigger = seed(sequence[16], event=event)
    trigger.delta = sign*6.
    engine = DeltaH1Engine(Monitor())
    for bar in sequence:
        engine.step(bar, [trigger] if bar.ts == trigger.ts else [])
    assert len(engine.candidates) == 1
    candidate = engine.candidates[0]
    assert candidate.side == 'SHORT'
    assert candidate.delta == trigger.delta
    assert candidate.shadow_flags['event'] == event
    assert candidate.signal_ts_utc == sequence[-1].ts


def test_other_sign_shares_pending_zone_without_restarting_deadline(first_sign):
    sequence = bars(300)
    triggers = {}
    for index, sign in [(16, first_sign), (180, -first_sign)]:
        sequence[index] = replace(sequence[index], buy_qty=8 if sign > 0 else 2, sell_qty=2 if sign > 0 else 8)
        trigger = seed(sequence[index], identity=str(index), event='DELTA_MAX' if sign > 0 else 'DELTA_MIN')
        trigger.delta = sign*6.
        triggers[trigger.ts] = [trigger]
    engine = DeltaH1Engine(Monitor())
    for bar in sequence:
        engine.step(bar, triggers.get(bar.ts, []))
    assert [row['status'] for row in engine.audit] == ['EXPIRED', 'DUPLICATE_PENDING_ZONE']
    assert engine.audit[0]['deadline'] == (sequence[16].ts+timedelta(hours=4)).isoformat()
    assert engine.audit[1]['parent_seed_id'] == '16'


def test_strategy_diff_is_only_event_admission_and_research_identity():
    here = Path(__file__).resolve().parent
    original = (here.parent/'peak_ai_delta_h1/engine.py').read_text()
    expected = original.replace('PEAK_AI_DELTA_H1_SHORT_V1', 'PEAK_AI_DELTA_H1_ALL_SIGNS_SHORT_V2')
    expected = expected.replace('if seed.event != "DELTA_MAX":\n                row["status"] = "OUT_OF_SCOPE_LONG_HYPOTHESIS"',
                                'if seed.event not in {"DELTA_MAX", "DELTA_MIN"}:\n                row["status"] = "OUT_OF_SCOPE_NON_DELTA_EVENT"')
    assert (here/'engine.py').read_text() == expected


def suite():
    result = unittest.TestSuite()
    for event in ['DELTA_MAX','DELTA_MIN']:
        for sign in [-1,1]:
            result.addTest(unittest.FunctionTestCase(lambda e=event,s=sign: test_both_numeric_signs_and_both_event_names_confirm_only_short(e,s), description=f"SHORT admission {event} sign {sign}"))
    for sign in [-1,1]:
        result.addTest(unittest.FunctionTestCase(lambda s=sign: test_other_sign_shares_pending_zone_without_restarting_deadline(s), description=f"Shared timer first sign {sign}"))
    result.addTest(unittest.FunctionTestCase(test_strategy_diff_is_only_event_admission_and_research_identity))
    return result

if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
