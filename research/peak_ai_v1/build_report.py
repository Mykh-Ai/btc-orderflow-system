from pathlib import Path
import json,hashlib,platform,subprocess
import pandas as pd
import numpy as np
R=Path(__file__).resolve().parent;O=R/'results'
M={s:json.loads((O/f'{s}_base/metrics.json').read_text()) for s in ('development','validation','holdout')}
choice=json.loads((O/'frozen_selection.json').read_text());f=choice['selected'];h=M['holdout'][f]['portfolio']
S={k:json.loads((O/f'holdout_{k}/metrics.json').read_text()) for k in ('target_first','double_slippage')}
rows=[]
for split,m in M.items():
 for family,views in m.items():
  for view,s in views.items():
   rows.append(dict(split=split,family=family,view=view,**{k:v for k,v in s.items() if not isinstance(v,(dict,list))}))
pd.DataFrame(rows).to_csv(O/'comparison.csv',index=False)
fmt=lambda x:f'{x:,.2f}'
table='| Варіант | Березень–травень: угоди / net USDC | Червень: угоди / net USDC |\n|---|---:|---:|\n'
labels={'continuation_15':'Продовження, дельта ≥15%','continuation_30':'Продовження, дельта ≥30%',
'pullback_15':'Відкат, дельта ≥15%','pullback_30':'Відкат, дельта ≥30%',
'failed_extreme_15':'Невдалий пробій, дельта ≥15%','failed_extreme_30':'Невдалий пробій, дельта ≥30%',
'PEAK_ARCHIVED':'Архівний PEAK','PEAK_ARCHIVED_AB':'Архівний PEAK + повторний A/B'}
for family in labels:
 a=M['development'][family]['portfolio'];b=M['validation'][family]['portfolio']
 table+=f"| {labels[family]} | {a['closed']} / {fmt(a['net_usdc'])} | {b['closed']} / {fmt(b['net_usdc'])} |\n"
hold='| Сигнал | Кандидати | Закриті угоди | Net USDC | Profit factor | Просадка USDC |\n|---|---:|---:|---:|---:|---:|\n'
for family in (f,'PEAK_ARCHIVED','PEAK_ARCHIVED_AB'):
 a=M['holdout'][family]['portfolio']
 hold+=f"| {labels[family]} | {a['candidates']} | {a['closed']} | {fmt(a['net_usdc'])} | {a['profit_factor']:.2f} | {fmt(a['max_closed_equity_drawdown_usdc'])} |\n"
