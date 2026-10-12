"""Descriptive outcome comparisons; no thresholds promoted to entry filters."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr
from .run import HERE, dump

def metrics(f):
    g=f.gross_pnl_usdc;n=f.net_pnl_usdc
    return dict(N=len(f),gross_wins=int(g.gt(0).sum()),net_wins=int(n.gt(0).sum()),
        gross_win_rate=float(g.gt(0).mean()),net_win_rate=float(n.gt(0).mean()),
        gross=float(g.sum()),net=float(n.sum()),gross_per_trade=float(g.mean()),net_per_trade=float(n.mean()),
        PF=float(n[n>0].sum()/-n[n<0].sum()) if (n<0).any() else None)

def describe(x):
    x=x.dropna()
    return dict(N=len(x),mean=x.mean(),median=x.median(),P25=x.quantile(.25),P75=x.quantile(.75))

def bh(p):
    p=np.asarray(p);order=np.argsort(p);ranked=p[order]
    q=np.minimum.accumulate((ranked*len(p)/np.arange(1,len(p)+1))[::-1])[::-1].clip(0,1)
    result=np.empty(len(p));result[order]=q;return result

def run():
    d=pd.read_csv(HERE/'data/forensic_dataset.csv');assert len(d)==262
    names=json.loads((HERE/'config.json').read_text())['feature_names']
    out=HERE/'analysis';out.mkdir(exist_ok=True)
    summary=[];quartiles=[];monthly=[];comparisons={};bins={}
    for name in names:
        x=d[name];summary.append(dict(feature=name,missing=int(x.isna().sum()),coverage=float(x.notna().mean()),**describe(x)))
        if x.nunique()>1:
            q=pd.qcut(x,4,labels=False,duplicates='drop')
            bins[name]=q
            for bucket,sub in d.assign(quartile=q).dropna(subset=['quartile']).groupby('quartile'):
                observed=x.loc[sub.index]
                quartiles.append(dict(feature=name,quartile=int(bucket)+1,min=float(observed.min()),max=float(observed.max()),**metrics(sub)))
            for (month,bucket),sub in d.assign(quartile=q).dropna(subset=['quartile']).groupby(['month','quartile']):
                monthly.append(dict(feature=name,month=month,quartile=int(bucket)+1,**metrics(sub)))
    for label,col in [('gross','gross_pnl_usdc'),('net','net_pnl_usdc')]:
        rows=[]
        for name in names:
            a=d.loc[d[col]>0,name].dropna();b=d.loc[d[col]<0,name].dropna()
            u,p=mannwhitneyu(a,b,alternative='two-sided',method='asymptotic') if len(a) and len(b) else (np.nan,np.nan)
            row=dict(feature=name,coverage=float(d[name].notna().mean()),
                rank_biserial=2*u/(len(a)*len(b))-1 if len(a)*len(b) else np.nan,p=p)
            for prefix,x in [('winner',a),('loser',b)]:row.update({prefix+'_'+k:v for k,v in describe(x).items()})
            rows.append(row)
        comp=pd.DataFrame(rows);valid=comp.p.notna();comp.loc[valid,'bh_q']=bh(comp.loc[valid,'p'])
        comp['abs_effect']=comp.rank_biserial.abs();comp=comp.sort_values('abs_effect',ascending=False)
        comp.to_csv(out/f'{label}_winner_loser_comparison.csv',index=False)
        comparisons[label]=comp
    pd.DataFrame(summary).to_csv(out/'feature_summary.csv',index=False)
    pd.DataFrame(quartiles).to_csv(out/'quartile_diagnostics.csv',index=False)
    pd.DataFrame(monthly).to_csv(out/'monthly_stability.csv',index=False)
    pd.DataFrame([dict(month=k,**metrics(v)) for k,v in d.groupby('month')]).to_csv(out/'monthly_overall.csv',index=False)
    # Outcome categories are labels, not pre-entry features or proposed filters.
    cats=[]
    for field in ['lifecycle_class','portfolio_blocked']:
        for value,g in d.groupby(field):cats.append(dict(field=field,value=value,**metrics(g)))
    pd.DataFrame(cats).to_csv(out/'categorical_outcomes.csv',index=False)
    m=metrics(d);m.update(commission=float(d.commission_usdc.sum()),slippage=float(d.slippage_usdc.sum()),
        gross_positive_net_negative=int(((d.gross_pnl_usdc>0)&(d.net_pnl_usdc<0)).sum()),
        tp1_reached=int(d.tp1_reached.sum()),tp2_reached=int(d.tp2_reached.sum()))
    dump(out/'aggregate_metrics.json',m)
    correlations=[]
    for name in names:
        for outcome in ['gross_pnl_usdc','net_pnl_usdc']:
            for mode in ['raw','month_demeaned']:
                a=d[[name,outcome,'month']].dropna().copy()
                if mode=='month_demeaned':
                    a[name]-=a.groupby('month')[name].transform('mean');a[outcome]-=a.groupby('month')[outcome].transform('mean')
                rho=spearmanr(a[name],a[outcome]).statistic if a[name].nunique()>1 else np.nan
                r=a[name].corr(a[outcome])
                correlations.append(dict(feature=name,outcome=outcome,mode=mode,N=len(a),spearman=rho,pearson_r2=r*r))
    pd.DataFrame(correlations).to_csv(out/'associations.csv',index=False)
    # Transparent post-hoc list; exact/redundant copies not presented as separate discoveries.
    eligible=comparisons['gross'].query('coverage >= .8 and winner_N >= 20 and loser_N >= 20')
    selected=[]
    for name in eligible.feature:
        if all(abs(d[name].corr(d[other],method='spearman'))<.9 for other in selected):selected.append(name)
        if len(selected)==5:break
    little=[]
    for name in eligible.sort_values('abs_effect').feature:
        if all(abs(d[name].corr(d[other],method='spearman'))<.9 for other in little):little.append(name)
        if len(little)==5:break
    contrasts=[]
    for name in names:
        if name not in bins:continue
        q=bins[name];lo=d[q==q.min()];hi=d[q==q.max()]
        months=[]
        for month,g in d.groupby('month'):
            aa=g[q.loc[g.index]==q.max()];bb=g[q.loc[g.index]==q.min()]
            if len(aa) and len(bb):months.append(dict(month=month,N_low=len(bb),N_high=len(aa),gross_difference=float(aa.gross_pnl_usdc.mean()-bb.gross_pnl_usdc.mean()),net_difference=float(aa.net_pnl_usdc.mean()-bb.net_pnl_usdc.mean())))
        contrasts.append(dict(feature=name,N_low=len(lo),N_high=len(hi),gross_difference=float(hi.gross_pnl_usdc.mean()-lo.gross_pnl_usdc.mean()),net_difference=float(hi.net_pnl_usdc.mean()-lo.net_pnl_usdc.mean()),months=months))
    dump(out/'quartile_contrasts.json',contrasts)
    dump(out/'ranked_findings.json',dict(ranking='post-hoc gross rank-biserial; correlated copies suppressed at abs Spearman >= .9 for display only',top=selected,little=little))
    print(json.dumps(dict(metrics=m,top=selected,little=little),indent=2),flush=True)

if __name__=='__main__':run()
