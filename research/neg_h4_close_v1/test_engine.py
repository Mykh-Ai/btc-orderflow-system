from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from research.neg_h4_close_v1.engine import NegCloseEngine, canonical_bucket
from deltascout.research_bundle.scout_backtester.contracts import FeedBar, ReplayConfig
from deltascout.research_bundle.scout_backtester.execution_policy import build_execution_plan
from market_monitor.closed_structure_adapter import minute_frame
from market_monitor.structure import aggregate_timeframe
T=datetime(2026,3,20,8,tzinfo=timezone.utc)
def bars(n=480,start=T):
    return [FeedBar(start+timedelta(minutes=i),102,103,101,102,10,2,8,False,'TEST',False,'test',i) for i in range(1,n+1)]
def seed(b,identity='a',event='DELTA_MIN'):
    return SimpleNamespace(seed_id=identity,ts=b.ts,local_ts=b.ts.isoformat(),event=event,
        delta=b.buy_qty-b.sell_qty,volume=b.volume,source_path='test',source_line=1,row_hash=identity)
class Monitor:
    def __init__(self,tf='H4'):
        self.zone=dict(zone_id='z',price_lower=99.,price_upper=101.,bucket='PRIMARY',
            significance_score=90.,available_at=(T-timedelta(days=1)).isoformat(),
            crossed_at=(T+timedelta(minutes=1)).isoformat(),sweep_start_ts=(T+timedelta(minutes=1)).isoformat(),
            sweep_high=103.,level_type=tf+'_SWING_HIGH',source_timeframe=tf)
    def query(self,ts):return [self.zone],{},[]
def run(seq,triggers,monitor=None,tf='H4'):
    e=NegCloseEngine(monitor or Monitor(),tf)
    for b in seq:e.step(b,triggers.get(b.ts,()))
    return e
@pytest.mark.parametrize('hour',[0,4,8,12,16,20])
def test_canonical_h4_boundaries(hour):
    start=T.replace(hour=hour);seq=bars(240,start)
    native=aggregate_timeframe(minute_frame(seq),'H4')
    assert len(native)==1 and native.iloc[0].Timestamp.to_pydatetime()==start
    assert canonical_bucket(seq[0].ts)==canonical_bucket(seq[-1].ts)==start
    assert canonical_bucket(seq[-1].ts+timedelta(minutes=1))==start+timedelta(hours=4)
@pytest.mark.parametrize('idx',[69,229])
def test_only_full_canonical_close_not_delta_rolling(idx):
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    triggers={seq[idx].ts:[seed(seq[idx])]}
    partial=run(seq[:-1],triggers);assert not partial.candidates
    e=run(seq,triggers);assert len(e.candidates)==1
    assert e.candidates[0].signal_ts_utc==T+timedelta(hours=4)
    assert e.candidates[0].signal_ts_utc!=seq[idx].ts+timedelta(hours=4)
def test_delta_1205_next_1600():
    seq=bars(480);seq[-1]=replace(seq[-1],close=98,low=97)
    e=run(seq,{seq[244].ts:[seed(seq[244])]});assert e.candidates[0].signal_ts_utc==T+timedelta(hours=8)
@pytest.mark.parametrize('close,confirmed',[(98.,True),(99.,False),(100.,False),(102.,False)])
def test_strict_h4_close_below_not_equality_or_wick(close,confirmed):
    seq=bars(310);seq[239]=replace(seq[239],close=close,low=90)
    e=run(seq,{seq[69].ts:[seed(seq[69])]});assert bool(e.candidates)==confirmed
    if not confirmed:assert e.audit[0]['status']=='EXPIRED'
def test_h1_or_minute_close_and_wick_do_not_confirm():
    seq=bars(310)
    for i in [80,119,179]:seq[i]=replace(seq[i],close=98,low=90)
    seq[239]=replace(seq[239],low=90)
    e=run(seq,{seq[69].ts:[seed(seq[69])]})
    assert not e.candidates and e.audit[0]['status']=='EXPIRED'
def test_exact_deadline_allowed_later_h4_forbidden():
    seq=bars(480);seq[-1]=replace(seq[-1],close=98,low=97)
    exact=run(seq,{seq[239].ts:[seed(seq[239])]})
    assert exact.candidates[0].signal_ts_utc==seq[239].ts+timedelta(hours=4)
    later=run(seq,{seq[238].ts:[seed(seq[238])]})
    assert not later.candidates and later.audit[0]['status']=='EXPIRED'
def test_first_neg_owns_repeat_no_restart_and_episode_dedup():
    seq=bars(390)
    e=run(seq,{seq[i].ts:[seed(seq[i],str(i))] for i in [69,180,320]})
    assert [r['status'] for r in e.audit]==['EXPIRED','DUPLICATE_PENDING_ZONE','EPISODE_ALREADY_ATTEMPTED']
    assert e.audit[0]['deadline']==(seq[69].ts+timedelta(hours=4)).isoformat()
    assert e.audit[1]['parent_seed_id']=='69'
