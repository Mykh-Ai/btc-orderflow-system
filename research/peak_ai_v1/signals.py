"""Offline Peak_Ai: causal extreme-delta continuation, pullback and failed auction."""
from __future__ import annotations
import hashlib
import json
from collections import deque
from datetime import timedelta
from dataclasses import dataclass
from typing import Iterable
from deltascout.research_bundle.scout_backtester.contracts import Candidate, FeedBar

FAMILIES = tuple(f'{family}_{strength}' for family in ('continuation','pullback','failed_extreme') for strength in (15,30))

@dataclass
class Pending:
    seed: FeedBar
    side: str
    retraced: bool = False


def _make(bar: FeedBar, family: str, seed: FeedBar, evidence: dict) -> Candidate:
    side = evidence['side']
    payload = {'family':family,'decision_ts':bar.ts.isoformat(),'seed_ts':seed.ts.isoformat(),
               'side':side,'close':bar.close,'delta':bar.buy_qty-bar.sell_qty,**evidence}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    return Candidate(candidate_id='PAI_'+digest[:20],source_event_ts_local=bar.ts.isoformat(),
        signal_ts_utc=bar.ts,side=side,event_type='PEAK_AI',candidate_group='PEAK_AI_'+family,
        reject_reason=None,signal_price=bar.close,delta=bar.buy_qty-bar.sell_qty,volume=bar.volume,
        imbalance=abs(bar.buy_qty-bar.sell_qty)/bar.volume if bar.volume>0 else None,
        vwap=None,poc=None,comparison_3of3_pass_count=None,comparison_3of3_failed_subconditions=None,
        shadow_flags=payload,source_path=bar.source_path,source_row_hash=digest)


def generate(bars: Iterable[FeedBar]) -> dict[str,list[Candidate]]:
    """State can be deterministically rebuilt by replaying the preceding history."""
    out={f:[] for f in FAMILIES}
    history:deque[FeedBar]=deque(maxlen=180)
    pending:dict[tuple[int,str],Pending]={}
    previous_ts=None
    for bar in bars:
        valid=(not bar.is_synthetic and bar.volume>0 and bar.high>bar.low)
        if previous_ts is not None and bar.ts-previous_ts!=timedelta(minutes=1):
            history.clear();pending.clear()
        previous_ts=bar.ts
        if not valid:
            history.clear();pending.clear();continue
        if len(history)<180:
            history.append(bar);continue
        prev=history[-1]
        # Pending decisions only use bars closed after their seed, never the seed itself.
        for key,p in list(pending.items()):
            strength,side=key;sign=1 if side=='LONG' else -1
            midpoint=(p.seed.high+p.seed.low)/2
            expired=bar.ts-p.seed.ts>timedelta(minutes=10)
            if expired or sign*(bar.close-midpoint)<=0:
                del pending[key];continue
            was_retraced=p.retraced
            retrace=(bar.low<=p.seed.close-0.25*(p.seed.high-p.seed.low) if sign==1
                     else bar.high>=p.seed.close+0.25*(p.seed.high-p.seed.low))
            p.retraced=p.retraced or retrace
            breakout=bar.close>prev.high if sign==1 else bar.close<prev.low
            if was_retraced and breakout and sign*(bar.buy_qty-bar.sell_qty)>0:
                family=f'pullback_{strength}'
                out[family].append(_make(bar,family,p.seed,{'side':side,'strength':strength,
                    'seed_delta':p.seed.buy_qty-p.seed.sell_qty,'confirmation':'prior_retrace_then_prior_bar_break'}))
                del pending[key]
        delta=bar.buy_qty-bar.sell_qty
        prior_deltas=[x.buy_qty-x.sell_qty for x in history]
        side=('LONG' if delta>0 and delta>max(prior_deltas) else
              'SHORT' if delta<0 and delta<min(prior_deltas) else None)
        if side:
            sign=1 if side=='LONG' else -1
            last20=list(history)[-20:]
            hi=max(x.high for x in last20);lo=min(x.low for x in last20)
            clv=(bar.close-bar.low)/(bar.high-bar.low)
            flow=sum(x.buy_qty-x.sell_qty for x in list(history)[-60:])
            cont=(bar.close>hi and clv>=0.7 if sign==1 else bar.close<lo and clv<=0.3) and sign*flow>0
            failed=(bar.high>hi and bar.close<hi and clv<=0.5 if sign==1
                    else bar.low<lo and bar.close>lo and clv>=0.5)
            evidence={'side':side,'delta_pct':abs(delta)/bar.volume,'prior_high20':hi,'prior_low20':lo,
                      'close_location':clv,'prior_delta60':flow,'extreme_window':180}
            for strength in (15,30):
                if abs(delta)/bar.volume<strength/100:continue
                if cont:
                    family=f'continuation_{strength}'
                    out[family].append(_make(bar,family,bar,{**evidence,'strength':strength}))
                    pending.setdefault((strength,side),Pending(bar,side))
                if failed:
                    family=f'failed_extreme_{strength}'
                    out[family].append(_make(bar,family,bar,{**evidence,'strength':strength,
                        'side':'SHORT' if side=='LONG' else 'LONG','extreme_side':side}))
        history.append(bar)
    return out
