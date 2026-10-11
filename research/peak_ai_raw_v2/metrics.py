"""Closed-trade and block-bootstrap diagnostics shared in semantics with v1."""
import numpy as np
import pandas as pd
from collections import Counter
RESOLVED={"PLAIN_SL","TP1_SL","TP1_TP2_TRAILING_STOP"}
SPLITS={"development":("2026-03-20","2026-05-29","2026-05-31"),"validation":("2026-06-01","2026-06-28","2026-06-30"),"historical_retest":("2026-07-01","2026-08-17","2026-08-19")}

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
