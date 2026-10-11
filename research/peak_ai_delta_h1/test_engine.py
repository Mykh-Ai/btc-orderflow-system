from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from deltascout.research_bundle.scout_backtester.contracts import FeedBar, ReplayConfig, InitialStopSelectionError
from deltascout.research_bundle.scout_backtester.execution_policy import build_execution_plan
from research.peak_ai_delta_h1.engine import DeltaH1Engine

T = datetime(2026,3,20,12,tzinfo=timezone.utc)

def bars(minutes=360):
    return [FeedBar(T+timedelta(minutes=i),102,103,101,102,10,8,2,False,"TEST",False,"test",i)
            for i in range(1,minutes+1)]

def seed(bar, identity="seed", event="DELTA_MAX"):
    return SimpleNamespace(seed_id=identity,ts=bar.ts,local_ts=bar.ts.isoformat(),event=event,
                           delta=6.,volume=10.,source_path="test",source_line=1,row_hash=identity)

class Monitor:
    def __init__(self):
        self.queries=[]
    def query(self,ts):
        self.queries.append(ts)
        return [dict(zone_id="zone",price_lower=99.,price_upper=101.,bucket="PRIMARY",
                     significance_score=90.,available_at=(T-timedelta(days=1)).isoformat(),
                     crossed_at=(T+timedelta(minutes=1)).isoformat(),sweep_start_ts=(T+timedelta(minutes=1)).isoformat(),
                     sweep_high=103.)],{},[]

def run(sequence, seed_map, monitor=None):
    engine=DeltaH1Engine(monitor or Monitor())
    for b in sequence:engine.step(b,seed_map.get(b.ts,()))
    return engine

def test_intrabar_low_does_not_confirm_and_entry_uses_later_h1_close():
    seq=bars(120)
    seq[30]=replace(seq[30],low=95.)
    seq[-1]=replace(seq[-1],low=97.,close=98.)
    e=run(seq,{seq[16].ts:[seed(seq[16])]})
    assert len(e.candidates)==1
    assert e.candidates[0].signal_ts_utc==T+timedelta(hours=2)
    assert [x['close'] for x in e.events if x['event']=='H1_CLOSE']==[102.,98.]

@pytest.mark.parametrize("close",[99.,100.,101.])
def test_equal_or_inside_zone_is_not_confirmation(close):
    seq=bars(300)
    seq[59]=replace(seq[59],low=98.,close=close)
    e=run(seq,{seq[16].ts:[seed(seq[16])]})
    assert not e.candidates
    assert e.audit[0]['status']=='EXPIRED'
    assert e.audit[0]['finished_at']==(seq[16].ts+timedelta(hours=4)).isoformat()

def test_repeat_delta_never_extends_timer_or_rearms_same_episode():
    seq=bars(310)
    e=run(seq,{seq[16].ts:[seed(seq[16],'a')],seq[200].ts:[seed(seq[200],'b')],seq[270].ts:[seed(seq[270],'c')]})
    assert [r['status'] for r in e.audit]==['EXPIRED','DUPLICATE_PENDING_ZONE','EPISODE_ALREADY_ATTEMPTED']
    assert e.audit[0]['deadline']==(seq[16].ts+timedelta(hours=4)).isoformat()

def test_h1_exact_deadline_is_included_but_later_close_is_not():
    seq=bars(301)
    seq[299]=replace(seq[299],low=97.,close=98.)
    e=run(seq,{seq[59].ts:[seed(seq[59])]})
    assert len(e.candidates)==1 and e.candidates[0].signal_ts_utc==seq[299].ts
    later=run(seq,{seq[58].ts:[seed(seq[58])]})
    assert not later.candidates and later.audit[0]['status']=='EXPIRED'

def test_gap_cancels_pending_and_partial_h1_never_confirms():
    seq=bars(120)
    seq[-1]=replace(seq[-1],close=98.,low=97.)
    seq.pop(50)
    e=run(seq,{seq[16].ts:[seed(seq[16])]})
    assert not e.candidates and e.audit[0]['status']=='CANCELLED_FEED_GAP'

def test_end_of_data_is_censored_not_expired():
    seq=bars(80);e=run(seq,{seq[16].ts:[seed(seq[16])]})
    audit=e.finish()
    assert audit[0]['status']=='RIGHT_CENSORED_END_OF_DATA'

def test_min_delta_does_not_query_short_monitor():
    seq=bars(80);m=Monitor();e=run(seq,{seq[16].ts:[seed(seq[16],event='DELTA_MIN')]},m)
    assert not m.queries and e.audit[0]['status']=='OUT_OF_SCOPE_LONG_HYPOTHESIS'

def test_sweep_stop_uses_high_until_confirmation_and_native_plan_validates_it():
    seq=bars(150)
    seq[45]=replace(seq[45],high=110.)
    seq[119]=replace(seq[119],low=97.,close=98.)
    seq[140]=replace(seq[140],high=1000.)
    e=run(seq,{seq[16].ts:[seed(seq[16])]})
    c=e.candidates[0]
    assert c.shadow_flags['sweep_high']==110.
    cfg=ReplayConfig(experiment_id='test',initial_stop_policy='candidate_sweep')
    plan=build_execution_plan(c,seq,cfg)
    assert plan.initial_stop_price_usdt==110.02
    bad=replace(c,shadow_flags={**c.shadow_flags,'sweep_stop_price':105.})
    with pytest.raises(InitialStopSelectionError,match='ANCHOR_MISMATCH'):
        build_execution_plan(bad,seq,cfg)
    missing=seq[:40]+seq[41:]
    with pytest.raises(InitialStopSelectionError,match='INCOMPLETE'):
        build_execution_plan(c,missing,cfg)

def test_future_price_changes_cannot_change_confirmed_candidate():
    seq=bars(240);seq[119]=replace(seq[119],close=98.,low=97.)
    full=run(seq,{seq[16].ts:[seed(seq[16])]})
    prefix=run(seq[:120],{seq[16].ts:[seed(seq[16])]})
    assert [c.to_dict() for c in full.candidates]==[c.to_dict() for c in prefix.candidates]

def test_mismatched_journal_cannot_silently_enter():
    seq=bars(20);s=seed(seq[16]);s.delta=9
    with pytest.raises(ValueError,match='journal/feed mismatch'):
        run(seq,{seq[16].ts:[s]})
