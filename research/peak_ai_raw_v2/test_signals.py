from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from research.peak_ai_raw_v2.signals import Seed,generate
from deltascout.research_bundle.scout_backtester.contracts import FeedBar

def fixture():
    t=datetime(2026,3,20,tzinfo=timezone.utc)
    bars=[FeedBar(t+timedelta(minutes=i),100,101,99,100,100,55,45,False,'LEGACY_BTCUSDT_SPOT',False,'fixture',i) for i in range(61)]
    bars[-1]=replace(bars[-1],high=104,low=99,close=100,buy_qty=85,sell_qty=15)
    seed=Seed('seed',bars[-1].ts,'2026-03-20 02:00:00','LONG',70,100,'DELTA_MAX','fixture',1,'hash')
    return bars,seed

def test_all_raw_seeds_have_both_immediate_directions_without_peak_gate():
    bars,s=fixture();g,a,_=generate([s],bars)
    assert g['immediate_follow__all'][0].side=='LONG'
    assert g['immediate_fade__all'][0].side=='SHORT'
    assert a[0]['status']=='USABLE'

def test_delayed_entry_is_after_confirming_close_prefix_invariant():
    b,s=fixture();g,_,_=generate([s],b)
    assert not g['break_follow__all']
    b.append(replace(b[-1],ts=b[-1].ts+timedelta(minutes=1),high=106,close=105))
    g,_,_=generate([s],b);assert g['break_follow__all'][0].signal_ts_utc==b[-1].ts
    earlier={k:list(v) for k,v in g.items()};cutoff=b[-1].ts
    b.append(replace(b[-1],ts=b[-1].ts+timedelta(minutes=1),low=97,close=98))
    later,_,_=generate([s],b)
    for k in earlier:assert earlier[k]==[c for c in later[k] if c.signal_ts_utc<=cutoff]

def test_intrabar_touch_without_close_does_not_confirm():
    b,s=fixture();b.append(replace(b[-1],ts=b[-1].ts+timedelta(minutes=1),high=110,close=103))
    g,_,_=generate([s],b);assert not g['break_follow__all']

def test_gap_cancels_confirmation():
    b,s=fixture();b.append(replace(b[-1],ts=b[-1].ts+timedelta(minutes=2),high=106,close=105))
    g,_,_=generate([s],b);assert not g['break_follow__all']

def test_mismatched_market_delta_fails_loud():
    b,s=fixture()
    with pytest.raises(ValueError,match='mismatch'):generate([replace(s,delta=71)],b)

def test_long_short_symmetry():
    b,s=fixture();b.append(replace(b[-1],ts=b[-1].ts+timedelta(minutes=1),high=106,close=105))
    mirror=[replace(x,open=200-x.open,high=200-x.low,low=200-x.high,close=200-x.close,buy_qty=x.sell_qty,sell_qty=x.buy_qty) for x in b]
    s=replace(s,side='SHORT',delta=-s.delta,event='DELTA_MIN')
    g,_,_=generate([s],mirror);assert g['break_follow__all'][0].side=='SHORT'

def test_future_seed_does_not_change_existing_emissions():
    b,s=fixture();g,_,_=generate([s],b)
    future=replace(s,seed_id='future',ts=s.ts+timedelta(days=1))
    later,_,_=generate([s,future],b);assert g==later

def test_missing_warmup_is_recorded_not_silently_dropped():
    b,s=fixture();g,a,_=generate([s],b[1:]);assert not any(g.values())
    assert a[0]['status']=='INCOMPLETE_VALID_60M_CONTEXT'

def test_flat_traded_bar_is_valid_history():
    b,s=fixture();b[30]=replace(b[30],high=100,low=100)
    g,a,_=generate([s],b);assert a[0]['status']=='USABLE'
    assert len(g['immediate_follow__all'])==1

def test_flat_seed_has_no_resistance_label_but_is_retained():
    b,s=fixture();b[-1]=replace(b[-1],high=100,low=100)
    g,_,_=generate([s],b);assert len(g['immediate_follow__all'])==1
    assert not g['immediate_follow__resistance']
