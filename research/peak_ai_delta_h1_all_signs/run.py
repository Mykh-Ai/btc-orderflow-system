"""Offline preparation and native Scout Replay. Each output directory is immutable."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import pickle
from pathlib import Path
import subprocess
import time

import numpy as np
import pandas as pd

from research.peak_ai_delta_h1_all_signs.query_cache import CachedStructureMonitor as ClosedStructureMonitor
import market_monitor.closed_structure_adapter as adapter_module
from research.peak_ai_delta_h1.inputs import load_legacy, load_seeds
from research.peak_ai_delta_h1_all_signs.engine import DeltaH1Engine
from deltascout.research_bundle.scout_backtester.contracts import (
    Candidate, ReplayConfig, BacktestContractError, TradeResult,
    LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
)
from deltascout.research_bundle.scout_backtester.feed_loader import load_feed
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate
from deltascout.research_bundle.scout_backtester.portfolio import replay_portfolio

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT/'deltascout/research_material'
MONITOR = Path(adapter_module.__file__).resolve().parents[1]
CONFIG = ReplayConfig(experiment_id='peak_ai_delta_h1_all_signs_v2_20261011',
    description='Any raw DELTA_MIN/MAX of either sign -> frozen H1/H4 zone -> SHORT H1 reclaim within four hours',
    signal_feature_feed_symbol='BTCUSDT_SPOT_LEGACY', initial_stop_policy='candidate_sweep',
    fill_model_id=LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID)
RESOLVED = {'PLAIN_SL','TP1_SL','TP1_TP2_TRAILING_STOP'}

def utc(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(path,value): Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str,allow_nan=False)+'\n')
def rows(path,items):
    items=list(items)
    if items: pd.DataFrame(items).to_csv(path,index=False)
    else: Path(path).write_text('')
def head(path): return subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()

def code_hashes():
    paths = list(HERE.glob('*.py')) + [HERE/'PROTOCOL.md', HERE.parent/'peak_ai_delta_h1/inputs.py']
    paths += list((ROOT/'deltascout/research_bundle/scout_backtester').glob('*.py'))
    paths += list((MONITOR/'market_monitor').glob('*.py'))
    return {(('monitor/' if p.is_relative_to(MONITOR) else 'replay/')+
             str(p.relative_to(MONITOR if p.is_relative_to(MONITOR) else ROOT))):digest(p) for p in sorted(paths)}

def verify_inputs(out):
    recorded=pd.read_csv(out/'input_hashes.csv')
    for row in recorded.to_dict('records'):
        if digest(ROOT/row['path'])!=row['sha256']:
            raise RuntimeError('Input changed: '+row['path'])

def checkpoint(out,engine,last_ts,seen,manifest):
    """Only our own locally written pickle is accepted; inputs/monitor rebuild on resume."""
    payload={'engine_state':{k:v for k,v in engine.__dict__.items() if k!='monitor'},
             'last_ts':last_ts,'seen':seen,'code_hashes':manifest['code_hashes']}
    temp=out/'checkpoint.tmp'
    temp.write_bytes(pickle.dumps(payload,protocol=pickle.HIGHEST_PROTOCOL))
    temp.replace(out/'checkpoint.pkl')
    dump(out/'progress.json',{'last_ts':last_ts,'raw_seeds_processed':len(seen),
        'confirmations':len(engine.candidates),'pending':len(engine.pending),
        'completed':False,'updated_at_utc':datetime.now(timezone.utc).isoformat()})

def prepare(out,resume=False):
    if not resume:out.mkdir(parents=True,exist_ok=False)
    CONFIG.validate()
    manifest={'created_at_utc':datetime.now(timezone.utc).isoformat(),
              'monitor_base':head(MONITOR),'replay_base':head(ROOT),
              'config':CONFIG.to_dict(),'code_hashes':code_hashes(),
              'decision_start':'2026-03-20T00:00:00+00:00',
              'decision_end':'2026-08-17T23:59:00+00:00',
              'outcome_end':'2026-08-19T23:59:00+00:00',
              'history_reused_not_fresh_holdout':True,
              'liquidations':'UNAVAILABLE_NOT_A_FILTER',
              'adapter_scope':'IMMUTABLE_INDIVIDUAL_H1_H4_UPPER_REFERENCES_NATIVE_SCORE_LIFECYCLE',
              'not_full_v39a_snapshot':True,'without_delta_control_run':False,
              'trigger_events':['DELTA_MAX','DELTA_MIN'],'trigger_sign_filter':None,
              'trade_side':'SHORT','shared_pending_and_portfolio':True}
    if resume:
        manifest=json.loads((out/'protocol_freeze.json').read_text())
        if manifest['code_hashes']!=code_hashes():raise RuntimeError('Cannot resume changed code')
        verify_inputs(out)
    else:dump(out/'protocol_freeze.json',manifest)
    legacy_root=BASE/'execution_feed/btcusdt_legacy_spot_1m/daily'
    if not resume:
        sources=list(legacy_root.glob('*.csv'))+list((BASE/'raw_archive').glob('*.jsonl'))
        sources+=list((BASE/'execution_feed/btcusdc_spot_1m/daily').glob('*.csv'))
        rows(out/'input_hashes.csv',({'path':str(p.relative_to(ROOT)),'sha256':digest(p)} for p in sorted(sources)))
    bars=load_legacy(legacy_root)
    bars=[b for b in bars if b.ts<=utc(manifest['outcome_end'])]
    seeds=load_seeds(BASE/'raw_archive')
    print('Loaded',len(bars),'minute bars,',len(seeds),'raw seeds',flush=True)
    monitor=ClosedStructureMonitor(bars)
    rows(out/'structural_inventory.csv',monitor.inventory())
    print('Causal H1/H4 references:',len(monitor.references),flush=True)
    engine=DeltaH1Engine(monitor)
    seed_map=defaultdict(list)
    for seed in seeds:seed_map[seed.ts].append(seed)
    seen=set();last_print=time.monotonic();started=last_print;last_ts=None
    if resume:
        saved=pickle.loads((out/'checkpoint.pkl').read_bytes())
        if saved['code_hashes']!=manifest['code_hashes']:raise RuntimeError('Checkpoint code mismatch')
        engine.__dict__.update(saved['engine_state'])
        seen=saved['seen'];last_ts=saved['last_ts']
        print('Resuming after',last_ts,'processed seeds',len(seen),flush=True)
    for bar in bars:
        if last_ts is not None and bar.ts<=last_ts:continue
        batch=seed_map.get(bar.ts,())
        engine.step(bar,batch)
        seen.update(s.seed_id for s in batch)
        if time.monotonic()-last_print>20:
            print('Progress',bar.ts.isoformat(),'seeds',len(seen),'confirmations',len(engine.candidates),
                  'seconds',round(time.monotonic()-started),flush=True)
            checkpoint(out,engine,bar.ts,seen,manifest)
            last_print=time.monotonic()
    audit=engine.finish()
    audit += [dict(seed_id=s.seed_id,seed_ts=s.ts.isoformat(),event=s.event,
                   status='NO_SEED_BAR',source_path=s.source_path,source_line=s.source_line)
              for s in seeds if s.seed_id not in seen]
    audit.sort(key=lambda r:(r['seed_ts'],r['seed_id']))
    candidates=engine.candidates
    rows(out/'seed_audit.csv',audit)
    rows(out/'candidate_events.csv',engine.events)
    rows(out/'zone_selection_audit.csv',engine.zone_evidence)
    dump(out/'candidates.json',[c.to_dict() for c in candidates])
    rows(out/'candidates.csv',[c.to_dict() for c in candidates])
    verify_inputs(out)
    eligible=[c for c in candidates if replay_eligible(c,manifest)]
    preparation={'raw_seeds':len(seeds),'seed_types':dict(Counter(s.event for s in seeds)),
                 'seed_status':dict(Counter(r['status'] for r in audit)),
                 'armed':sum(e['event']=='ARMED' for e in engine.events),
                 'confirmed_unique':len(candidates),'replay_eligible':len(eligible),
                 'bars':len(bars),'first_bar':bars[0].ts.isoformat(),'last_bar':bars[-1].ts.isoformat(),
                 'feed_gaps':sum(b.ts-a.ts!=timedelta(minutes=1) for a,b in zip(bars,bars[1:])),
                 'structure_references':len(monitor.references),'elapsed_seconds':time.monotonic()-started,
                 'zone_rejections':dict(Counter(e['decision'] for e in engine.zone_evidence))}
    dump(out/'preparation_summary.json',preparation)
    dump(out/'progress.json',{'last_ts':bars[-1].ts,'completed':True,
                             'raw_seeds_processed':len(seen),'confirmations':len(candidates)})
    assert manifest['code_hashes']==code_hashes(),'Code changed while preparing'
    print(json.dumps(preparation,indent=2),flush=True)

def replay_eligible(c,manifest):
    return (utc(manifest['decision_start'])<=datetime.fromisoformat(c.shadow_flags['seed_ts'])
            <=c.signal_ts_utc<=utc(manifest['decision_end']))

def metrics(results, candidates):
    filled=[r for r in results if r.entry_status=='FILLED']
    closed=sorted([r for r in filled if r.lifecycle_class in RESOLVED],key=lambda r:r.exit_ts)
    pnl=np.array([r.net_pnl_usdc for r in closed],dtype=float)
    equity=np.r_[0,np.cumsum(pnl)]
    losses=-float(pnl[pnl<0].sum())
    monthly={}
    for month in sorted({r.signal_ts_utc.strftime('%Y-%m') for r in results}):
        rr=[r for r in closed if r.signal_ts_utc.strftime('%Y-%m')==month]
        monthly[month]={'closed':len(rr),'net_usdc':sum(r.net_pnl_usdc for r in rr)}
    return {'candidates':len(candidates),'filled':len(filled),'closed':len(closed),
            'unresolved':len(filled)-len(closed),'net_usdc':float(pnl.sum()),
            'gross_usdc':sum(r.gross_pnl_usdc for r in closed),
            'commission_usdc':sum(r.commission_usdc for r in closed),
            'slippage_usdc':sum(r.slippage_usdc for r in closed),
            'profit_factor':float(pnl[pnl>0].sum())/losses if losses>0 else None,
            'net_wins':int((pnl>0).sum()),'tp1_hits':sum(r.tp1_fill_ts is not None for r in closed),
            'max_closed_equity_drawdown_usdc':float((np.maximum.accumulate(equity)-equity).max()),
            'unresolved_realized_partial_net':sum(r.net_pnl_usdc or 0 for r in filled if r.lifecycle_class not in RESOLVED),
            'status_counts':dict(Counter(r.entry_status for r in results)),
            'lifecycle_counts':dict(Counter(r.lifecycle_class for r in results)),
            'blocked_reasons':dict(Counter(r.blocked_reason for r in results if r.blocked_reason)),
            'monthly_by_signal_month':monthly}

def replay(out,label):
    manifest=json.loads((out/'protocol_freeze.json').read_text())
    if manifest['code_hashes']!=code_hashes():raise RuntimeError('Code changed since protocol freeze')
    verify_inputs(out)
    destination=out/label
    destination.mkdir(exist_ok=False)
    cfg=CONFIG if label=='base' else replace(CONFIG,exit_slippage_bps=2,stop_slippage_bps=4)
    raw=json.loads((out/'candidates.json').read_text())
    cs=[Candidate(**dict(r,signal_ts_utc=datetime.fromisoformat(r['signal_ts_utc']))) for r in raw]
    cs=[c for c in cs if replay_eligible(c,manifest)]
    signal=[b for b in load_legacy(BASE/'execution_feed/btcusdt_legacy_spot_1m/daily') if b.ts<=utc(manifest['outcome_end'])]
    execution=load_feed(BASE/'execution_feed/btcusdc_spot_1m/daily',date_from='2026-03-19',date_to='2026-08-19',feed_role='official_spot_execution')
    if any(b.ts-a.ts!=timedelta(minutes=1) for a,b in zip(execution,execution[1:])):
        raise ValueError('Execution gap')
    st=[b.ts for b in signal];et=[b.ts for b in execution]
    results=[];events=[];errors=[]
    for i,c in enumerate(cs):
        try:
            r,ev=replay_candidate(c,execution,cfg,reference_bars=signal,_timestamps=et,_reference_timestamps=st)
        except BacktestContractError as exc:
            r=TradeResult(trade_id='ERROR_'+c.candidate_id,candidate_id=c.candidate_id,experiment_id=cfg.experiment_id,
                replay_mode='independent_opportunity',candidate_group=c.candidate_group,side=c.side,
                signal_ts_utc=c.signal_ts_utc,entry_status='INVALID',lifecycle_class='INTEGRITY_ERROR',blocked_reason=str(exc))
            ev=[]
        if r.entry_status=='INVALID':errors.append({'candidate_id':c.candidate_id,'reason':r.blocked_reason})
        results.append(r);events.extend(e.to_dict() for e in ev)
        if (i+1)%20==0:print(label,'replayed',i+1,'/',len(cs),flush=True)
    portfolio,pevents,_=replay_portfolio(cs,results,cfg)
    rows(destination/'independent_trades.csv',(r.to_dict() for r in results))
    rows(destination/'portfolio_trades.csv',(r.to_dict() for r in portfolio))
    rows(destination/'execution_events.csv',events)
    rows(destination/'portfolio_events.csv',(e.to_dict() for e in pevents))
    report={'independent':metrics(results,cs),'portfolio':metrics(portfolio,cs),
            'integrity_errors':errors,'config':cfg.to_dict()}
    dump(destination/'metrics.json',report)
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['prepare','base','double_slippage'])
    parser.add_argument('--output',type=Path,default=HERE/'results_v2')
    parser.add_argument('--resume',action='store_true',help='Resume only a locally generated preparation checkpoint')
    args=parser.parse_args()
    if args.stage=='prepare':prepare(args.output,args.resume)
    else:replay(args.output,args.stage)
