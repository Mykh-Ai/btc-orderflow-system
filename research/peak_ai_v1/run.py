"""Reproducible research driver; production modules and replay engine are unmodified."""
from __future__ import annotations
import argparse,copy,hashlib,json,pickle,platform,subprocess,time
from collections import Counter
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from research.peak_ai_v1.signals import generate,FAMILIES
from deltascout.research_bundle.scout_backtester.contracts import ReplayConfig,TradeResult,BacktestContractError,LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,TARGET_FIRST_SAME_BAR_POLICY_ID
from deltascout.research_bundle.scout_backtester.feed_loader import load_feed,quality_counts
from deltascout.research_bundle.scout_backtester.candidate_compiler import compile_candidates
from deltascout.research_bundle.scout_backtester.shadow_features import enrich_shadow_flags
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate
from deltascout.research_bundle.scout_backtester.portfolio import replay_portfolio

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'deltascout/research_material'
OUT=ROOT/'research/peak_ai_v1/results'
SPLITS={'development':('2026-03-20','2026-05-29','2026-05-31'),
        'validation':('2026-06-01','2026-06-28','2026-06-30'),
        'holdout':('2026-07-01','2026-08-17','2026-08-19')}
RESOLVED={'PLAIN_SL','TP1_SL','TP1_TP2_TRAILING_STOP'}
CONFIG=ReplayConfig(experiment_id='peak_ai_v1_20261009',fill_model_id=LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n')
def utc(s):return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
def end(s):return utc(s)+timedelta(days=1)-timedelta(microseconds=1)
def save_rows(path,rows):
    rows=list(rows)
    if rows:pd.DataFrame(rows).to_csv(path,index=False)
    else:Path(path).write_text('')

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    CONFIG.validate()
    signal=load_feed(BASE/'effective_feed',date_from='2026-03-18',date_to='2026-08-19',quality_sidecar_root=BASE/'recovery_reports')
    execution=load_feed(BASE/'execution_feed/btcusdc_spot_1m/daily',date_from='2026-03-19',date_to='2026-08-19',feed_role='official_spot_execution')
    gaps=[(a.ts.isoformat(),b.ts.isoformat()) for a,b in zip(execution,execution[1:]) if b.ts-a.ts!=timedelta(minutes=1)]
    if gaps:raise RuntimeError(f'Execution feed discontinuity: {gaps[:10]}')
    print('Feed loaded',len(signal),len(execution),flush=True)
    generated=generate(signal)
    baseline,quality=compile_candidates(BASE/'reviews',date_from='2026-03-19',date_to='2026-08-18',raw_archive_root=BASE/'raw_archive',candidate_groups=['PEAK_EMIT_BASELINE'])
    baseline=[c for c in baseline if c.admission_status=='ADMITTED' and c.event_type=='PEAK_EMIT']
    enriched=enrich_shadow_flags(baseline,signal,raw_archive_root=BASE/'raw_archive',date_from='2026-03-19',date_to='2026-08-18')
    groups={**generated,'PEAK_ARCHIVED':baseline,'PEAK_ARCHIVED_AB':[c for c in enriched if c.shadow_flags.get('loss_avoidance_conservative_union') is not True]}
    with (OUT/'prepared.pkl').open('wb') as f:pickle.dump((signal,execution,groups),f)
    save_rows(OUT/'candidates.csv',(dict(family=k,**c.to_dict()) for k,v in groups.items() for c in v))
    save_rows(OUT/'baseline_quality.csv',(vars(q) for q in quality))
    files=[]
    for sub,glob in [('effective_feed','*.csv'),('execution_feed/btcusdc_spot_1m/daily','*.csv'),('raw_archive','*.jsonl'),('reviews','**/*.csv'),('recovery_reports','recovery_quality_*.csv')]:
        for p in sorted((BASE/sub).glob(glob)):files.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p)})
    save_rows(OUT/'input_hashes.csv',files)
    dump(OUT/'manifest.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'config':CONFIG.to_dict(),'splits':SPLITS,'candidate_counts':{k:len(v) for k,v in groups.items()},
        'signal_quality':quality_counts(signal),'signal_gaps':sum(b.ts-a.ts!=timedelta(minutes=1) for a,b in zip(signal,signal[1:])),
        'execution_rows':len(execution),'signal_rows':len(signal),'execution_gaps':gaps,'python':platform.python_version(),
        'hashes':{p.name:digest(p) for p in (ROOT/'research/peak_ai_v1').glob('*.py')},
        'baseline_ab_unknown':sum(c.shadow_flags.get('loss_avoidance_conservative_union') is None for c in enriched)})
    print('Prepared', {k:len(v) for k,v in groups.items()},flush=True)

