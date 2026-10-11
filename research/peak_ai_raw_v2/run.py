"""Auditable offline raw-extrema experiment. Stages never overwrite prior outputs."""
from __future__ import annotations
import argparse,copy,hashlib,json,pickle,subprocess,time
from collections import Counter
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pandas as pd
from research.peak_ai_raw_v2.signals import generate,load_seeds,load_legacy,FAMILIES,MODES
from research.peak_ai_raw_v2.metrics import summary,SPLITS
from deltascout.research_bundle.scout_backtester.contracts import ReplayConfig,TradeResult,BacktestContractError,LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,TARGET_FIRST_SAME_BAR_POLICY_ID
from deltascout.research_bundle.scout_backtester.feed_loader import load_feed
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate
from deltascout.research_bundle.scout_backtester.portfolio import replay_portfolio

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
BASE=ROOT/'deltascout/research_material'
OUT=HERE/'results'
CONFIG=ReplayConfig(experiment_id='peak_ai_raw_v2_20261009',
    signal_feature_feed_symbol='BTCUSDT_SPOT_LEGACY',fill_model_id=LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID)

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n')
def rows(p,v):
    v=list(v)
    if v:pd.DataFrame(v).to_csv(p,index=False)
    else:Path(p).write_text('')
def utc(s):return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
def end(s):return utc(s)+timedelta(days=1)-timedelta(microseconds=1)
def code_hashes():return {p.name:digest(p) for p in sorted(HERE.glob('*.py')) if p.name!='report.py'}
def in_split(c,period):
    first,last,_=SPLITS[period];seed=datetime.fromisoformat(c.shadow_flags['seed_ts'])
    return utc(first)<=seed<=c.signal_ts_utc<=end(last)

def prepare():
    OUT.mkdir(exist_ok=False);CONFIG.validate()
    legacy_root=BASE/'execution_feed/btcusdt_legacy_spot_1m/daily'
    signal=load_legacy(legacy_root)
    execution=load_feed(BASE/'execution_feed/btcusdc_spot_1m/daily',date_from='2026-03-19',date_to='2026-08-19',feed_role='official_spot_execution')
    if any(b.ts-a.ts!=timedelta(minutes=1) for a,b in zip(execution,execution[1:])):raise ValueError('Execution gap')
    seeds=load_seeds(BASE/'raw_archive');groups,audit,duplicates=generate(seeds,signal)
    rows(OUT/'seed_audit.csv',audit);rows(OUT/'duplicate_signals.csv',duplicates)
    rows(OUT/'candidates.csv',(dict(family=k,**c.to_dict()) for k,v in groups.items() for c in v))
    sources=list(legacy_root.glob('*.csv'))+list((BASE/'raw_archive').glob('*.jsonl'))+list((BASE/'execution_feed/btcusdc_spot_1m/daily').glob('*.csv'))
    rows(OUT/'input_hashes.csv',({'path':str(p.relative_to(ROOT)),'sha256':digest(p)} for p in sorted(sources)))
    manifest={'created_at_utc':datetime.now(timezone.utc).isoformat(),'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'config':CONFIG.to_dict(),'splits':SPLITS,'code_hashes':code_hashes(),'protocol_hash':digest(HERE/'PROTOCOL.md'),
        'raw_seeds':len(seeds),'seed_types':dict(Counter(s.event for s in seeds)),
        'seed_status':dict(Counter(r['status'] for r in audit)),
        'max_delta_error':max(r.get('delta_error',0) for r in audit),'max_volume_error':max(r.get('volume_error',0) for r in audit),
        'signal_rows':len(signal),'signal_gaps':sum(b.ts-a.ts!=timedelta(minutes=1) for a,b in zip(signal,signal[1:])),
        'execution_rows':len(execution),'candidate_counts':{k:len(v) for k,v in groups.items()},
        'split_counts':{p:{k:sum(in_split(c,p) for c in v) for k,v in groups.items()} for p in SPLITS},
        'history_reused_not_fresh_holdout':True}
    dump(OUT/'manifest.json',manifest)
    with (OUT/'prepared.pkl').open('wb') as f:pickle.dump((signal,execution,groups),f)
    print(json.dumps(manifest,indent=2),flush=True)

