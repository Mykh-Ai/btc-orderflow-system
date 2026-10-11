"""Raw-journal seeds -> causal entry candidates. No terminal Scout events or gates."""
from __future__ import annotations
import csv, hashlib, json, math, statistics
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from deltascout.research_bundle.scout_backtester.contracts import Candidate, FeedBar
from deltascout.research_bundle.scout_backtester.candidate_compiler import local_event_to_utc
from deltascout.research_bundle.scout_backtester.feed_loader import parse_feed_timestamp

MODES=('immediate_follow','immediate_fade','break_follow','break_reverse')
CONTEXTS=('all','activity','resistance','trend')
FAMILIES=tuple(m+'__'+c for m in MODES for c in CONTEXTS)
RAW_EVENTS={'DELTA_MAX','DELTA_MIN'}

@dataclass(frozen=True)
class Seed:
    seed_id:str
    ts:object
    local_ts:str
    side:str
    delta:float
    volume:float
    event:str
    source_path:str
    source_line:int
    row_hash:str

def load_seeds(root:Path):
    seeds=[]; seen={}
    for path in sorted(root.glob('*.jsonl')):
        for lineno,line in enumerate(path.open(),1):
            if not line.strip():continue
            row=json.loads(line)
            if row.get('event') not in RAW_EVENTS:continue
            ts=local_event_to_utc(row['ts']);key=(ts,row['event'])
            if key in seen:raise ValueError(f'Duplicate raw seed {key}: {path}:{lineno}')
            seen[key]=True
            side='LONG' if row['event']=='DELTA_MAX' else 'SHORT'
            delta=float(row['delta']);volume=float(row['vol'])
            if not all(math.isfinite(v) for v in (delta,volume)) or volume<=0:raise ValueError('Invalid seed numbers')
            if row['kind'].upper()!=side:raise ValueError('Seed kind mismatch')
            h=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            seeds.append(Seed('RAW_'+h[:20],ts,row['ts'],side,delta,volume,row['event'],str(path),lineno,h))
    return sorted(seeds,key=lambda s:(s.ts,s.seed_id))

def load_legacy(root:Path):
    """Explicit Spot loader; do not apply SHI Futures recovery metadata to Spot."""
    bars=[];seen=set()
    for path in sorted(root.glob('*.csv')):
        for lineno,row in enumerate(csv.DictReader(path.open()),2):
            ts=parse_feed_timestamp(row['Timestamp'])
            if ts in seen:raise ValueError(f'Duplicate legacy minute {ts}')
            seen.add(ts)
            values=[float(row[k]) for k in ('Open','High','Low','Close','Volume','BuyQty','SellQty')]
            if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite legacy values')
            o,h,l,c,v,b,s=values
            if min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or min(v,b,s)<0:raise ValueError('Invalid legacy OHLC/volume')
            synthetic=row['IsSynthetic'].strip().lower() in ('1','true','yes')
            bars.append(FeedBar(ts,o,h,l,c,v,b,s,synthetic,'LEGACY_BTCUSDT_SPOT',False,str(path),lineno))
    bars.sort(key=lambda b:b.ts)
    return bars

def valid(bar):return not bar.is_synthetic and bar.volume>0 and bar.high>=bar.low

def generate(seeds,bars):
    index={b.ts:i for i,b in enumerate(bars)}
    groups={f:[] for f in FAMILIES};audit=[];duplicates=[]
    for seed in seeds:
        row={'seed_id':seed.seed_id,'ts':seed.ts.isoformat(),'event':seed.event,'delta':seed.delta,
             'volume':seed.volume,'source_path':seed.source_path,'source_line':seed.source_line}
        i=index.get(seed.ts)
        if i is None:row['status']='NO_SEED_BAR';audit.append(row);continue
        b=bars[i]
        row.update(delta_error=abs(seed.delta-(b.buy_qty-b.sell_qty)),volume_error=abs(seed.volume-b.volume))
        if row['delta_error']>0.011 or row['volume_error']>0.011:raise ValueError(f'Journal/feed mismatch {seed.seed_id}')
        hist=bars[max(0,i-60):i+1]
        if len(hist)!=61 or any(not valid(x) for x in hist) or any(y.ts-x.ts!=timedelta(minutes=1) for x,y in zip(hist,hist[1:])):
            row['status']='INCOMPLETE_VALID_60M_CONTEXT';audit.append(row);continue
        sign=1 if seed.side=='LONG' else -1
        clv=(b.close-b.low)/(b.high-b.low) if b.high>b.low else None
        ratio=b.volume/statistics.median(x.volume for x in hist[:-1])
        trend=b.close-hist[0].close
        resist=clv is not None and sign*(clv-0.5)<=0
        row.update(status='USABLE',volume_ratio=ratio,close_location=clv,trend60=trend,resistance=resist)
        decisions={'immediate_follow':b,'immediate_fade':b}
        last=b
        for nxt in bars[i+1:i+11]:
            if nxt.ts-last.ts!=timedelta(minutes=1) or not valid(nxt):break
            last=nxt
            follow=nxt.close>b.high if sign==1 else nxt.close<b.low
            reverse=nxt.close<b.low if sign==1 else nxt.close>b.high
            if follow:decisions.setdefault('break_follow',nxt)
            if reverse:decisions.setdefault('break_reverse',nxt)
        row['decision_modes']='|'.join(decisions);audit.append(row)
        for mode,decision in decisions.items():
            trade_sign=sign if mode in ('immediate_follow','break_follow') else -sign
            side='LONG' if trade_sign==1 else 'SHORT'
            conditions={'all':True,'activity':ratio>=2,'resistance':resist,'trend':trade_sign*trend>0}
            for context,passed in conditions.items():
                if not passed:continue
                family=mode+'__'+context
                payload={'seed_id':seed.seed_id,'seed_ts':seed.ts.isoformat(),'seed_event':seed.event,
                         'seed_delta':seed.delta,'volume_ratio':ratio,'close_location':clv,'trend60':trend,
                         'seed_high':b.high,'seed_low':b.low,'entry_mode':mode,'context':context,
                         'decision_ts':decision.ts.isoformat(),'side':side}
                h=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
                groups[family].append(Candidate('PAIRAW_'+h[:20],seed.local_ts,decision.ts,side,
                    'PEAK_AI_RAW','PEAK_AI_RAW_'+family,None,decision.close,seed.delta,seed.volume,
                    abs(seed.delta)/seed.volume,None,None,None,None,payload,seed.source_path,seed.row_hash))
    for family,cs in groups.items():
        seen={};unique=[]
        for c in sorted(cs,key=lambda c:(c.signal_ts_utc,c.shadow_flags['seed_ts'],c.candidate_id)):
            key=(c.signal_ts_utc,c.side)
            if key in seen:
                duplicates.append({'family':family,'discarded_candidate_id':c.candidate_id,'kept_candidate_id':seen[key].candidate_id,
                                   'discarded_seed_id':c.shadow_flags['seed_id']})
            else:seen[key]=c;unique.append(c)
        groups[family]=unique
    return groups,audit,duplicates
