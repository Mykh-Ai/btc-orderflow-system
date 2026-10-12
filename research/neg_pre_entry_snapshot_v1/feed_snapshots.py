"""Feed-only causal feature extraction. No Monitor, replay outcomes or fill inputs."""
import numpy as np
import pandas as pd

MISSING = ['liquidations', 'open_interest', 'funding', 'poc', 'session_vwap', 'post_sweep_evidence']

def prepare_feed(raw):
    f = raw.copy().sort_values('Timestamp').reset_index(drop=True)
    f['Timestamp'] = pd.to_datetime(f.Timestamp, utc=True)
    assert not f.Timestamp.duplicated().any()
    f['delta'] = f.BuyQty - f.SellQty
    f['valid'] = ((~f.IsSynthetic.astype(str).str.lower().isin(['1', 'true', 'yes'])) &
                  f.Volume.gt(0) & f.Close.gt(0))
    f['minute_average_price'] = f.VWAP  # normalized source maps legacy AvgPrice, not session VWAP
    f['signed_imbalance'] = (f.delta / f.Volume).where(f.valid)
    f['abs_imbalance'] = f.signed_imbalance.abs()
    f['bar_range_bps'] = (f.High-f.Low)/f.Close*10000
    f['bar_body_bps'] = (f.Close-f.Open)/f.Open*10000
    f['close_location'] = ((f.Close-f.Low)/(f.High-f.Low)).where(f.High.gt(f.Low))
    f['minute_average_distance_bps'] = (f.Close/f.minute_average_price-1)*10000
    # A gap at the first observation of the window is irrelevant; internal gaps are not.
    for window in [5, 15, 20, 60]:
        contiguous = (f.Timestamp-f.Timestamp.shift(window-1)).eq(pd.Timedelta(minutes=window-1))
        valid = contiguous & f.valid.rolling(window, min_periods=window).sum().eq(window)
        if window == 20:
            for col, name in [('delta', 'delta_zscore'), ('Volume', 'volume_zscore')]:
                mean = f[col].rolling(window).mean(); std = f[col].rolling(window).std(ddof=0)
                f[name] = ((f[col]-mean)/std).where(valid & std.gt(0))
        else:
            prefix = f'trailing_{window}m_'
            for col, name in [('Volume','volume'), ('delta','delta'), ('AggTrades','trades')]:
                f[prefix+name] = f[col].rolling(window).sum().where(valid)
            f[prefix+'imbalance'] = f[prefix+'delta']/f[prefix+'volume']
            f[prefix+'range_bps'] = ((f.High.rolling(window).max()-f.Low.rolling(window).min())/f.Close*10000).where(valid)
            return_valid = valid & f.valid.shift(window, fill_value=False) & (f.Timestamp-f.Timestamp.shift(window)).eq(pd.Timedelta(minutes=window))
            f[prefix+'return_bps'] = (f.Close/f.Close.shift(window)-1).mul(10000).where(return_valid)
    return f.set_index('Timestamp', drop=False)

def snapshot(candidate, tag, cutoff, feed):
    expected = candidate.shadow_flags['seed_ts'] if tag == 'S0' else candidate.signal_ts_utc
    t = pd.Timestamp(cutoff)
    assert tag in ('S0', 'S1') and t == pd.Timestamp(expected), 'incorrect snapshot cutoff'
    assert t in feed.index, 'missing exact cutoff minute'
    row = feed.loc[t]
    assert row.valid, 'invalid snapshot minute'
    columns = ['Open','High','Low','Close','Volume','BuyQty','SellQty','AggTrades','delta',
        'signed_imbalance','abs_imbalance','bar_range_bps','bar_body_bps','close_location',
        'minute_average_price','minute_average_distance_bps','delta_zscore','volume_zscore']
    columns += [c for c in feed if c.startswith('trailing_')]
    out = {'candidate_id':candidate.candidate_id, 'seed_id':candidate.shadow_flags['seed_id'],
           'seed_ts':candidate.shadow_flags['seed_ts'], 'snapshot':tag, 'cutoff':t.isoformat(),
           'evidence_max_ts':t.isoformat(), 'delta_event_type':candidate.shadow_flags['event'],
           'owning_delta':candidate.delta, 'owning_volume':candidate.volume,
           'owning_abs_imbalance':abs(candidate.delta)/candidate.volume}
    out.update({c:float(row[c]) if pd.notna(row[c]) else None for c in columns})
    out.update({c:None for c in MISSING})
    return out

def state_change(candidate, s0, s1, feed):
    t0,t1 = pd.Timestamp(s0['cutoff']),pd.Timestamp(s1['cutoff'])
    w = feed.loc[(feed.index>t0)&(feed.index<=t1)]
    elapsed = (t1-t0).total_seconds()/60
    assert len(w)==elapsed and w.valid.all() and elapsed>0, 'incomplete S0/S1 interval'
    p0,p1 = s0['Close'],s1['Close']
    out = {'candidate_id':candidate.candidate_id,'elapsed_minutes':elapsed,
        'price_change_bps':(p1/p0-1)*10000,
        'downward_progress_bps':(p0-p1)/p0*10000,
        'maximum_upward_excursion_bps':max(0,w.High.max()-p0)/p0*10000,
        'maximum_downward_excursion_bps':max(0,p0-w.Low.min())/p0*10000,
        'interval_volume':w.Volume.sum(),'interval_delta':w.delta.sum(),
        'interval_signed_imbalance':w.delta.sum()/w.Volume.sum(),
        'interval_trades':w.AggTrades.sum()}
    for minutes in [1,5,15]:
        end=t0+pd.Timedelta(minutes=minutes)
        part=w[w.Timestamp<=end]
        available=end<=t1 and len(part)==minutes
        out[f'downward_progress_{minutes}m_bps']=(p0-part.Close.iloc[-1])/p0*10000 if available else None
        out[f'flow_delta_{minutes}m']=part.delta.sum() if available else None
    keys=['delta','Volume','signed_imbalance','abs_imbalance','delta_zscore','volume_zscore',
          'bar_range_bps','bar_body_bps','AggTrades']+[c for c in s0 if c.startswith('trailing_')]
    for key in keys:
        a,b=s0[key],s1[key]
        out[key+'_change']=b-a if a is not None and b is not None else None
    return out

def join_outcomes(features, outcomes):
    assert len(features)==len(outcomes) and features.candidate_id.is_unique and outcomes.candidate_id.is_unique
    assert set(features.candidate_id)==set(outcomes.candidate_id)
    return features.merge(outcomes,on='candidate_id',validate='one_to_one')
