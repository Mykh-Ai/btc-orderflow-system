"""Fail-closed reproduction gate, using the unchanged corrected H1 implementation."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import math
import pandas as pd
from research.peak_ai_delta_h1_all_signs import run as old
from research.peak_ai_delta_h1_all_signs.engine import DeltaH1Engine
from research.peak_ai_delta_h1_all_signs.query_cache import CachedStructureMonitor

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent/'peak_ai_delta_h1_all_signs/results_v2'
EXPECTED = {
    'independent': (515,192,323,-2612.7512593,-42.5851329),
    'negative': (164,69,95,-455.1569238,362.6545122),
    'positive': (351,123,228,-2157.5943355,-405.2396451),
    'portfolio': (226,82,144,-1401.9452982,-273.1020277),
}

def load_inputs():
    old.verify_inputs(PRIOR)
    bars = [b for b in old.load_legacy(old.BASE/'execution_feed/btcusdt_legacy_spot_1m/daily')
            if b.ts <= old.utc('2026-08-19T23:59:00+00:00')]
    seeds = old.load_seeds(old.BASE/'raw_archive')
    execution = old.load_feed(old.BASE/'execution_feed/btcusdc_spot_1m/daily',
        date_from='2026-03-19',date_to='2026-08-19',feed_role='official_spot_execution')
    assert all((b.ts-a.ts).total_seconds()==60 for a,b in zip(execution,execution[1:]))
    return bars,seeds,execution

def normalize(value):
    if isinstance(value,dict):return {k:normalize(v) for k,v in value.items()}
    if isinstance(value,list):return [normalize(v) for v in value]
    if isinstance(value,str) and '/deltascout/research_material/' in value:
        return 'deltascout/research_material/'+value.split('/deltascout/research_material/',1)[1]
    return value

def replay(cs,bars,execution,cfg):
    st=[b.ts for b in bars];et=[b.ts for b in execution];results=[];events=[]
    for i,c in enumerate(cs):
        r,ev=old.replay_candidate(c,execution,cfg,reference_bars=bars,_timestamps=et,_reference_timestamps=st)
        assert r.entry_status!='INVALID', (c.candidate_id,r.blocked_reason)
        results.append(r);events.extend(e.to_dict() for e in ev)
        if (i+1)%100==0:print('replay',i+1,'/',len(cs),flush=True)
    portfolio,pevents,blocked=old.replay_portfolio(cs,results,cfg)
    return results,portfolio,events,pevents,blocked

def run():
    out=HERE/'baseline_parity';out.mkdir(exist_ok=False)
    bars,seeds,execution=load_inputs();print('inputs verified',len(bars),len(seeds),flush=True)
    monitor=CachedStructureMonitor(bars);engine=DeltaH1Engine(monitor);batches=defaultdict(list)
    for s in seeds:batches[s.ts].append(s)
    for b in bars:engine.step(b,batches.get(b.ts,()))
    audit=engine.finish()
    expected=json.loads((PRIOR/'candidates.json').read_text())
    actual=json.loads(json.dumps([c.to_dict() for c in engine.candidates],default=str))
    assert normalize(actual)==normalize(expected),'candidate parity failed'
    original=pd.read_csv(PRIOR/'seed_audit.csv').set_index('seed_id').status.to_dict()
    assert {r['seed_id']:r['status'] for r in audit}==original,'seed status parity failed'
    print('exact candidate and seed status parity passed',flush=True)
    manifest=json.loads((PRIOR/'protocol_freeze.json').read_text())
    cs=[c for c in engine.candidates if old.replay_eligible(c,manifest)]
    results,portfolio,events,pevents,blocked=replay(cs,bars,execution,old.CONFIG)
    sign={c.candidate_id:c.delta for c in cs}
    groups={'independent':results,'negative':[r for r in results if sign[r.candidate_id]<0],
            'positive':[r for r in results if sign[r.candidate_id]>0],'portfolio':portfolio}
    report={}
    for name,rr in groups.items():
        m=old.metrics(rr,cs);n,w,l,net,gross=EXPECTED[name]
        assert (m['closed'],m['net_wins'],m['closed']-m['net_wins'])==(n,w,l),(name,m)
        assert math.isclose(m['net_usdc'],net,abs_tol=1e-7,rel_tol=0),(name,'net')
        assert math.isclose(m['gross_usdc'],gross,abs_tol=1e-7,rel_tol=0),(name,'gross')
        report[name]=m
    assert len(blocked)==289
    fields=['entry_status','lifecycle_class','entry_fill_ts','exit_ts','entry_fill_price','initial_stop_price',
            'gross_pnl_usdc','commission_usdc','slippage_usdc','net_pnl_usdc','blocked_reason']
    for mode,rr in [('independent',results),('portfolio',portfolio)]:
        current=pd.DataFrame([r.to_dict() for r in rr]).set_index('candidate_id').sort_index()
        prior=pd.read_csv(PRIOR/'base'/f'{mode}_trades.csv').set_index('candidate_id').sort_index()
        cols=[c for c in fields if c in current and c in prior]
        assert list(current.index)==list(prior.index)
        for col in cols:
            if pd.api.types.is_numeric_dtype(current[col]):
                import numpy as np
                assert np.allclose(current[col].astype(float),prior[col].astype(float),rtol=0,atol=1e-9,equal_nan=True),(mode,col)
            else:
                assert list(current[col].fillna('').astype(str))==list(prior[col].fillna('').astype(str)),(mode,col)
        old.rows(out/f'{mode}_trades.csv',(r.to_dict() for r in rr))
    old.dump(out/'result.json',{'passed':True,'exact_candidates':len(actual),'exact_seed_statuses':len(audit),
        'blocked':len(blocked),'financial_tolerance':1e-7,'per_trade_tolerance':1e-9,'metrics':report})
    old.verify_inputs(PRIOR)
    print('BASELINE PARITY PASSED',flush=True)

if __name__=='__main__':run()