# Entry intervals and overlap with archived admitted PEAK.
c=pd.read_csv(O/'candidates.csv');c=c[c.family==f];c.signal_ts_utc=pd.to_datetime(c.signal_ts_utc,utc=True)
p=pd.read_csv(O/'holdout_base'/f'{f}_portfolio.csv');p=p[p.entry_status=='FILLED']
durations=(pd.to_datetime(p.exit_ts,utc=True)-pd.to_datetime(p.entry_fill_ts,utc=True)).dt.total_seconds()/3600
baseline=pd.read_csv(O/'candidates.csv');baseline=baseline[baseline.family=='PEAK_ARCHIVED'];keys=set(zip(baseline.signal_ts_utc,baseline.side))
holdc=c[(c.signal_ts_utc>=pd.Timestamp('2026-07-01',tz='UTC'))&(c.signal_ts_utc<pd.Timestamp('2026-08-18',tz='UTC'))]
overlap=sum((x.isoformat(),s) in keys for x,s in zip(holdc.signal_ts_utc,holdc.side))
report=f'''# Peak_Ai v1 — власна родина сигналів і фактичний бектест

Дата дослідження: 9 жовтня 2026. **Рішення: NO-MERGE / НЕ ВПРОВАДЖУВАТИ В ТОРГІВЛЮ.**

Розроблено окремий причинний детектор із feed та виконано бектести на штатному Scout Replay. Це детерміновані правила, запропоновані й перевірені асистентом; назва Peak_Ai не означає виклик LLM на кожній хвилині або навчання нейромережі. Перевірено шість наперед визначених варіантів. Прибуткової стабільної переваги на відкладеному відрізку не знайдено. Глобально оптимальні входи не встановлені.

## Що саме відрізняється від DeltaScout

DeltaScout фіксує нову крайню дельту, потім порівнює поточні ціну, обсяг і VWAP з попереднім піком та застосовує ворота. Peak_Ai не потребує попереднього PEAK або його проходження через ворота: він сам переглядає завершені хвилинні бари feed.

Дельта D = BuyQty − SellQty. Новий екстремум — D вище максимуму попередніх 180 хвилин при D>0 або нижче мінімуму при D<0. Попереднє вікно не включає поточну хвилину. Модуль вимагає 180 послідовних несинтетичних барів із позитивним обсягом і діапазоном; розрив або синтетичний бар скидає накопичення. Мінімальна сила — |D|/Volume ≥15% або ≥30%. Це відношення дельти до обсягу, а не частка покупців чи значення чинного IMB.

Три механізми входу:

1. **Продовження.** Екстремальна дельта пробиває попередній 20-хвилинний high/low закриттям; закриття в останніх 30% бару за напрямком; сумарна дельта попередніх 60 хвилин підтримує напрямок.
2. **Відкат після імпульсу.** Той самий імпульс, потім до 10 хвилин очікування. Ціна відступає щонайменше на 25% діапазону імпульсного бару, але закриття не порушує його середину. Лише після вже зафіксованого відкату новий бар пробиває high/low попереднього закриттям і має дельту за напрямком. Один вхід на seed; поточний бар не може одночасно створити й підтвердити відкат.
3. **Невдалий пробій / розворот.** Екстремальна дельта виходить за попередній 20-хвилинний рівень, проте закриття повертається всередину й лежить у протилежній половині бару. Наприклад, агресивні покупки пробили high, але бар закрився нижче старого high і в нижній половині: кандидат SHORT. Для LONG — симетрично.

Фінальний дослідницький кандидат: **Peak_Ai failed_extreme_30**. Його сигнал виникає після закриття бару, а виконання можливе лише на наступних барах. Відсутність реакції на агресивний обсяг тут — гіпотеза невдалого пробою, а не доведене біржове поглинання: ордербука немає.

## Дані, виконання і чесність перевірки

Використано гілку codex/scout-replay-backtester-v0-1, immutable SHA `84fcb9ec257dd2c28b04ff6149b48b52d628fdca`. Обидва вхідні архіви агента пройшли SHA-256 перевірку. Завантажено 222883 бари сигнального feed і 221760 барів офіційного BTCUSDC Spot. Feed містить 19067 відновлених price/volume/OI рядків, 203791 REAL_ENRICHED і 25 SYNTHETIC_UNTRUSTED; є 23 часові розриви. Сигнали не використовують синтетичні бари або неповний 180-хвилинний контекст. Офіційний execution-feed суцільний. Для ділянки квітень–травень використано effective_feed та recovery sidecars, а не первинні пошкоджені рядки.

Сигнал — BTCUSDT Futures. Угоди — BTCUSDC Spot. Історичний conversion proxy й час доступності ціни обробляє наявний бектестер. Використано чинний офлайн контракт виходів: структурний SL за підтвердженим swing 24 год/LR25, буфер 50, обмеження відстані 1200; TP1/TP2 частинами, BE, trailing 240/LR25, буфер 50, крок 25, підтвердження 20. Одна позиція, cooldown 180 секунд. Для всіх сімейств однакові виходи.

Модель входу — LIMIT_THEN_MARKET_90S_GUARDED_V0_1: хвилинний proxy 90 секунд із перевіркою відхилення 0.25R та забороною наздоганяти за TP1. Це не точне відтворення bid/ask, черги або часткових виконань. У разі неоднозначного торкання SL/TP в одному барі базова модель обирає SL першим.

Номінал **3000 USDC на позицію** — база розрахунку, не рекомендація капіталу. Комісія **0.0744% від кожного обороту**, прослизання entry/звичайний вихід/stop = 0/1/2 bps. Net наведено після цих витрат, **до відсотків за позикою**. Немає фінансування, кредитного плеча чи реальних ордерів. Просадка — за закритими угодами, не внутрішньоугодна переоцінка рахунку.

Дослідницький протокол записаний перед першим розрахунком outcomes:

- Розробка: сигнали 20.03–29.05; закриття до 31.05.
- Вибір: сигнали 01.06–28.06; закриття до 30.06.
- Відкладена перевірка: сигнали 01.07–17.08; закриття до 19.08.

Кожен відрізок починається без позиції. Два останні дні відведено на закриття; незакриті угоди позначені окремо. Майбутні outcomes одного відрізка не потрапляють у відбір для попереднього. Вибір зафіксовано у frozen_selection.json до запуску holdout. Після перегляду holdout правила сигналів не змінені. Ці історичні дані могли використовуватися у попередніх дослідженнях проєкту: це відкладена перевірка в межах цього запуску, а не абсолютно нові майбутні ринкові дані.

## Результати пошуку до фінальної перевірки

{table}

Числа — закриті угоди портфеля та сума net. У continuation на development залишилася одна незакрита позиція в кожному варіанті; її частковий результат не змішано з закритими. Вимоги відбору: щонайменше 20 development і 10 validation закритих угод, net>0 і PF≥1.05 в обох відрізках. **Жоден варіант не пройшов.** failed_extreme_30 мав найкращий мінімальний PF двох відрізків, тому за протоколом обраний лише для негативної/діагностичної перевірки.

Не можна об'єднати development і validation, побачити плюс і оголосити успіх: вимога стабільності на кожному відрізку провалена.

## Відкладена перевірка — липень–серпень

{hold}

Для Peak_Ai: 31 кандидат, 19 закритих угод, 11 блокувань зайнятою позицією й одна відмова через відсутність підтвердженого swing для SL. Незакритих позицій немає. {h['net_wins']}/19 угод позитивні після витрат; {h['tp1_hits']}/19 досягли TP1; {h['tp2_hits']}/19 досягли TP2. Середній net = {fmt(h['mean_net_usdc'])} USDC/угоду. Медіанний час утримання — {durations.median():.1f} години; це не скальпінг.

Розклад результату: **gross +{fmt(h['gross_usdc'])}; комісії −{fmt(h['commission_usdc'])}; прослизання −{fmt(h['slippage_usdc'])}; net {fmt(h['net_usdc'])} USDC**. Отже, позитивний рух ціни до витрат тут недостатній для прибуткової торгівлі. TP1 або перенесення SL у BE не гарантує позитивний net.

Незалежні можливості без позиційного ліміту: {M['holdout'][f]['independent']['closed']} закритих, net {fmt(M['holdout'][f]['independent']['net_usdc'])} USDC. Це окрема діагностика, а не досяжний результат одно-позиційного бота. Відповідність нових кандидатів архівним PEAK за тим самим часом і напрямком: {overlap}/31; сімейство справді окреме.

Архівний PEAK порівнюється лише на тих історичних допусках, що є в журналі; його параметри змінювалися з часом. Другий baseline повторно застосовує A/B до вже допущених архівних PEAK. Це **не повний detector replay актуальної версії DeltaScout**. У holdout 5 угод baseline проти 19 Peak_Ai — замало для твердження про статистичну перевагу, а просадка Peak_Ai вища. Менший абсолютний збиток не означає кращу стратегію.

## Стійкість і невизначеність

- Target-first sensitivity: net {fmt(S['target_first'][f]['portfolio']['net_usdc'])}; у закритих holdout-угодах Peak_Ai немає одночасного SL/TP зі зміною результату.
- Подвоєне прослизання: net {fmt(S['double_slippage'][f]['portfolio']['net_usdc'])} USDC.
- Дослідницький 95% інтервал суми net при 7-денному блоковому bootstrap: {fmt(h['weekly_block_bootstrap_net_95pct'][0])}…{fmt(h['weekly_block_bootstrap_net_95pct'][1])} USDC. Він охоплює нуль і не є доказом переваги; вибірка мала, перебрано шість варіантів.
- SHORT дав плюс на development і validation, але −94.21 USDC у holdout; LONG був збитковим на development, але +45.11 USDC у holdout. Це нестабільність за часом; відкинути SHORT після перегляду holdout означало б підгонку. Такої зміни не зроблено.
- В архівному baseline development одна явна помилка INITIAL_STOP_WRONG_SIDE_AFTER_FILL (04.05 10:08 UTC). Вона записана в integrity_errors.json і рядок INVALID, а не перетворена на виграш чи звичайний стоп. Результати baseline development — діагностичні з цим обмеженням. Peak_Ai та holdout не мають таких помилок.
- Бектестер зберігає захисні виходи при відсутності придатної reference-хвилини для оновлення trailing; не гарантує тикову або live-паритетність. Якість початкового сигналу й придатність усього майбутнього шляху — різні речі.

## Що встановлено

У перевірених правилах нова екстремальна дельта з пробоєм сама по собі часто дає невдале продовження. Додавання короткого відкату не забезпечило стабільного покращення. Невдалий пробій — найбільш перспективна з трьох перевірених **гіпотез**, але чинний варіант не покриває торгові витрати й не пройшов критерій стабільності.

**Рішення: Peak_Ai v1 залишити дослідницьким сімейством; у production не вносити, не об'єднувати з чинним PEAK, сервер не перезапускати.** Наступна версія повинна отримати новий протокол і новий недоторканий період, якщо змінюватимуться контекст чи виходи. Цей holdout більше не можна називати новим тестом для правил, підібраних за його результатами.

## Перевірки та відтворення

Виконано **92 тести: 86 існуючих + 6 Peak_Ai**. Власні тести перевіряють незмінність сигналів при додаванні майбутніх барів, розриви й синтетику, напрямок розвороту, заборону підтвердження відкату тим самим баром, симетрію LONG/SHORT та скасування очікування після порушення середини seed. Контрольний CLI-прогін агента за 20–22 березня завершився успішно. Синтаксична компіляція пройшла. git diff для всіх існуючих tracked-файлів порожній; зміни лише в новій research/peak_ai_v1. Комітів, push, merge чи deploy у цьому запуску не було.

Код: signals.py, run.py. Правила й audit: AUDIT_AND_PROTOCOL.md. Інструкція: README.md. Повні кандидати, незалежні та портфельні ledgers, помилки, вибір до holdout й hashes — у results/. comparison.csv містить машинозчитуване зіставлення. SHA256SUMS.txt перевіряє вміст доставленого пакета. prepared.pkl не включений; він відновлюється командою prepare з наданих агентом архівів.
'''
(R/'Peak_Ai_Report_UA.md').write_text(report,encoding='utf-8')
dump={'tests':'92 passed','smoke':'peak_ai_handoff_smoke_20261009 completed','production_diff':subprocess.check_output(['git','diff','--stat'],text=True).strip(),
      'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
      'final_code_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in R.glob('*.py')},
      'signal_hash_matches_selection':hashlib.sha256((R/'signals.py').read_bytes()).hexdigest()==choice['signal_code_hash'],
      'note':'Post-run nonsemantic changes: output-directory overwrite guard, extra invalidation test, report generator. Frozen signals unchanged.'}
(O/'verification.json').write_text(json.dumps(dump,ensure_ascii=False,indent=2))
print(R/'Peak_Ai_Report_UA.md')
