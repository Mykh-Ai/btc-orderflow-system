"""Recover a missing summary from immutable native trade ledgers; verify existing rows."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import pandas as pd
from research.peak_ai_raw_v2.metrics import summary
from research.peak_ai_raw_v2.signals import FAMILIES

def equivalent(a,b):
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):return abs(a-b)<1e-7
    return a==b

def main():
    out=Path(__file__).resolve().parents[1]/'results';root=out/'development_base';p=root/'metrics.json'
    original=p.read_bytes();native=json.loads(original);rebuilt={}
    for family in FAMILIES:
        data={}
        for mode in ('portfolio','independent'):
            df=pd.read_csv(root/f'{family}_{mode}.csv');rs=[]
            for row in df.to_dict('records'):
                r={k:(None if pd.isna(v) else v) for k,v in row.items()}
                for k,v in list(r.items()):
                    if v is not None and (k.endswith('_ts') or k=='signal_ts_utc'):r[k]=datetime.fromisoformat(v)
                rs.append(SimpleNamespace(**r))
            data[mode]=summary(rs,[None]*len(rs),'development')
        data['integrity_errors']=int((pd.read_csv(root/f'{family}_independent.csv').lifecycle_class=='INTEGRITY_ERROR').sum())
        rebuilt[family]=data
        if family in native:assert equivalent(data,native[family]),family
    missing=[f for f in FAMILIES if f not in native]
    if not missing:print('All summaries present and verified');return
    for f in missing:native[f]=rebuilt[f]
    p.write_text(json.dumps(native,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n')
    note={'reason':'Completed process logged 16 results but persisted metrics had only 15. Restored missing summary from completed native ledgers; every existing summary verified within 1e-7 recursively. No signal, trade or selection rule changed.',
        'missing_families_restored':missing,'original_metrics_sha256':hashlib.sha256(original).hexdigest(),
        'restored_metrics_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'existing_summaries_verified':len(native)-len(missing)}
    (out/'summary_reconciliation.json').write_text(json.dumps(note,indent=2)+'\n');print(note)

if __name__=='__main__':main()
