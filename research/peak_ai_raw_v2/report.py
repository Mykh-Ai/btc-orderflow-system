"""Build an evidence-backed Ukrainian report, never change selection or rules."""
import hashlib,json
from pathlib import Path
import pandas as pd
from research.peak_ai_raw_v2.metrics import RESOLVED

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'
LABELS={'immediate_follow':'Одразу за дельтою','immediate_fade':'Одразу проти дельти',
        'break_follow':'Після підтвердження продовження','break_reverse':'Після підтвердження розвороту'}
CTX={'all':'без додаткової умови','activity':'підвищений обсяг','resistance':'ціна опирається дельті','trend':'попередній рух за напрямком входу'}
PERIODS={'development':'20.03–29.05','validation':'01.06–28.06','historical_retest':'01.07–17.08'}

def read(p):return json.loads(p.read_text())
def num(x):return '—' if x is None else f'{x:,.2f}'.replace(',',' ')
def label(f):
    mode,context=f.split('__');return LABELS[mode]+'; '+CTX[context]
def table(records):
    lines=['| Правило / ділянка | Кандидати | Закриті | Незавершені | Нетто, USDC | PF | Просадка, USDC | Помилки |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for title,m in records:
        p=m['portfolio'];lines.append(f"| {title} | {p['candidates']} | {p['closed']} | {p['unresolved']} | {num(p['net_usdc'])} | {num(p['profit_factor'])} | {num(p['max_closed_equity_drawdown_usdc'])} | {m['integrity_errors']} |")
    return '\n'.join(lines)

def main():
    manifest=read(OUT/'manifest.json');short=read(OUT/'shortlist.json');choice=read(OUT/'selection.json')
    all_metrics={p:read(OUT/f'{p}_base/metrics.json') for p in PERIODS}
    chosen=choice['selected'];p=all_metrics['historical_retest'][chosen]['portfolio']
    verification=[];comparison=[]
    for directory in sorted(OUT.iterdir()):
        if not directory.is_dir() or not (directory/'metrics.json').exists():continue
        for family,m in read(directory/'metrics.json').items():
            for mode in ('independent','portfolio'):
                path=directory/f'{family}_{mode}.csv';df=pd.read_csv(path)
                closed=df[(df.entry_status=='FILLED') & df.lifecycle_class.isin(RESOLVED)]
                s=m[mode]
                assert len(closed)==s['closed'],path
                for field in ('net_pnl_usdc','gross_pnl_usdc','commission_usdc','slippage_usdc'):
                    target={'net_pnl_usdc':'net_usdc','gross_pnl_usdc':'gross_usdc'}.get(field,field)
                    assert abs(closed[field].sum()-s[target])<1e-6,(path,field)
                assert len(df)==s['candidates'],path
                verification.append({'run':directory.name,'family':family,'mode':mode,'rows':len(df),'closed':len(closed),'checked':True})
            comparison.append({'run':directory.name,'family':family,**{k:v for k,v in m['portfolio'].items() if not isinstance(v,(dict,list))},'integrity_errors':m['integrity_errors']})
    pd.DataFrame(comparison).to_csv(OUT/'comparison.csv',index=False)
    (OUT/'verification.json').write_text(json.dumps({'ledger_checks':verification,'all_passed':True},indent=2)+'\n')
    candidates=pd.read_csv(OUT/'candidates.csv')
    for s in candidates.shadow_flags:
        import ast
        flags=ast.literal_eval(s)
        assert flags['seed_ts']<=flags['decision_ts']
    result_eligible=choice['eligible'] and p['closed']>=10 and p['net_usdc']>0 and (p['profit_factor'] or 0)>=1.1 and all_metrics['historical_retest'][chosen]['integrity_errors']==0
    conclusion=('Є історичний кандидат для подальшої незалежної перевірки. Це ще не підтверджена перевага для реальної торгівлі.' if result_eligible
                else 'Стійку прибуткову точку входу цим набором правил не підтверджено. Відібраний варіант є діагностичним; до реальної торгівлі не допущений.')
    tests=read(OUT/'test_verification.json') if (OUT/'test_verification.json').exists() else {'summary':'див. журнал pytest'}
    sensitivity={k:read(OUT/f'historical_retest_{k}/metrics.json')[chosen]['portfolio'] for k in ('double_slippage','target_first')}
    audit=pd.read_csv(OUT/'seed_audit.csv')
    monthly=audit.assign(month=audit.ts.str[:7]).groupby(['month','event']).size().unstack(fill_value=0)
    month_lines=['| Місяць UTC | DELTA_MAX | DELTA_MIN |','|---|---:|---:|']
    for month,r in monthly.iterrows():month_lines.append(f"| {month} | {r.get('DELTA_MAX',0)} | {r.get('DELTA_MIN',0)} |")
    text=f'''# Peak_Ai raw v2 — незалежний пошук входу

{conclusion}

## Що саме перевірено

Вхідні події: **{manifest['raw_seeds']} екстремумів**, DELTA_MAX — {manifest['seed_types']['DELTA_MAX']}, DELTA_MIN — {manifest['seed_types']['DELTA_MIN']}.
Архів: 17 березня–18 серпня 2026 за локальними датами файлів. Події не відбирались за допуском PEAK.
Усі {manifest['seed_status'].get('USABLE',0)} отримали придатний контекст. Відбір за датами дослідження
та конкретними умовами входу відбувається після цього; він не дорівнює числу всіх подій.

Виправлена помилка зіставлення джерел: DeltaScout у цьому журналі працював від BTCUSDT **Spot**,
а effective_feed SHI — BTCUSDT **Futures**. Усі журнальні дельти та обсяги збігаються зі Spot
за тією самою хвилиною UTC: максимальна різниця через округлення {manifest['max_delta_error']:.6f} BTC для дельти
і {manifest['max_volume_error']:.6f} BTC для обсягу. Додатковий часовий зсув не застосовано.
Futures, PEAK_EMIT, A/B та рішення воріт не використовувалися ні для сигналу, ні як критерій відбору.

{chr(10).join(month_lines)}

Місячний підрахунок тут за UTC, тому біля межі місяця відрізняється від підрахунку за локальною датою файлу.

## Власні правила входу

За дельтою: MAX → LONG, MIN → SHORT. Проти дельти: MAX → SHORT, MIN → LONG.
Негайний сигнал приймається на закритті хвилини екстремуму; виконання моделюється тільки після сигналу.
Для продовження чекаємо до 10 хвилин на перше закриття вище High MAX-свічки або нижче Low MIN-свічки.
Для розвороту — нижче Low MAX-свічки або вище High MIN-свічки. Торкання рівня без закриття не достатньо.

Кожен із чотирьох способів перевірений у чотирьох варіантах: без додаткової умови;
обсяг щонайменше вдвічі більший за медіану попередніх 60 хвилин;
закриття екстремальної свічки у половині діапазону проти дельти;
рух за попередні 60 хвилин у напрямку запланованої угоди.
Це **16 заздалегідь зафіксованих правил**, а не повний перебір усіх можливих закономірностей.
Ціна сигналу — фактичний Close хвилини рішення, а не бажана ціна всередині вже завершеної свічки.

## Результати навчальної ділянки

Для кожного способу входу обрано один контекст за зафіксованим правилом ранжування;
успішність вимагає щонайменше 25 закритих угод, додатного нетто, PF ≥1,10 та відсутності помилок цілісності.

{table([(label(f),m) for f,m in all_metrics['development'].items()])}

## Перевірка чотирьох зафіксованих варіантів у червні

Короткий список зафіксований {short['frozen_at_utc']}; наступні результати не змінюють його правила.
У червні потрібно ≥10 закритих угод, додатне нетто, PF ≥1,10 та відсутність помилок цілісності.

{table([(label(f),m) for f,m in all_metrics['validation'].items()])}

## Відібраний варіант: {chosen}

**{label(chosen)}.** Допуск за навчанням і червнем: **{choice['eligible']}**.
Вибір зафіксовано {choice['frozen_at_utc']} до розрахунку результату цього варіанта на липні–серпні.

{table([(PERIODS[period],all_metrics[period][chosen]) for period in PERIODS])}

На липні–серпні: валовий результат {num(p['gross_usdc'])} USDC,
комісії {num(p['commission_usdc'])}, прослизання {num(p['slippage_usdc'])}, нетто **{num(p['net_usdc'])} USDC**.
Прибуткових закритих угод: {p['net_wins']} / {p['closed']}; TP1: {p['tp1_hits']}, TP2: {p['tp2_hits']}.
LONG: {p['by_side']['LONG']['n']} закритих, нетто {num(p['by_side']['LONG']['net'])};
SHORT: {p['by_side']['SHORT']['n']} закритих, нетто {num(p['by_side']['SHORT']['net'])}.
Заблоковані/непридатні входи: `{json.dumps(p['blocked_reasons'],ensure_ascii=False)}`.

Подвоєне прослизання: **{num(sensitivity['double_slippage']['net_usdc'])} USDC**.
TP перед SL при неоднозначності однієї свічки: **{num(sensitivity['target_first']['net_usdc'])} USDC**.
Орієнтовний 95% інтервал нетто за 7-денним блоковим bootstrap:
{num(p['weekly_block_bootstrap_net_95pct'][0])}…{num(p['weekly_block_bootstrap_net_95pct'][1])} USDC.
Цей інтервал не коригує множинний перебір стратегій і не є доказом майбутньої прибутковості.

## Межі висновку та відтворюваність

- Це **повторне історичне дослідження**, не свіжий untouched holdout: попередній експеримент уже розглядав цей період.
- Вересень не включено. Для нього потрібна окрема узгоджена підготовка пізніших джерел.
- У таблицях — змодельовані закриті угоди портфеля з однією позицією, не фактичні біржові виконання.
- Номінал кожної угоди 3000 USDC, комісії та прослизання враховано, відсотки за позикою — ні.
- Правила SL/TP/BE/trailing існуючого бектестера залишені незмінними. Перевірялись нові входи в межах цієї моделі виходу.
- Кожна ділянка починається без позиції; після останнього дня сигналів є два дні для завершення.
  Незавершені позиції не зараховано як нульовий прибуток і не закрито штучно.
- Просадка по закритих угодах, не переоцінка рахунку щохвилини. Немає моделі книги ордерів та часткових виконань.
- Legacy Open відновлений із попереднього Close; High/Low нормалізатор розширив до нього. Це обмежує точність рівнів.
- {manifest['signal_gaps']} розриви часової послідовності legacy feed; очікування сигналу через розрив скасовується.
- Помилки бектестера записані окремо та дискваліфікують сімейство; для них PnL не вигадувався.
- Один останній навчальний підсумок не зберігся у зведеному JSON після завершення процесу.
  Його відновлено з повних журналів угод; решту 15 підсумків незалежно перераховано та звірено
  з точністю 1e-7. Угоди і правила не змінювались; запис є у summary_reconciliation.json.
- Перевірки: {tests['summary']}; звірка кожного журналу з підсумками пройшла.

Код, незмінний протокол, повний аудит подій, 16 навчальних результатів, наступні перевірки,
журнали угод та контрольні суми входять до пакета. Робочий бот, сервер і файли production не змінені.
'''
    (HERE/'Peak_Ai_raw_v2_Report_UA.md').write_text(text)
    print({'chosen':chosen,'passed_historical_gates':result_eligible,'ledger_checks':len(verification),'report':str(HERE/'Peak_Ai_raw_v2_Report_UA.md')})

if __name__=='__main__':main()