def summary(results,candidates,period):
    filled=[r for r in results if r.entry_status=='FILLED']
    closed=sorted([r for r in filled if r.lifecycle_class in RESOLVED],key=lambda r:r.exit_ts)
    pnls=np.array([r.net_pnl_usdc for r in closed],dtype=float)
    pos=float(pnls[pnls>0].sum());neg=float(-pnls[pnls<0].sum())
    equity=np.r_[0,np.cumsum(pnls)]
    start,_,stop=SPLITS[period]
    days=pd.date_range(start,stop,tz='UTC')
    daily=pd.Series(0.,index=days)
    for r in closed:daily.loc[pd.Timestamp(r.exit_ts).floor('D')]+=r.net_pnl_usdc
    n=len(daily);rng=np.random.default_rng(20261009)
    # Circular moving 7-day block bootstrap preserves local serial dependence.
    idx=(rng.integers(0,n,size=(2000,(n+6)//7,1))+np.arange(7))%n
    boot=daily.to_numpy()[idx.reshape(2000,-1)[:,:n]].sum(axis=1)
    byside={}
    for side in ('LONG','SHORT'):
        rs=[r for r in closed if r.side==side]
        byside[side]={'n':len(rs),'net':sum(r.net_pnl_usdc for r in rs)}
    return {'candidates':len(candidates),'filled':len(filled),'closed':len(closed),'unresolved':len(filled)-len(closed),
        'net_usdc':float(pnls.sum()),'gross_usdc':sum(r.gross_pnl_usdc for r in closed),
        'commission_usdc':sum(r.commission_usdc for r in closed),'slippage_usdc':sum(r.slippage_usdc for r in closed),
        'profit_factor':pos/neg if neg>0 else None,'mean_net_usdc':float(pnls.mean()) if len(pnls) else None,
        'net_wins':int((pnls>0).sum()),'tp1_hits':sum(r.tp1_fill_ts is not None for r in closed),
        'tp2_hits':sum(r.tp2_fill_ts is not None for r in closed),
        'max_closed_equity_drawdown_usdc':float((np.maximum.accumulate(equity)-equity).max()),
        'weekly_block_bootstrap_net_95pct':np.quantile(boot,[.025,.975]).tolist(),
        'lifecycle_counts':dict(Counter(r.lifecycle_class for r in results)),
        'status_counts':dict(Counter(r.entry_status for r in results)),
        'blocked_reasons':dict(Counter(r.blocked_reason for r in results if r.blocked_reason)),
        'same_bar_ambiguous_closed':sum(r.same_bar_ambiguous for r in closed),
        'unresolved_realized_partial_net':sum(r.net_pnl_usdc or 0 for r in filled if r.lifecycle_class not in RESOLVED),
        'by_side':byside,'daily_net':{d.date().isoformat():v for d,v in daily.items()}}

def run_period(period,families,signal,execution,groups,config,label='base'):
    start,last,stop=SPLITS[period]
    signal=[b for b in signal if utc(start)-timedelta(days=2)<=b.ts<=end(stop)]
    execution=[b for b in execution if utc(start)-timedelta(days=2)<=b.ts<=end(stop)]
    st=[b.ts for b in signal];et=[b.ts for b in execution]
    cache={};metrics={};exceptions=[];began=time.monotonic()
    runroot=OUT/f'{period}_{label}';runroot.mkdir(exist_ok=False)
    for family in families:
        cs=sorted([c for c in groups[family] if utc(start)<=c.signal_ts_utc<=end(last)],key=lambda c:(c.signal_ts_utc,c.candidate_id))
        results=[]
        for i,c in enumerate(cs):
            key=(c.signal_ts_utc,c.side,c.signal_price)
            if key not in cache:
                try:r,_=replay_candidate(c,execution,config,reference_bars=signal,_timestamps=et,_reference_timestamps=st)
                except BacktestContractError as exc:
                    exceptions.append({'candidate_id':c.candidate_id,'family':family,'time':c.signal_ts_utc.isoformat(),'error':str(exc)})
                    r=TradeResult(trade_id='ERROR_'+c.candidate_id,candidate_id=c.candidate_id,experiment_id=config.experiment_id,
                        replay_mode='independent_opportunity',candidate_group=c.candidate_group,side=c.side,
                        signal_ts_utc=c.signal_ts_utc,entry_status='INVALID',lifecycle_class='INTEGRITY_ERROR',blocked_reason=str(exc))
                cache[key]=r
            r=copy.deepcopy(cache[key]);r.candidate_id=c.candidate_id;r.candidate_group=c.candidate_group
            r.trade_id='PAI_TR_'+hashlib.sha256((c.candidate_id+label).encode()).hexdigest()[:20]
            results.append(r)
            if (i+1)%100==0:print(period,label,family,i+1,'/',len(cs),'elapsed',round(time.monotonic()-began),flush=True)
        portfolio,_,opportunities=replay_portfolio(cs,results,config)
        save_rows(runroot/f'{family}_independent.csv',(r.to_dict() for r in results))
        save_rows(runroot/f'{family}_portfolio.csv',(r.to_dict() for r in portfolio))
        metrics[family]={'portfolio':summary(portfolio,cs,period),'independent':summary(results,cs,period)}
        dump(runroot/'metrics.json',metrics);dump(runroot/'integrity_errors.json',exceptions)
        print(period,label,family,json.dumps({k:v for k,v in metrics[family]['portfolio'].items() if k in ('candidates','closed','unresolved','net_usdc','profit_factor')}),flush=True)
    return metrics

def select():
    dev=json.loads((OUT/'development_base/metrics.json').read_text());val=json.loads((OUT/'validation_base/metrics.json').read_text())
    rankings=[]
    for family in FAMILIES:
        a=dev[family]['portfolio'];b=val[family]['portfolio']
        eligible=(a['closed']>=20 and b['closed']>=10 and min(a['net_usdc'],b['net_usdc'])>0 and min(a['profit_factor'] or 0,b['profit_factor'] or 0)>=1.05)
        rankings.append({'family':family,'eligible':eligible,'min_pf':min(a['profit_factor'] or 0,b['profit_factor'] or 0),
                         'validation_net_dd':b['net_usdc']/max(b['max_closed_equity_drawdown_usdc'],1)})
    rankings.sort(key=lambda x:(-int(x['eligible']),-x['min_pf'],-x['validation_net_dd'],x['family']))
    p=OUT/'frozen_selection.json'
    if p.exists():raise RuntimeError('Frozen selection already exists: never overwrite')
    dump(p,{'selected':rankings[0]['family'],'eligible':rankings[0]['eligible'],'rankings':rankings,
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'test_outcomes_seen':False,
        'development_hash':digest(OUT/'development_base/metrics.json'),'validation_hash':digest(OUT/'validation_base/metrics.json'),
        'signal_code_hash':digest(ROOT/'research/peak_ai_v1/signals.py'),'protocol_hash':digest(ROOT/'research/peak_ai_v1/AUDIT_AND_PROTOCOL.md')})
    print(p.read_text(),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','development','validation','select','holdout','sensitivity'])
    args=parser.parse_args()
    if args.stage=='prepare':prepare()
    elif args.stage=='select':select()
    else:
        signal,execution,groups=pickle.loads((OUT/'prepared.pkl').read_bytes())
        families=list(FAMILIES)+['PEAK_ARCHIVED','PEAK_ARCHIVED_AB']
        if args.stage in ('holdout','sensitivity'):
            choice=json.loads((OUT/'frozen_selection.json').read_text())
            assert choice['signal_code_hash']==digest(ROOT/'research/peak_ai_v1/signals.py')
            families=[choice['selected'],'PEAK_ARCHIVED','PEAK_ARCHIVED_AB']
        if args.stage=='sensitivity':
            for label,cfg in [('target_first',replace(CONFIG,same_bar_policy_id=TARGET_FIRST_SAME_BAR_POLICY_ID)),
                              ('double_slippage',replace(CONFIG,exit_slippage_bps=2,stop_slippage_bps=4))]:
                run_period('holdout',families,signal,execution,groups,cfg,label)
        else:run_period(args.stage,families,signal,execution,groups,CONFIG)
