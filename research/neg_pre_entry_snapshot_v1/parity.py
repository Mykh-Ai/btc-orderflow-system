"""Exact primary cohort gate, using stored candidate IDs and unchanged replay."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from research.neg_h4_close_v1 import baseline
from research.neg_h4_close_v1.run import signature
from research.peak_ai_delta_h1_all_signs.engine import DeltaH1Engine
from research.peak_ai_delta_h1_all_signs.query_cache import CachedStructureMonitor
old=baseline.old
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'neg_h4_close_v1/results'
COHORT=PRIOR/'NEG_H1_CONTROL'
def candidates():
    raw=json.loads((COHORT/'candidates.json').read_text());manifest=json.loads((PRIOR/'protocol_freeze.json').read_text())
    cs=[old.Candidate(**dict(r,signal_ts_utc=datetime.fromisoformat(r['signal_ts_utc']))) for r in raw]
    return [c for c in cs if old.replay_eligible(c,manifest)]
def run():
    out=HERE/'parity';out.mkdir(exist_ok=True)
    bars,seeds,execution=baseline.load_inputs();cs=candidates();assert len(cs)==262
    cached=CachedStructureMonitor(bars);e=DeltaH1Engine(cached);batches=defaultdict(list)
    for s in seeds:
        if s.delta<0:batches[s.ts].append(s)
    for b in bars:e.step(b,batches.get(b.ts,()))
    e.finish();m=json.loads((PRIOR/'protocol_freeze.json').read_text())
    rebuilt=[c for c in e.candidates if old.replay_eligible(c,m)]
    assert [signature(c) for c in rebuilt]==[signature(c) for c in cs]
    for c in cs:
        f=c.shadow_flags;expected='NEGH1_'+hashlib.sha256(f"{f['seed_id']}|{f['zone_id']}|{c.signal_ts_utc.isoformat()}".encode()).hexdigest()[:20]
        assert expected==c.candidate_id
    cfg=old.ReplayConfig(**json.loads((PRIOR/'config.json').read_text())['H1'])
    rr,pp,_,_,_=baseline.replay(cs,bars,execution,cfg)
    current=pd.DataFrame([r.to_dict() for r in rr]).set_index('candidate_id').sort_index()
    original=pd.read_csv(COHORT/'independent_trades.csv').set_index('candidate_id').sort_index()
    assert list(current.index)==list(original.index)
    financial=['gross_pnl_usdc','commission_usdc','slippage_usdc','net_pnl_usdc','position_r','planned_entry_price_usdt','initial_stop_price_usdt','tp1_price_usdt','tp2_price_usdt']
    for col in financial:assert np.allclose(current[col],original[col],atol=1e-9,rtol=0,equal_nan=True),col
    for col in ['entry_status','lifecycle_class','entry_fill_ts','exit_ts','tp1_fill_ts','tp2_fill_ts']:
        assert list(current[col].fillna('').astype(str))==list(original[col].fillna('').astype(str)),col
    metrics=old.metrics(rr,cs);expected=next(x for x in json.loads((PRIOR/'aggregate_metrics.json').read_text()) if x['experiment']=='NEG_H1_CONTROL' and x['mode']=='independent')
    assert (metrics['closed'],metrics['net_wins'])==(262,105)
    for key,source in [('net_usdc','net'),('gross_usdc','gross'),('profit_factor','PF')]:assert abs(metrics[key]-expected[source])<1e-9
    old.dump(out/'result.json',dict(passed=True,candidates=262,wins=105,losses=157,metrics=metrics,
        candidate_ids_exact=True,signal_stop_geometry_exact=True,per_trade_financial_fields_exact=financial,
        per_trade_tolerance=1e-9,source_sha256=old.digest(COHORT/'independent_trades.csv')))
    print('PRIMARY PARITY PASS',metrics['net_usdc'],flush=True)
if __name__=='__main__':run()