def test_frozen_zone_does_not_mutate():
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    m=Monitor();e=NegCloseEngine(m);frozen=deepcopy(m.zone)
    for i,b in enumerate(seq):
        e.step(b,[seed(b)] if i==69 else [])
        if i==70:m.zone.update(price_lower=50,price_upper=60,significance_score=1,level_type='MUTATED')
    c=e.candidates[0];assert c.shadow_flags['frozen_zone']==frozen
    assert c.shadow_flags['price_lower']==99 and c.shadow_flags['level_type']=='H4_SWING_HIGH'
@pytest.mark.parametrize('kind',['missing','synthetic','zero_volume'])
def test_feed_failure_cancels_pending(kind):
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97);triggers={seq[69].ts:[seed(seq[69])]}
    if kind=='missing':seq.pop(100)
    elif kind=='synthetic':seq[100]=replace(seq[100],is_synthetic=True)
    else:seq[100]=replace(seq[100],volume=0)
    e=run(seq,triggers);assert not e.candidates
    assert e.audit[0]['status']==('CANCELLED_FEED_GAP' if kind=='missing' else 'CANCELLED_INVALID_BAR')
def test_partial_h4_before_seed_cannot_confirm():
    seq=bars(240)[30:];seq[-1]=replace(seq[-1],close=98,low=97)
    e=run(seq,{seq[40].ts:[seed(seq[40])]});assert not e.candidates
    assert e.finish()[0]['status']=='RIGHT_CENSORED_END_OF_DATA'
def test_sweep_includes_high_through_h4_excludes_future_and_native_stop_validates():
    seq=bars(300);seq[100]=replace(seq[100],high=109);seq[230]=replace(seq[230],high=110)
    seq[239]=replace(seq[239],high=112,close=98,low=97);seq[260]=replace(seq[260],high=1000)
    e=run(seq,{seq[69].ts:[seed(seq[69])]});c=e.candidates[0]
    assert c.shadow_flags['sweep_high']==112 and c.shadow_flags['sweep_end_ts']==seq[239].ts.isoformat()
    assert c.shadow_flags['stop_anchor']==112*1.0001
    plan=build_execution_plan(c,seq,ReplayConfig(experiment_id='test',initial_stop_policy='candidate_sweep'))
    assert plan.initial_stop_price_usdt==112.02
    prefix=run(seq[:240],{seq[69].ts:[seed(seq[69])]})
    assert c.to_dict()==prefix.candidates[0].to_dict()
@pytest.mark.parametrize('tf',['H1','H4'])
def test_level_types_remain_identifiable(tf):
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    c=run(seq,{seq[69].ts:[seed(seq[69])]},Monitor(tf)).candidates[0]
    assert c.shadow_flags['level_type']==tf+'_SWING_HIGH' and c.shadow_flags['source_timeframe']==tf
@pytest.mark.parametrize('event',['DELTA_MIN','DELTA_MAX'])
def test_negative_numeric_sign_not_event_label(event):
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    c=run(seq,{seq[69].ts:[seed(seq[69],event=event)]}).candidates[0]
    assert c.side=='SHORT' and c.delta<0
@pytest.mark.parametrize('buy,sell',[(8,2),(5,5)])
def test_positive_and_zero_do_not_arm(buy,sell):
    seq=bars(240);seq[69]=replace(seq[69],buy_qty=buy,sell_qty=sell);seq[-1]=replace(seq[-1],close=98,low=97)
    e=run(seq,{seq[69].ts:[seed(seq[69])]});assert not e.candidates
    assert e.audit[0]['status']=='OUT_OF_SCOPE_NON_NEGATIVE'
def test_no_peak_emit():
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    e=run(seq,{seq[69].ts:[seed(seq[69],event='PEAK_EMIT')]});assert not e.candidates
    assert e.audit[0]['status']=='OUT_OF_SCOPE_NON_DELTA_EVENT'
def test_duplicate_confirmation_one_trade():
    seq=bars(240);seq[-1]=replace(seq[-1],close=98,low=97)
    m=Monitor();e=NegCloseEngine(m)
    for i,b in enumerate(seq):
        if i==80:m.zone['zone_id']='second'
        e.step(b,[seed(b,str(i))] if i in [69,80] else [])
    assert len(e.candidates)==1
    assert [r['status'] for r in e.audit]==['CONFIRMED','DUPLICATE_CONFIRMATION']
def test_h1_control_changes_confirmation_only():
    seq=bars(240);seq[119]=replace(seq[119],close=98,low=97);seq[-1]=replace(seq[-1],close=98,low=97)
    triggers={seq[69].ts:[seed(seq[69])]}
    h1=run(seq,triggers,tf='H1');h4=run(seq,triggers)
    assert h1.candidates[0].signal_ts_utc==seq[119].ts
    assert h4.candidates[0].signal_ts_utc==seq[239].ts
    assert h1.candidates[0].shadow_flags['frozen_zone']==h4.candidates[0].shadow_flags['frozen_zone']
