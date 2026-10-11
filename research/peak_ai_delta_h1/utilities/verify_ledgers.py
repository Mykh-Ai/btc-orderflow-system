"""Reconcile saved economic ledgers after native replay; no strategy tuning."""
import json,math
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results_v1_checkpointed'
checks=[]
for label in ['base','double_slippage']:
 metrics=json.loads((OUT/label/'metrics.json').read_text())
 for mode,file in [('independent','independent_trades.csv'),('portfolio','portfolio_trades.csv')]:
  df=pd.read_csv(OUT/label/file)
  closed=df[(df.entry_status=='FILLED') & df.lifecycle_class.isin(['PLAIN_SL','TP1_SL','TP1_TP2_TRAILING_STOP'])]
  m=metrics[mode]
  assert len(closed)==m['closed'];checks.append(label+'/'+mode+'/count')
  for key,column in [('net_usdc','net_pnl_usdc'),('gross_usdc','gross_pnl_usdc'),('commission_usdc','commission_usdc'),('slippage_usdc','slippage_usdc')]:
   assert math.isclose(float(closed[column].sum()),m[key],rel_tol=0,abs_tol=1e-6),(label,mode,key)
   checks.append(label+'/'+mode+'/'+key)
  assert ((closed.gross_pnl_usdc-closed.commission_usdc-closed.slippage_usdc-closed.net_pnl_usdc).abs()<1e-6).all()
  checks.append(label+'/'+mode+'/gross_minus_cost')
  entered=df[df.entry_status=='FILLED']
  assert (pd.to_datetime(entered.entry_fill_ts,utc=True)>pd.to_datetime(entered.signal_ts_utc,utc=True)).all()
  checks.append(label+'/'+mode+'/entry_after_confirmation')
  assert (entered.initial_stop_price>entered.entry_fill_price).all()
  checks.append(label+'/'+mode+'/protective_short_stop')
prep=json.loads((OUT/'preparation_summary.json').read_text())
audit=pd.read_csv(OUT/'seed_audit.csv')
events=pd.read_csv(OUT/'candidate_events.csv')
assert len(audit)==prep['raw_seeds']
assert (events.event=='ARMED').sum()==prep['armed']
assert (audit.status=='CONFIRMED').sum()==prep['confirmed_unique']
checks+=['all_seeds_accounted','armed_event_count','confirmed_count']
candidates=json.loads((OUT/'candidates.json').read_text())
for c in candidates:
 f=c['shadow_flags'];start=pd.Timestamp(f['seed_ts']);confirm=pd.Timestamp(c['signal_ts_utc'])
 assert start<confirm<=start+pd.Timedelta(hours=4)
 assert float(c['signal_price'])<float(f['lower'])
 assert float(f['price'])>float(f['upper'])
 assert pd.Timestamp(f['level_available_at'])<pd.Timestamp(f['crossed_at'])<=start
 assert pd.Timestamp(f['sweep_end_ts'])==confirm
checks+=['all_candidate_deadlines','strict_reclaim','price_above_zone_at_delta','preexisting_levels','frozen_stop_cutoff']
zones=pd.read_csv(OUT/'zone_selection_audit.csv')
for seed_id,group in zones[zones.decision=='ELIGIBLE'].groupby('seed_id'):
 row=audit[audit.seed_id==seed_id].iloc[0]
 ranked=group.assign(distance=float(row.price)-group.price_upper).sort_values(
  ['distance','significance_score','zone_id'],ascending=[True,False,True])
 assert row.zone_id==ranked.iloc[0].zone_id
checks+=['nearest_significant_zone_selection']
result={'passed':True,'checks':checks,'count':len(checks)}
(OUT/'ledger_verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
