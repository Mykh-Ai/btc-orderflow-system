"""Fixed NEG H4 experiment and matched NEG H1 control; unchanged native replay."""
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import json
import shutil
import pandas as pd
from research.neg_h4_close_v1 import baseline
from research.neg_h4_close_v1.engine import NegCloseEngine
from research.peak_ai_delta_h1_all_signs import run as old
from research.peak_ai_delta_h1_all_signs.engine import DeltaH1Engine
from research.peak_ai_delta_h1_all_signs.query_cache import CachedStructureMonitor, CACHE

HERE=Path(__file__).resolve().parent

def stats(frame):
    closed=frame[(frame.entry_status=='FILLED') & frame.lifecycle_class.isin(old.RESOLVED)]
    net=closed.net_pnl_usdc.astype(float); n=len(closed)
    losses=-net[net<0].sum()
    return {'N':n,'wins':int((net>0).sum()),'losses':int((net<0).sum()),'breakeven':int((net==0).sum()),
        'win_rate_pct':float(100*(net>0).sum()/n) if n else None,
        'gross':float(closed.gross_pnl_usdc.sum()),'commission':float(closed.commission_usdc.sum()),
        'slippage':float(closed.slippage_usdc.sum()),'net':float(net.sum()),
        'gross_per_trade':float(closed.gross_pnl_usdc.sum()/n) if n else None,
        'net_per_trade':float(net.sum()/n) if n else None,
        'PF':float(net[net>0].sum()/losses) if losses else None,
        'unresolved':int(((frame.entry_status=='FILLED') & ~frame.lifecycle_class.isin(old.RESOLVED)).sum()),
        'blocked':int((frame.entry_status=='BLOCKED').sum()),'opportunities':len(frame)}

def timing(minutes):
    assert 0<minutes<=240
    return '<=60' if minutes<=60 else '61-120' if minutes<=120 else '121-180' if minutes<=180 else '181-240'

def signature(c):
    f=c.shadow_flags
    return (f['seed_id'],f['zone_id'],c.signal_ts_utc,c.signal_price,c.delta,c.side,
            f['lower'],f['upper'],f['sweep_start_ts'],f['sweep_high'],f['stop_anchor'])

def mapping(cs,inventory):
    refs={r['zone_id']:r for r in inventory}
    output=[]
    for c in cs:
        f=c.shadow_flags;ref=refs[f['zone_id']];level=json.loads(ref['level'])
        minutes=(c.signal_ts_utc-datetime.fromisoformat(f['seed_ts'])).total_seconds()/60
        output.append(dict(candidate_id=c.candidate_id,seed_id=f['seed_id'],delta=c.delta,
            seed_ts=f['seed_ts'],confirmation_ts=c.signal_ts_utc.isoformat(),zone_id=f['zone_id'],
            price_lower=f['lower'],price_upper=f['upper'],available_at=f['level_available_at'],
            crossed_at=f['crossed_at'],sweep_start_ts=f['sweep_start_ts'],sweep_high=f['sweep_high'],
            stop_anchor=f['stop_anchor'],significance_score=f['significance_score'],bucket=f['bucket'],
            source_timeframe=ref['timeframe'],level_type=level['level_type'],
            delta_to_confirmation_minutes=minutes,timing_bucket=timing(minutes),
            month=c.signal_ts_utc.strftime('%Y-%m')))
    return pd.DataFrame(output)

def enrich(frame,meta):
    result=frame.merge(meta,on='candidate_id',how='left',validate='one_to_one')
    assert result.level_type.notna().all()
    return result

def summaries(label,mode,frame):
    total=dict(experiment=label,mode=mode,**stats(frame)); rows=[]
    for column,values in [('level_type',['H1_SWING_HIGH','H4_SWING_HIGH']),
                          ('month',sorted(frame.month.unique())),
                          ('timing_bucket',['<=60','61-120','121-180','181-240'])]:
        for value in values:rows.append(dict(experiment=label,mode=mode,dimension=column,cohort=value,**stats(frame[frame[column]==value])))
    # Monthly concentration within each structural type is explicitly auditable.
    for level in ['H1_SWING_HIGH','H4_SWING_HIGH']:
        for month in sorted(frame.month.unique()):
            rows.append(dict(experiment=label,mode=mode,dimension='level_month',cohort=level+'|'+month,
                             **stats(frame[(frame.level_type==level)&(frame.month==month)])))
    return total,rows

