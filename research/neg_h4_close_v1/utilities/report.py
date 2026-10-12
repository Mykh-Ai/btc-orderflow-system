"""Generate the Ukrainian report from persisted, verified experiment ledgers."""
from pathlib import Path
import json
import pandas as pd
HERE=Path(__file__).resolve().parents[1];out=HERE/'results'
assert json.loads((out/'verification.json').read_text())['passed']
a=pd.read_csv(out/'aggregate_metrics.csv');b=pd.read_csv(out/'breakdown_metrics.csv')
f=json.loads((out/'funnel.json').read_text());p=json.loads((HERE/'baseline_parity/result.json').read_text())
def val(v):
    if pd.isna(v):return '—'
    if isinstance(v,float):return f'{v:.2f}'
    return str(v)
def table(frame,cols):
    return '| '+' | '.join(cols)+' |\n| '+' | '.join(['---']*len(cols))+' |\n'+'\n'.join('| '+' | '.join(val(r[c]) for c in cols)+' |' for r in frame.to_dict('records'))+'\n'
columns=['experiment','opportunities','N','wins','losses','win_rate_pct','gross','commission','slippage','net','net_per_trade','PF']
parts=['# NEG_H4_CLOSE_V1 — результат дослідження\n',
'''**Висновок: перевага після витрат не підтверджена.** H4-close дає 128 незалежних угод: gross +72.49, net −566.00 USDC, PF 0.766. Спільний портфель: 80 відкритих/закритих, 39 прибуткових, 41 збиткова, gross +93.18, net −305.30, PF 0.798; 48 заблокованих. Незавершених позицій немає.

Очікуване поліпшення саме на H4_SWING_HIGH не підтвердилося: незалежно 64 угоди, gross −130.43, net −449.77; портфель 41 угода, gross −82.67, net −286.99. Навіть портфельний win rate 51.22% тут не означає прибутковості. H1_SWING_HIGH виявився менш збитковим: портфель 39 угод, net −18.31, але PF 0.972 усе ще нижче 1.

## Що саме перевірено

Числова NEG delta < 0 з того самого raw журналу → та сама значуща верхня H1/H4 зона → заморожені межі → перше повне канонічне закриття H4 строго нижче lower в межах чотирьох годин від першої NEG → лише SHORT. H4 UTC 00/04/08/12/16/20, використана наявна агрегація Monitor; 240 завершених валідних хвилин. Жодного фільтра >120 хвилин, нового порога чи обмеження тільки H4-рівнями.

Stop — candidate_sweep, максимум до підтвердження, buffer 0.0001; 3000 USDC, комісія 0.000744 за оборот, slippage 0/1/2 bps, TP1=1R, TP2=2R, третини, BE, trailing, stop-first і concurrency збережені. Ціна/структура з legacy Spot, виконання BTCUSDC Spot. Період рішень 20.03–17.08.2026, outcomes до 19.08; warm-up з початку джерела. Ліквідації недоступні, не підмінені нулем.

## Baseline parity

Відтворено всі 516 повних записів кандидатів, із них 515 у вікні рішень; 2846 статусів seeds. Повторно програно старий replay; перевірено фінансові та часові поля кожної угоди й усі задані підсумки (толеранс агрегатів 1e−7 USDC, ledger 1e−9). Результат: **PASS**.
''']
pr=[]
for name,m in p['metrics'].items():pr.append(dict(cohort=name,N=m['closed'],wins=m['net_wins'],losses=m['closed']-m['net_wins'],gross=m['gross_usdc'],net=m['net_usdc']))
parts.append(table(pd.DataFrame(pr),['cohort','N','wins','losses','gross','net']))
parts.append('Портфель baseline: 289 заблокованих. Файли `baseline_parity/result.json` і повторно отримані ledgers.\n')
parts.append('''## Важлива різниця двох H1-порівнянь

`NEG_H1_BASELINE` — саме запитані історичні NEG: 164 незалежні можливості й 75 відкритих угод як внесок у **спільний all-signs** процес. POS там можуть раніше зайняти pending-зону, підтвердження або портфель.

`NEG_H1_CONTROL` — додатковий контроль **тільки NEG**, з тими самими новими admission/dedup і портфелем, але H1-підтвердженням. Він має 262 можливості. Усі його сигнали, стопи та статуси точно збіглися з незміненим старим H1 engine, запущеним на NEG-only seeds. Порівняння CONTROL ↔ H4 ізолює таймфрейм; BASELINE ↔ H4 також включає прямо замовлене вилучення POS із володіння кандидатами. Ці вибірки не підміняються одна одною.

## 1. Funnel

Raw/armed/status counts включають весь журнал із warm-up; торгове вікно застосовано однаково після підтвердження. У H1 control один із 263 кандидатів поза вікном; у H4 усі 128 у вікні.
''')
fr=[]
for label,values in f.items():
    for key,value in values.items():
        if key!='statuses':fr.append(dict(experiment=label,stage=key,count=value))
