from datetime import datetime,timedelta,timezone
from dataclasses import replace
from research.peak_ai_v1.signals import generate
from deltascout.research_bundle.scout_backtester.contracts import FeedBar

def bars():
    t=datetime(2026,3,20,tzinfo=timezone.utc)
    return [FeedBar(t+timedelta(minutes=i),100,101,99,100,100,55,45,False,'REAL_ENRICHED',False,'fixture',i) for i in range(181)]

def test_prefix_invariance_and_breakout_requires_current_close():
    b=bars();b[-1]=replace(b[-1],high=104,low=100,close=103.9,buy_qty=90,sell_qty=10)
    before=generate(b)
    assert len(before['continuation_30'])==1
    more=[replace(b[-1],ts=b[-1].ts+timedelta(minutes=i),close=100,high=110) for i in range(1,10)]
    after=generate(b+more)
    for f in before:
        assert before[f]==[c for c in after[f] if c.signal_ts_utc<=b[-1].ts]
    b[-1]=replace(b[-1],close=100)
    assert not generate(b)['continuation_15']

def test_synthetic_and_gap_cannot_seed():
    for mode in ('synthetic','gap'):
        b=bars();b[-1]=replace(b[-1],high=104,low=100,close=103.9,buy_qty=90,sell_qty=10)
        b[90]=replace(b[90],is_synthetic=True) if mode=='synthetic' else replace(b[90],ts=b[90].ts+timedelta(seconds=1))
        assert not any(generate(b).values())

def test_failed_extreme_has_opposite_side():
    b=bars();b[-1]=replace(b[-1],high=104,low=99,close=100,buy_qty=90,sell_qty=10)
    c=generate(b)['failed_extreme_30']
    assert len(c)==1 and c[0].side=='SHORT'

def test_pullback_waits_for_prior_retrace_not_same_bar():
    b=bars();seed=replace(b[-1],high=104,low=100,close=103.9,buy_qty=90,sell_qty=10);b[-1]=seed
    b.append(replace(seed,ts=seed.ts+timedelta(minutes=1),open=103.9,low=102.8,high=105,close=104.5,buy_qty=65,sell_qty=35))
    assert not generate(b)['pullback_30']
    b.append(replace(seed,ts=seed.ts+timedelta(minutes=2),open=104.5,low=104,high=106,close=105.5,buy_qty=65,sell_qty=35))
    c=generate(b)['pullback_30'];assert len(c)==1 and c[0].signal_ts_utc==b[-1].ts

def test_directional_symmetry():
    b=bars();b[-1]=replace(b[-1],high=104,low=100,close=103.9,buy_qty=90,sell_qty=10)
    mirrored=[replace(x,open=200-x.open,high=200-x.low,low=200-x.high,close=200-x.close,buy_qty=x.sell_qty,sell_qty=x.buy_qty) for x in b]
    assert generate(mirrored)['continuation_30'][0].side=='SHORT'

def test_pending_invalidation_prevents_later_confirmation():
    b=bars();seed=replace(b[-1],high=104,low=100,close=103.9,buy_qty=90,sell_qty=10);b[-1]=seed
    b.append(replace(seed,ts=seed.ts+timedelta(minutes=1),high=104,low=101,close=101.5,buy_qty=40,sell_qty=60))
    b.append(replace(seed,ts=seed.ts+timedelta(minutes=2),high=106,low=102,close=105,buy_qty=70,sell_qty=30))
    assert not generate(b)['pullback_30']
