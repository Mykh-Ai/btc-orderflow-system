"""Reproduce feed-only S0/S1 dataset after the existing replay parity gate."""
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd
from .parity import HERE, PRIOR, COHORT, old, candidates
from .feed_snapshots import prepare_feed, snapshot, state_change, join_outcomes, MISSING

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path, value): Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def run():
    gate=json.loads((HERE/'parity/result.json').read_text())
    assert gate['passed'] and gate['candidates']==262
    assert digest(COHORT/'independent_trades.csv')==gate['source_sha256']
    old.verify_inputs(HERE.parent/'peak_ai_delta_h1_all_signs/results_v2')
    paths=sorted((old.BASE/'execution_feed/btcusdt_legacy_spot_1m/daily').glob('*.csv'))
    raw=pd.concat([pd.read_csv(p) for p in paths],ignore_index=True)
    raw.Timestamp=pd.to_datetime(raw.Timestamp,utc=True)
    raw=raw[raw.Timestamp<=pd.Timestamp('2026-08-19T23:59:00Z')].copy()
    feed=prepare_feed(raw)
    cs=candidates();assert len(cs)==262
    s0=[];s1=[];changes=[]
    for c in cs:
        a=snapshot(c,'S0',c.shadow_flags['seed_ts'],feed)
        b=snapshot(c,'S1',c.signal_ts_utc,feed)
        s0.append(a);s1.append(b);changes.append(state_change(c,a,b,feed))
    frames={'snapshot_s0':pd.DataFrame(s0),'snapshot_s1':pd.DataFrame(s1),'state_delta':pd.DataFrame(changes)}
    f=frames['state_delta'].copy()
    # No prices, timestamps, IDs, missing fields or outcomes are ranked as explanatory features.
    snapshot_features=['owning_delta','owning_volume','owning_abs_imbalance','Volume','BuyQty','SellQty',
        'AggTrades','delta','signed_imbalance','abs_imbalance','bar_range_bps','bar_body_bps','close_location',
        'minute_average_distance_bps','delta_zscore','volume_zscore']+[c for c in frames['snapshot_s0'] if c.startswith('trailing_')]
    for tag in ['s0','s1']:
        frame=frames['snapshot_'+tag]
        # Owning delta is identity and does not change at S1; avoid another duplicate feature.
        cols=[c for c in snapshot_features if tag=='s0' or not c.startswith('owning_')]
        prefixed=frame[['candidate_id']+cols].rename(columns={c:tag+'_'+c for c in cols})
        f=f.merge(prefixed,on='candidate_id',validate='one_to_one')
    feature_names=[c for c in f if c!='candidate_id']
    ledger=pd.read_csv(COHORT/'independent_trades.csv')
    outcomes=ledger[['candidate_id','seed_id','seed_ts','signal_ts_utc','entry_fill_ts','exit_ts',
        'gross_pnl_usdc','commission_usdc','slippage_usdc','net_pnl_usdc','position_r','lifecycle_class',
        'tp1_fill_ts','tp2_fill_ts','month','planned_entry_price_usdt','initial_stop_price_usdt',
        'tp1_price_usdt','tp2_price_usdt']].copy()
    outcomes['gross_label']=np.where(outcomes.gross_pnl_usdc>0,'GROSS_WIN',np.where(outcomes.gross_pnl_usdc<0,'GROSS_LOSS','GROSS_ZERO'))
    outcomes['net_label']=np.where(outcomes.net_pnl_usdc>0,'NET_WIN',np.where(outcomes.net_pnl_usdc<0,'NET_LOSS','NET_ZERO'))
    outcomes['tp1_reached']=outcomes.tp1_fill_ts.notna();outcomes['tp2_reached']=outcomes.tp2_fill_ts.notna()
    blocked=pd.read_csv(COHORT/'blocked_opportunities.csv')
    outcomes['portfolio_blocked']=outcomes.candidate_id.isin(blocked.candidate_id)
    dataset=join_outcomes(f,outcomes)
    assert len(dataset)==262 and dataset.portfolio_blocked.sum()==112
    for col,key in [('gross_pnl_usdc','gross_usdc'),('commission_usdc','commission_usdc'),
                    ('slippage_usdc','slippage_usdc'),('net_pnl_usdc','net_usdc')]:
        assert abs(dataset[col].sum()-gate['metrics'][key])<1e-9
    frames['forensic_dataset']=dataset
    out=HERE/'data';out.mkdir(exist_ok=True)
    for name,frame in frames.items():
        assert len(frame)==262 and frame.candidate_id.is_unique
        frame.to_csv(out/(name+'.csv'),index=False,float_format='%.15g')
    dump(HERE/'config.json',dict(scope='FEED_ONLY_USER_CORRECTION_2026_10_12',base_sha='d6f82fccd0ffea27831e878382eaf8f2662a39bb',
         cohort='NEG_H1_CONTROL',snapshot_clock='minute_availability',s0='owning seed_ts',s1='signal_ts_utc',
         windows=[5,15,60],zscore_window=20,zscore_ddof=0,immediate_windows=[1,5,15],feature_names=feature_names))
    availability={col:{'rows':len(raw),'nonmissing':int(raw[col].notna().sum())} for col in
        ['OpenInterest','FundingRate','LiqBuyQty','LiqSellQty','VWAP','AggTrades']}
    dump(HERE/'data_availability.json',dict(feed_fields=availability,snapshot_missing_fields=MISSING,
        vwap_column_provenance='legacy AvgPrice -> normalized VWAP -> minute_average_price',
        journal_poc_vwap='excluded by user feed-only scope',zones='not reconstructed; user stopped this work',
        post_sweep='not reconstructed; would require Monitor zone/event analysis'))
    dump(HERE/'input_hashes.json',dict(files=[dict(path=str(p.relative_to(old.ROOT)),sha256=digest(p)) if hasattr(old,'ROOT') and p.is_relative_to(old.ROOT) else dict(path=str(p),sha256=digest(p)) for p in paths],
        independent_ledger_sha256=digest(COHORT/'independent_trades.csv'),candidates_sha256=digest(COHORT/'candidates.json'),
        protocol_sha256=digest(HERE/'PROTOCOL.md')))
    dump(HERE/'data/validation.json',dict(passed=True,primary=262,complete_pairs=262,portfolio_blocked_included=112,
        s0_unique=262,s1_unique=262,one_to_one_join=True,cutoff='signal not fill',gross=float(dataset.gross_pnl_usdc.sum()),
        net=float(dataset.net_pnl_usdc.sum()),snapshot_feed_rows=len(feed),zone_reconstruction=False))
    print('DATASET COMPLETE',len(dataset),'pairs; features',len(feature_names),flush=True)

if __name__=='__main__':run()
