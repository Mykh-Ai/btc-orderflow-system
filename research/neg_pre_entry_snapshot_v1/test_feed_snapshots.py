from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from .feed_snapshots import prepare_feed, snapshot, state_change, join_outcomes, MISSING
from .parity import HERE, COHORT, candidates

@pytest.fixture
def raw():
    n=100;x=np.arange(n,dtype=float)
    return pd.DataFrame(dict(Timestamp=pd.date_range('2026-04-01',periods=n,freq='min',tz='UTC'),
        Open=100+x*.1,High=102+x*.1,Low=98+x*.1,Close=100+x*.1,
        Volume=20+x,BuyQty=5+x*.2,SellQty=15+x*.8,AggTrades=40+x,VWAP=100+x*.1,
        IsSynthetic=0,OpenInterest=np.nan,FundingRate=np.nan,LiqBuyQty=np.nan,LiqSellQty=np.nan))

@pytest.fixture
def candidate(raw):
    return SimpleNamespace(candidate_id='TEST',delta=-11.,volume=24.,signal_ts_utc=raw.Timestamp[85],
        shadow_flags=dict(seed_ts=raw.Timestamp[70].isoformat(),seed_id='SEED',event='DELTA_MIN'))

def test_s0_exact_owning_time(raw,candidate):
    t=candidate.shadow_flags['seed_ts'];s=snapshot(candidate,'S0',t,prepare_feed(raw))
    assert s['cutoff']==t
    with pytest.raises(AssertionError):snapshot(candidate,'S0',raw.Timestamp[71],prepare_feed(raw))

def test_s1_exact_signal_time(raw,candidate):
    s=snapshot(candidate,'S1',candidate.signal_ts_utc,prepare_feed(raw))
    assert s['cutoff']==candidate.signal_ts_utc.isoformat()
    with pytest.raises(AssertionError):snapshot(candidate,'S1',raw.Timestamp[86],prepare_feed(raw))

@pytest.mark.parametrize('tag,index',[('S0',70),('S1',85)])
def test_snapshot_prefix_equivalence_and_future_mutation(raw,candidate,tag,index):
    cutoff=raw.Timestamp[index]
    expected=snapshot(candidate,tag,cutoff,prepare_feed(raw.iloc[:index+1]))
    altered=raw.copy();altered.loc[index+1:,['High','Low','Close','Volume','BuyQty','SellQty','AggTrades','VWAP']]=999999.
    assert snapshot(candidate,tag,cutoff,prepare_feed(altered))==expected
    assert pd.Timestamp(expected['evidence_max_ts'])<=cutoff

def test_entry_fill_minute_cannot_contaminate_s1(raw,candidate):
    a=snapshot(candidate,'S1',candidate.signal_ts_utc,prepare_feed(raw))
    # First simulated fill minute is the minute after decision. It is deliberately extreme.
    raw.loc[86,['Close','High','Low','Volume','BuyQty','SellQty']]=1e12
    assert snapshot(candidate,'S1',candidate.signal_ts_utc,prepare_feed(raw))==a

def test_owning_raw_delta_separate_from_current_feed(raw,candidate):
    s=snapshot(candidate,'S0',candidate.shadow_flags['seed_ts'],prepare_feed(raw))
    assert s['owning_delta']==-11 and s['delta']==raw.BuyQty[70]-raw.SellQty[70]
    assert s['owning_delta']!=s['delta']

def test_missing_fields_not_zero(raw,candidate):
    s=snapshot(candidate,'S0',candidate.shadow_flags['seed_ts'],prepare_feed(raw))
    assert all(s[k] is None for k in MISSING)

def test_zscore_warmup_and_zero_variance_missing(raw):
    raw.Volume=20.;f=prepare_feed(raw)
    assert f.volume_zscore.isna().all()
    assert f.delta_zscore.iloc[:19].isna().all()

def test_zscore_matches_population_definition(raw):
    f=prepare_feed(raw);x=(raw.BuyQty-raw.SellQty).iloc[51:71]
    assert f.delta_zscore.iloc[70]==pytest.approx((x.iloc[-1]-x.mean())/x.std(ddof=0))

def test_gap_invalidates_window_not_zero_filled(raw):
    f=prepare_feed(raw.drop(index=65))
    assert pd.isna(f.loc[raw.Timestamp[70],'delta_zscore'])
    assert pd.isna(f.loc[raw.Timestamp[70],'trailing_15m_delta'])

