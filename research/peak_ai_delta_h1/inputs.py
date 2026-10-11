"""Archived Spot and raw delta loaders, preserved from raw-v2 audited input contract."""
from __future__ import annotations
import csv, hashlib, json, math
from dataclasses import dataclass
from pathlib import Path
from deltascout.research_bundle.scout_backtester.contracts import FeedBar
from deltascout.research_bundle.scout_backtester.candidate_compiler import local_event_to_utc
from deltascout.research_bundle.scout_backtester.feed_loader import parse_feed_timestamp
RAW_EVENTS={"DELTA_MAX","DELTA_MIN"}

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