def replay(period,families,signal,execution,groups,config=CONFIG,label='base'):
    first,last,stop=SPLITS[period]
    signal=[b for b in signal if utc(first)-timedelta(days=2)<=b.ts<=end(stop)]
    execution=[b for b in execution if utc(first)-timedelta(days=2)<=b.ts<=end(stop)]
    st=[b.ts for b in signal];et=[b.ts for b in execution]
    dest=OUT/f'{period}_{label}';dest.mkdir(exist_ok=False)
    cache={};metrics={};errors=[];started=time.monotonic()
    for family in families:
        cs=[c for c in groups[family] if in_split(c,period)];results=[];family_errors=[]
        for i,c in enumerate(cs):
            key=(c.signal_ts_utc,c.side,c.signal_price)
            if key not in cache:
                try:r,_=replay_candidate(c,execution,config,reference_bars=signal,_timestamps=et,_reference_timestamps=st)
                except BacktestContractError as exc:
                    r=TradeResult(trade_id='ERROR_'+c.candidate_id,candidate_id=c.candidate_id,experiment_id=config.experiment_id,
                        replay_mode='independent_opportunity',candidate_group=c.candidate_group,side=c.side,
                        signal_ts_utc=c.signal_ts_utc,entry_status='INVALID',lifecycle_class='INTEGRITY_ERROR',blocked_reason=str(exc))
                cache[key]=r
            r=copy.deepcopy(cache[key]);r.candidate_id=c.candidate_id;r.candidate_group=c.candidate_group
            r.trade_id='RAWTR_'+hashlib.sha256((c.candidate_id+label).encode()).hexdigest()[:20]
            if r.lifecycle_class=='INTEGRITY_ERROR':
                error={'family':family,'candidate_id':c.candidate_id,'ts':c.signal_ts_utc.isoformat(),'error':r.blocked_reason}
                family_errors.append(error);errors.append(error)
            results.append(r)
            if (i+1)%200==0:print(period,label,family,i+1,'/',len(cs),'seconds',round(time.monotonic()-started),flush=True)
        portfolio,_,_=replay_portfolio(cs,results,config)
        rows(dest/f'{family}_independent.csv',(r.to_dict() for r in results))
        rows(dest/f'{family}_portfolio.csv',(r.to_dict() for r in portfolio))
        metrics[family]={'portfolio':summary(portfolio,cs,period),'independent':summary(results,cs,period),'integrity_errors':len(family_errors)}
        dump(dest/'metrics.json',metrics);dump(dest/'integrity_errors.json',errors)
        print(period,label,family,{k:v for k,v in metrics[family]['portfolio'].items() if k in ('candidates','closed','unresolved','net_usdc','profit_factor')},'errors',len(family_errors),flush=True)
    return metrics

def eligible(m,min_closed):
    p=m['portfolio']
    return m['integrity_errors']==0 and p['closed']>=min_closed and p['net_usdc']>0 and (p['profit_factor'] or 0)>=1.1

def shortlist():
    dest=OUT/'shortlist.json'
    if dest.exists():raise RuntimeError('Frozen shortlist exists')
    d=json.loads((OUT/'development_base/metrics.json').read_text());ranking=[];chosen=[]
    for mode in MODES:
        rr=[]
        for family in FAMILIES:
            if not family.startswith(mode+'__'):continue
            m=d[family];p=m['portfolio']
            rr.append({'family':family,'eligible':eligible(m,25),'pf':p['profit_factor'] or 0,
                       'net_dd':p['net_usdc']/max(p['max_closed_equity_drawdown_usdc'],1)})
        rr.sort(key=lambda r:(-int(r['eligible']),-r['pf'],-r['net_dd'],r['family']))
        chosen.append(rr[0]['family']);ranking.extend(rr)
    dump(dest,{'chosen':chosen,'ranking':ranking,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'development_hash':digest(OUT/'development_base/metrics.json'),'code_hashes':code_hashes(),'protocol_hash':digest(HERE/'PROTOCOL.md')})
    print(dest.read_text(),flush=True)

def select():
    dest=OUT/'selection.json'
    if dest.exists():raise RuntimeError('Frozen selection exists')
    d=json.loads((OUT/'development_base/metrics.json').read_text());v=json.loads((OUT/'validation_base/metrics.json').read_text());rank=[]
    for family,m in v.items():
        a=d[family]['portfolio'];b=m['portfolio']
        rank.append({'family':family,'eligible':eligible(d[family],25) and eligible(m,10),
            'min_pf':min(a['profit_factor'] or 0,b['profit_factor'] or 0),
            'validation_net_dd':b['net_usdc']/max(b['max_closed_equity_drawdown_usdc'],1)})
    rank.sort(key=lambda r:(-int(r['eligible']),-r['min_pf'],-r['validation_net_dd'],r['family']))
    dump(dest,{'selected':rank[0]['family'],'eligible':rank[0]['eligible'],'rankings':rank,
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'code_hashes':code_hashes(),
        'validation_hash':digest(OUT/'validation_base/metrics.json'),'historical_retest_is_not_fresh_holdout':True})
    print(dest.read_text(),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','development','shortlist','validation','select','historical_retest','sensitivity'])
    args=parser.parse_args()
    if args.stage=='prepare':prepare()
    elif args.stage=='shortlist':shortlist()
    elif args.stage=='select':select()
    else:
        manifest=json.loads((OUT/'manifest.json').read_text())
        assert manifest['code_hashes']==code_hashes() and manifest['protocol_hash']==digest(HERE/'PROTOCOL.md'),'Code/protocol changed after preparation'
        signal,execution,groups=pickle.loads((OUT/'prepared.pkl').read_bytes())
        if args.stage=='development':replay(args.stage,FAMILIES,signal,execution,groups)
        elif args.stage=='validation':replay(args.stage,json.loads((OUT/'shortlist.json').read_text())['chosen'],signal,execution,groups)
        else:
            chosen=[json.loads((OUT/'selection.json').read_text())['selected']]
            if args.stage=='historical_retest':replay(args.stage,chosen,signal,execution,groups)
            else:
                for label,cfg in [('double_slippage',replace(CONFIG,exit_slippage_bps=2,stop_slippage_bps=4)),
                                  ('target_first',replace(CONFIG,same_bar_policy_id=TARGET_FIRST_SAME_BAR_POLICY_ID))]:
                    replay('historical_retest',chosen,signal,execution,groups,cfg,label)