parts.append(table(pd.DataFrame(fr),['experiment','stage','count']))
parts.append('H4: додатково 25 DUPLICATE_CONFIRMATION і 3 CANCELLED_FEED_GAP; H1 control: 46 і 3 відповідно. Повні статуси — `results/funnel.json`. 445 H4-кандидатів завершилися EXPIRED. Deadline не продовжувався.\n')
for mode,name in [('independent','Незалежні можливості'),('portfolio','Спільний портфель')]:
    parts.append('## 2. '+name+' — загальний результат та пряме порівняння\n\nУсі суми — USDC; wins/losses і PF визначено за net після витрат. N — закриті угоди, а не raw seeds.\n')
    parts.append(table(a[a['mode']==mode],columns))
    parts.append('## 3. '+name+' — структурні рівні та H1/H4-підтвердження\n')
    parts.append(table(b[(b['mode']==mode)&(b.dimension=='level_type')],['experiment','cohort','N','wins','losses','win_rate_pct','gross','net','net_per_trade','PF']))
    parts.append('## 4. '+name+' — delta → confirmation, лише діагностика H4\n')
    parts.append(table(b[(b['mode']==mode)&(b.dimension=='timing_bucket')&(b.experiment=='NEG_H4_CLOSE_V1')],['cohort','N','wins','losses','win_rate_pct','gross','net','net_per_trade','PF']))
    parts.append('## 5. '+name+' — місячні результати H4\n')
    parts.append(table(b[(b['mode']==mode)&(b.dimension=='month')&(b.experiment=='NEG_H4_CLOSE_V1')],['cohort','N','wins','losses','gross','commission','slippage','net','net_per_trade','PF']))
    parts.append('## 6. '+name+' — концентрація за рівнем і місяцем\n')
    parts.append(table(b[(b['mode']==mode)&(b.dimension=='level_month')&(b.experiment=='NEG_H4_CLOSE_V1')],['cohort','N','gross','net','PF']))