def test_state_change_uses_only_open_interval_to_decision(raw,candidate):
    f=prepare_feed(raw);a=snapshot(candidate,'S0',candidate.shadow_flags['seed_ts'],f);b=snapshot(candidate,'S1',candidate.signal_ts_utc,f)
    s=state_change(candidate,a,b,f)
    assert s['elapsed_minutes']==15
    assert s['interval_delta']==pytest.approx((raw.BuyQty-raw.SellQty).iloc[71:86].sum())
    assert s['downward_progress_15m_bps']==pytest.approx((raw.Close[70]-raw.Close[85])/raw.Close[70]*10000)
    raw.loc[86:,'High']=1e12
    assert state_change(candidate,a,b,prepare_feed(raw))==s

def test_immediate_progress_unavailable_after_signal(raw,candidate):
    candidate.signal_ts_utc=raw.Timestamp[72];f=prepare_feed(raw)
    a=snapshot(candidate,'S0',candidate.shadow_flags['seed_ts'],f);b=snapshot(candidate,'S1',candidate.signal_ts_utc,f)
    s=state_change(candidate,a,b,f)
    assert s['downward_progress_1m_bps'] is not None
    assert s['downward_progress_5m_bps'] is None and s['downward_progress_15m_bps'] is None

def test_gap_in_s0_s1_interval_rejected(raw,candidate):
    f=prepare_feed(raw.drop(index=80));a=snapshot(candidate,'S0',candidate.shadow_flags['seed_ts'],f);b=snapshot(candidate,'S1',candidate.signal_ts_utc,f)
    with pytest.raises(AssertionError):state_change(candidate,a,b,f)

def test_join_rejects_duplicate_or_missing_outcomes():
    f=pd.DataFrame({'candidate_id':['a','b']})
    for ids in [['a','a'],['a','c'],['a']]:
        with pytest.raises(AssertionError):join_outcomes(f,pd.DataFrame({'candidate_id':ids}))

def test_all_262_receive_one_exact_pair():
    expected={c.candidate_id:c for c in candidates()}
    for tag in ['s0','s1']:
        f=pd.read_csv(HERE/f'data/snapshot_{tag}.csv')
        assert len(f)==262 and f.candidate_id.is_unique and set(f.candidate_id)==set(expected)
        for r in f.itertuples():
            c=expected[r.candidate_id];t=c.shadow_flags['seed_ts'] if tag=='s0' else c.signal_ts_utc
            assert pd.Timestamp(r.cutoff)==pd.Timestamp(t)==pd.Timestamp(r.evidence_max_ts)

def test_exact_financial_join_and_aggregate_parity():
    new=pd.read_csv(HERE/'data/forensic_dataset.csv').set_index('candidate_id').sort_index()
    prior=pd.read_csv(COHORT/'independent_trades.csv').set_index('candidate_id').sort_index()
    assert list(new.index)==list(prior.index) and new.index.is_unique
    for col in ['gross_pnl_usdc','net_pnl_usdc','commission_usdc','slippage_usdc','position_r',
                'planned_entry_price_usdt','initial_stop_price_usdt','tp1_price_usdt','tp2_price_usdt']:
        np.testing.assert_allclose(new[col],prior[col],rtol=0,atol=1e-9)
    gate=json.loads((HERE/'parity/result.json').read_text());assert gate['passed']
    assert new.net_pnl_usdc.sum()==pytest.approx(gate['metrics']['net_usdc'],abs=1e-9)
    assert new.gross_pnl_usdc.sum()==pytest.approx(gate['metrics']['gross_usdc'],abs=1e-9)
    assert new.portfolio_blocked.sum()==112 and (new.net_pnl_usdc>0).sum()==105

def test_zone_work_excluded_and_all_missing_columns_empty():
    cfg=json.loads((HERE/'config.json').read_text())
    assert all(not any(x in c for x in ['zone','fill','pnl','position_r','stop','tp1','tp2']) for c in cfg['feature_names'])
    for tag in ['s0','s1']:
        f=pd.read_csv(HERE/f'data/snapshot_{tag}.csv');assert f[MISSING].isna().all().all()
        assert not any('zone' in c for c in f)