def run():
    gate=json.loads((HERE/'baseline_parity/result.json').read_text());assert gate['passed']
    out=HERE/'results';out.mkdir(exist_ok=False)
    bars,seeds,execution=baseline.load_inputs();neg=[s for s in seeds if s.delta<0]
    batches=defaultdict(list)
    for s in neg:batches[s.ts].append(s)
    manifest=json.loads((baseline.PRIOR/'protocol_freeze.json').read_text())
    cache=CachedStructureMonitor(bars);inventory=cache.inventory()
    old.rows(out/'structural_inventory.csv',inventory)
    shutil.copyfile(baseline.PRIOR/'input_hashes.csv',out/'input_hashes.csv')
    cache_files=sorted(CACHE.glob('*.json'))+sorted(CACHE.glob('part_*.jsonl'))
    old.rows(out/'query_cache_hashes.csv',({'path':str(p.relative_to(old.ROOT)),'sha256':old.digest(p)} for p in cache_files))
    code=old.code_hashes();code.update({str(p.relative_to(old.ROOT)):old.digest(p) for p in sorted(HERE.glob('*.py'))})
    configs={tf:replace(old.CONFIG,experiment_id='NEG_H4_CLOSE_V1' if tf=='H4' else 'NEG_H1_CONTROL',
                description='Numeric NEG only; frozen upper zone; completed canonical '+tf+' close; horizon four hours') for tf in ['H4','H1']}
    for cfg in configs.values():
        assert {k:v for k,v in cfg.to_dict().items() if k not in ['experiment_id','description']}=={
            k:v for k,v in old.CONFIG.to_dict().items() if k not in ['experiment_id','description']}
    old.dump(out/'config.json',{tf:cfg.to_dict() for tf,cfg in configs.items()})
    old.dump(out/'protocol_freeze.json',dict(base_sha='966dabcc0bef0ac7289905fcdfaf93252e1d1198',
        protocol_sha256=old.digest(HERE/'PROTOCOL.md'),code_hashes=code,decision_start=manifest['decision_start'],
        decision_end=manifest['decision_end'],outcome_end=manifest['outcome_end'],
        seed_filter='numeric delta < 0',horizon_minutes=240,confirmation='canonical completed H4 CLOSE < frozen lower',
        baseline_parity_sha256=old.digest(HERE/'baseline_parity/result.json'),
        input_manifest_sha256=old.digest(out/'input_hashes.csv'),cache_manifest_sha256=old.digest(out/'query_cache_hashes.csv'),
        monitor_head=old.head(old.MONITOR),no_fresh_holdout=True,no_production_change=True))
    totals=[];breakdowns=[];funnels={};frames={};all_cs={};checks=[]
    for tf in ['H1','H4']:
        label=configs[tf].experiment_id;folder=out/label;folder.mkdir()
        cache.last_query=None;e=NegCloseEngine(cache,tf)
        old_control=DeltaH1Engine(cache) if tf=='H1' else None
        # Same cache shared for identical timestamps, no query recomputation.
        for b in bars:
            triggers=batches.get(b.ts,())
            e.step(b,triggers)
            if old_control is not None:old_control.step(b,triggers)
        audit=e.finish()
        if old_control is not None:
            old_control.finish()
            assert [signature(c) for c in e.candidates]==[signature(c) for c in old_control.candidates]
            assert [(r['seed_id'],r['status']) for r in audit]==[(r['seed_id'],r['status']) for r in old_control.audit]
            checks.append('NEG-only H1 exact signal/stop/status parity with unchanged original H1 engine')
        seen={r['seed_id'] for r in audit}
        audit.extend(dict(seed_id=s.seed_id,seed_ts=s.ts.isoformat(),delta=s.delta,event=s.event,
            status='NO_SEED_BAR',source_path=s.source_path,source_line=s.source_line) for s in neg if s.seed_id not in seen)
        cs=[c for c in e.candidates if old.replay_eligible(c,manifest)];all_cs[label]=cs
        old.rows(folder/'seed_audit.csv',audit);old.rows(folder/'candidate_events.csv',e.events)
        # Preserve complete selection evidence efficiently, without repeating query cache blobs.
        old.rows(folder/'zone_selection_audit.csv',e.zone_evidence)
        old.dump(folder/'candidates.json',[c.to_dict() for c in e.candidates])
        old.rows(folder/'candidates.csv',[c.to_dict() for c in e.candidates])
        meta=mapping(cs,inventory);meta.to_csv(folder/'structural_level_mapping.csv',index=False)
        print(label,'raw',len(neg),'confirmed',len(e.candidates),'eligible',len(cs),flush=True)
        independent,portfolio,events,pevents,blocked=baseline.replay(cs,bars,execution,configs[tf])
        old.rows(folder/'execution_events.csv',events)
        old.rows(folder/'portfolio_events.csv',(r.to_dict() for r in pevents))
        old.rows(folder/'blocked_opportunities.csv',blocked)
        for mode,rr in [('independent',independent),('portfolio',portfolio)]:
            frame=enrich(pd.DataFrame([r.to_dict() for r in rr]),meta)
            frame.to_csv(folder/(mode+'_trades.csv'),index=False);frames[(label,mode)]=frame
            total,bb=summaries(label,mode,frame);totals.append(total);breakdowns.extend(bb)
            closed=frame[frame.entry_status=='FILLED']
            assert ((closed.gross_pnl_usdc-closed.commission_usdc-closed.slippage_usdc-closed.net_pnl_usdc).abs()<1e-8).all()
            assert (closed.side=='SHORT').all() and (closed.delta<0).all()
            assert (pd.to_datetime(closed.entry_fill_ts,utc=True)>pd.to_datetime(closed.confirmation_ts,utc=True)).all()
            if mode=='portfolio':
                trades=closed.sort_values('entry_fill_ts')
                assert all(pd.Timestamp(b)>pd.Timestamp(a) for a,b in zip(trades.exit_ts.iloc[:-1],trades.entry_fill_ts.iloc[1:]))
        counts=dict(Counter(r['status'] for r in audit));pc=stats(frames[(label,'portfolio')])
        funnels[label]=dict(raw_NEG_seeds=len(neg),armed=sum(x['event']=='ARMED' for x in e.events),
            no_eligible_zone=counts.get('NO_ELIGIBLE_ZONE',0),duplicate_pending=counts.get('DUPLICATE_PENDING_ZONE',0),
            expired=counts.get('EXPIRED',0),confirmed_all=len(e.candidates),confirmed_decision_eligible=len(cs),
            independent_trades=stats(frames[(label,'independent')])['N'],portfolio_opened=pc['N'],portfolio_blocked=pc['blocked'],
            statuses=counts)
        assert sum(counts.values())==len(neg)
        for c in cs:
            f=c.shadow_flags;t=c.signal_ts_utc;seedts=datetime.fromisoformat(f['seed_ts'])
            assert c.signal_price<f['price_lower'] and seedts<t<=seedts+old.timedelta(hours=4)
            assert f['price']>f['price_upper'] and datetime.fromisoformat(f['available_at'])<seedts
            assert f['level_type'] in ['H1_SWING_HIGH','H4_SWING_HIGH']
            assert f['frozen_zone']['price_lower']==f['lower'] and f['frozen_zone']['price_upper']==f['upper']
            if tf=='H4':assert t.hour%4==0 and t.minute==0 and t.second==0
        checks.append(label+': costs, SHORT/NEG, entry causality, horizon, bounds, frozen identity, portfolio concurrency')
    # Historical NEG contribution, unchanged all-sign ownership/concurrency.
    raw=json.loads((baseline.PRIOR/'candidates.json').read_text())
    cs=[old.Candidate(**dict(c,signal_ts_utc=datetime.fromisoformat(c['signal_ts_utc']))) for c in raw]
    cs=[c for c in cs if c.delta<0 and old.replay_eligible(c,manifest)]
    meta=mapping(cs,inventory)
    for mode in ['independent','portfolio']:
        frame=pd.read_csv(HERE/'baseline_parity'/(mode+'_trades.csv'))
        frame=frame[frame.candidate_id.isin(meta.candidate_id)]
        frame=enrich(frame,meta);label='NEG_H1_BASELINE'
        frame.to_csv(out/(label+'_'+mode+'.csv'),index=False);frames[(label,mode)]=frame
        total,bb=summaries(label,mode,frame);totals.append(total);breakdowns.extend(bb)
    old.dump(out/'aggregate_metrics.json',totals);old.rows(out/'aggregate_metrics.csv',totals)
    old.rows(out/'breakdown_metrics.csv',breakdowns)
    old.rows(out/'monthly_metrics.csv',[r for r in breakdowns if r['dimension'] in ['month','level_month']])
    old.rows(out/'structural_metrics.csv',[r for r in breakdowns if r['dimension']=='level_type'])
    old.rows(out/'timing_metrics.csv',[r for r in breakdowns if r['dimension']=='timing_bucket'])
    old.dump(out/'funnel.json',funnels)
    sets={label:{c.shadow_flags['seed_id'] for c in candidates} for label,candidates in all_cs.items()}
    h1=sets['NEG_H1_CONTROL'];h4=sets['NEG_H4_CLOSE_V1']
    old.dump(out/'opportunity_comparison.json',{'unit':'owning NEG seed; not a time-delay filter',
        'H1_only':sorted(h1-h4),'H4_only':sorted(h4-h1),'common':sorted(h1&h4),
        'H1_total':len(h1),'H4_total':len(h4)})
    baseline.old.verify_inputs(baseline.PRIOR)
    assert code=={**old.code_hashes(),**{str(p.relative_to(old.ROOT)):old.digest(p) for p in sorted(HERE.glob('*.py'))}}
    old.dump(out/'verification.json',{'passed':True,'checks':checks,'input_hashes_reverified':True,
        'code_hashes_unchanged_during_run':True,'baseline_parity_passed':True})
    print(json.dumps(totals,indent=2),flush=True)

if __name__=='__main__':run()