parts.append('''## Інтерпретація

- Проти історичного NEG H1 independent результат **погіршився**: net/trade −2.78 → −4.42, gross/trade +2.21 → +0.57, PF 0.811 → 0.766. Win rate зріс 42.07% → 43.75%, але це не перевага.
- Проти matched NEG-only H1 control незалежна expectancy практично не поліпшилася: gross/trade +0.592 → +0.566; net/trade −4.398 → −4.422. Скорочення сумарного збитку значною мірою пов'язане зі зменшенням числа угод 262 → 128 (−51.15%).
- Портфель проти matched control справді покращився: net/trade −7.87 → −3.82, PF 0.543 → 0.798, gross/trade −2.87 → +1.16. Але середні витрати H4 близько 4.98 USDC/угоду перекривають gross; позитивної net expectancy немає.
- На H4_SWING_HIGH незалежна expectancy проти matched H1 control стала гіршою: gross/trade +0.76 → −2.04; net/trade −4.23 → −7.03; PF 0.744 → 0.657. Поліпшення не концентрується тут як позитивний результат. На H1_SWING_HIGH gross/trade незалежно зріс +0.41 → +3.17, але net залишився −1.82.
- Портфель H4 має лише три плюсові місяці: березень +10.78, травень +197.29, липень +51.17. Травень дає приблизно 76.1% суми позитивних місячних результатів. Квітень −424.81 домінує у збитках; без травня net був би −502.59. Це нестійкий місячний профіль, не рівномірний результат.
- Незалежний H4 має плюсові березень, травень і червень, але квітень −680.01 перекриває їх. Місячна концентрація окремо для H1/H4-рівнів наведена вище; нульові cohort-місяці не приховані.
- 64 незалежні можливості на кожен тип рівня; у портфелі лише 39 H1 і 41 H4. Місячні підгрупи ще менші. Такої in-sample вибірки недостатньо для висновку про стійку перевагу, навіть якби підсумок був плюсовим. Усі ці місяці вже досліджувалися; нового holdout немає.
- Від matched H1 control втрачено 144 owner-seed можливості, збережено 118, з'явилося 10 з іншими власниками/епізодами після зміни часу підтвердження. Нетто −134. Це не просто фільтр на старих угодах. Повні ID у `opportunity_comparison.json`.

**Відповідь A:** H4 покращив окремі портфельні показники, але не дав прибутковості, а незалежну expectancy проти matched H1 не покращив. **Відповідь B:** підтвердження переваги саме H4_SWING_HIGH немає; ця когорта має негативний gross і net.

## Перевірки та обмеження

162 тести пройдено: 129 research/replay, 26 native Monitor, 7 corrected all-signs. Додатково runtime-перевірки input/code hashes, сигналів/стопів H1 control, frozen-zone меж і доступності, H4 UTC boundary, strict close, horizon, NEG/SHORT, entry після confirmation, рівності gross − costs = net, відсутності перекриття портфеля. `results/verification.json` — PASS.

Використаний той самий обмежений structural adapter, а не повний Monitor v39A: індивідуальні H1/H4 upper references з native score/lifecycle. Legacy Open синтезований початковим нормалізатором; джерела не змінювалися. Немає borrow interest, реальної книги ордерів чи моделі часткових виконань. Незалежні можливості можуть перекриватися; їхній PnL не є доходом одного рахунку. Жодної production-рекомендації з цього in-sample тесту.

## Артефакти

- `PROTOCOL.md`, `EVIDENCE_AUDIT.md`, `evidence/` — контракт, фактичні команди й тести.
- `baseline_parity/result.json` та baseline ledgers — відтворений gate.
- `results/config.json`, `protocol_freeze.json`, `input_hashes.csv`, `query_cache_hashes.csv` — заморожені параметри та hashes.
- `results/NEG_H4_CLOSE_V1/` і `results/NEG_H1_CONTROL/`: seed audit, candidate events, кандидати CSV/JSON, structural mapping, independent/portfolio ledgers, execution/portfolio events, blocked opportunities, zone-selection audit.
- `results/aggregate_metrics.csv`/`.json`, `structural_metrics.csv`, `monthly_metrics.csv`, `timing_metrics.csv`, `breakdown_metrics.csv`, `funnel.json`, `opportunity_comparison.json`, `verification.json`.
- CSV понад 500 KB публікуються як `.csv.gz` без втрат; `artifact_manifest.json` містить початкові й збережені SHA-256. Pandas читає gzip напряму.

Production, Executor, DeltaScout, historical source data та replay execution modules не змінені. Доставка цього дослідження лише в isolated canonical research branch.
''')
(HERE/'REPORT_UA.md').write_text('\n'.join(parts))
print('Report generated from verified metrics')
