# Технічне завдання: Manual Close Detection (Finalization-First)

## Мета

Забезпечити, щоб при ручному закритті позиції на біржі (через Binance App/Web) бот:
- Автоматично детектував це через порівняння поточного балансу з baseline
- Виконував повний cleanup (скасування ліміток, repay боргу, очистка state)
- Робив це на самому початку manage_v15_position (позиція 1/10), до будь-яких watchdog/trailing/TP/SL дій
- Дотримувався принципу Finalization-First: cleanup → return, нічого більше не виконується в цьому циклі

---

## Вимоги

1. **Детекція manual close (LONG vs SHORT guards)**

### 1.1 Поля та розрахунки
Використовуються поля, зняті `baseline_policy`:
- `base_free`, `base_locked`
- `quote_free`, `quote_locked`
- `debt` (для margin)

Розрахункові значення:
- `base_total = base_free + base_locked`
- `quote_total = quote_free + quote_locked`

### 1.2 Допуски (tolerances)
- `BASE_EPS = 0.00001 BTC` (або еквівалент для іншого base)

### 1.3 Загальні передумови
- `st["position"]` існує та активна
- `st["baseline"]["active"]` існує
- Визначено `side` позиції (LONG або SHORT)

### 1.4 Guard-умови для LONG
Manual close для LONG вважається підтвердженим, якщо **одночасно**:
1) `abs(current.base_total - baseline.base_total) <= BASE_EPS`
2) (Margin) `current_debt.has_debt == False` *(рекомендовано як строгий gate)*

### 1.5 Guard-умови для SHORT
Manual close для SHORT вважається підтвердженим, якщо **одночасно**:
1) `current_debt.has_debt == False` *(обовʼязковий gate)*
2) `abs(current.base_total - baseline.base_total) <= BASE_EPS`

Quote не є guard, оскільки quote змінюється на close через PnL + fees.

> Примітка: `openOrders` **не є** джерелом істини про наявність позиції на margin spot і використовуються лише як обʼєкт cleanup.


2. **Cleanup (Finalization-First)**
   - **Скасувати всі exit-ордери** (SL, TP1, TP2) через `api.cancel_order()`, ігнорувати помилки "UNKNOWN_ORDER"
   - **Repay margin debt** через `margin_policy.repay_if_any()`, якщо TRADE_MODE=margin
   - **Очистити state**:
     - `st["position"] = None`
     - `st["cooldown_until"] = now_s + COOLDOWN_SEC`
     - `st["baseline"]["active"] = None`
     - Записати `st["last_closed"]` з причиною "MANUAL_CLOSE_DETECTED"
   - **Зберегти state** (save_state)
   - **Відправити webhook/log** з деталями cleanup

3. **Порядок виконання**
   - Весь блок manual close detection та cleanup має бути на самому початку manage_v15_position (позиція 1/10)
   - Після cleanup — `return` (жодна інша логіка не виконується в цьому циклі)

4. **Безпека**
   - Не виконувати cleanup, якщо baseline відсутній або позиція неактивна
   - Не запускати watchdog/trailing/TP/SL, якщо cleanup вже виконано

5. **Документування**
   - Описати цей механізм у AUDIT_PRODUCT_QUALITY.md та/або WATCHDOG_SPEC.md як реалізацію Finalization-First для manual close

---

## Додатково

- Якщо repay debt не вдається — alert оператору, але state все одно очищати
- Покрити тестами: сценарії ручного закриття, edge cases (залишок боргу, вже скасовані ордери)
- Всі зміни мають бути ізольовані, не впливати на інші watchdog-логіки

---

**Критерій приймання:**  
- Якщо позиція закрита вручну (balance ≈ baseline), cleanup виконується негайно, всі інші дії блокує return, state очищено, оператор отримує повідомлення.

- Архітектура (додається до ТЗ)
Компоненти та відповідальність
1) Executor (manage_v15_position)

Роль: єдиний власник state-machine та єдине місце, яке виконує дії, що змінюють стан (cancel/repay/clear state).

Відповідає за:

Виклик manual_close_detector.tick(...) на самому початку manage_v15_position (позиція 1/10).

Якщо tick() повернув True → негайний return (Finalization-First), жодні watchdog/trailing/TP/SL далі не виконуються.

Виконання cleanup (через детектор) в рамках того ж циклу executor (single-owner, без паралельних процесів).

2) Новий модуль executor_mod/manual_close_detector.py

Роль: детекція ручного втручання на основі exchange reality + baseline, з контрольованою частотою перевірок.

Відповідає за:

Throttle опитування біржі (наприклад раз на MANUAL_CLOSE_CHECK_SEC, дефолт 120 сек) з персистентним ключем у state.

Читання current balance/debt з біржі (margin spot):

Баланси: через api.margin_account(...) + парсинг margin_policy._asset_snapshot(...) до free/locked.

Борг: через api.get_margin_debt_snapshot(...) з урахуванням isolated/cross.

    Перевірку guard-умов (LONG/SHORT) з цього ТЗ.

(Рекомендовано) 2-step confirm (candidate → confirm), щоб уникнути eventual-consistency після ручного закриття.

При confirmed:

Лог 1 раз (MANUAL_CLOSE_DETECTED_OK) без спаму.

Notify 1 раз через notifications (див. нижче).

Запуск cleanup (cancel exits → repay → clear state → save_state) і повернення True.

Дозволені мутації state (мінімум):

pos["manual_close_next_check_s"] — throttle таймер.

pos["manual_close_candidate_s"] — 2-step confirm.

pos["manual_close_notified"] — антиспам для OK-повідомлення.

Очистка позиції/базелайну та запис last_closed виконується в cleanup-блоці (single-owner).

3) executor_mod/notifications.py ("труба")

Роль: I/O модуль. Не приймає рішень, не зберігає бізнес-стан, не робить дедуп поза тим, що явно задано state.

Відповідає за:

log_event(...) — запис JSONL у EXEC_LOG з cap.

send_webhook(payload) — доставка у n8n/Telegram (та інші канали).

send_trade_closed(...) — стандартний шлях відправки TRADE_CLOSED (може бути перевикористаний для manual close як close_reason=MANUAL_CLOSE_DETECTED).

Принцип антиспаму:

Дедуп/тротлінг виконуються в state (executor/детектор), а не в notifications.py.

Мінімальний контракт інтеграції
1) Виклик у manage_v15_position (на початку)

Executor завжди викликає детектор першим кроком:

handled = manual_close_detector.tick(st, pos, api, margin_policy, ENV, now_s)

if handled: return

Примітка: детектор не запускається, якщо st["position"] або st["baseline"]["active"] відсутні.

2) Вхідні параметри tick(...)

manual_close_detector.tick(...) має приймати лише те, що потрібно для (a) зчитування exchange reality і (b) запуску cleanup:

st: Dict[str, Any] — глобальний state (джерело істини).

pos: Dict[str, Any] — активна позиція (посилання на st["position"]).

api — бинанс API wrapper (виклики margin_account, get_margin_debt_snapshot, cancel_order, тощо).

margin_policy — доступ до _asset_snapshot(...) та repay_if_any(...) (для TRADE_MODE=margin).

ENV: Dict[str, Any] — конфіг (EPS, throttle seconds, isolated/cross flags, COOLDOWN_SEC, тощо).

now_s: int — поточний час у секундах.

Заборона: tick() не повинен читати глобальні env напряму, окрім як через ENV, щоб зберегти детермінізм тестів.

3) Дозволені мутації state (scope)

Щоб уникнути “розповзання” відповідальності, tick() має право змінювати лише наступні ключі, окрім блоку cleanup:

3.1 Detector keys (технічні)

pos["manual_close_next_check_s"] — throttle для опитування біржі.

pos["manual_close_candidate_s"] — 2-step confirm (перший успішний збіг guard-умов).

pos["manual_close_notified"] — антиспам для OK-notify.

(опц.) pos["manual_close_last_check_ts"] — телеметрія.

(опц.) pos["manual_close_last_error"] — остання помилка читання exchange reality (без spam-логів).

3.2 Cleanup keys (бізнес-мутації) — тільки у confirmed гілці

При confirmed manual close детектор виконує cleanup і має право змінювати:

st["position"] = None

---


1) Дефолтна частота

MANUAL_CLOSE_CHECK_SEC = 120 сек (раз на 2 хв) — дефолтний інтервал опитування біржі.

Throttle реалізується через pos["manual_close_next_check_s"] і персиститься в state, щоб після рестарту частота залишалась детермінованою.

2) Прискорений режим при WARN/WARM (опційно)

Якщо в системі активний стан підвищеної уваги (наприклад pos["warm"] == True або інший існуючий прапор/сигнал), дозволяється зменшити інтервал:

MANUAL_CLOSE_CHECK_SEC_WARM = 15..30 сек.

Вибір конкретного прапора WARM/WARN залежить від наявних сигналів у state; якщо такого сигналу немає, використовується лише дефолтний інтервал 120 сек.

3) Заборона спаму

Незалежно від інтервалу опитування, MANUAL_CLOSE_DETECTED_OK та Telegram/webhook notify відправляються один раз на trade_key (див. розділ no-spam).

Принципи

Single-owner: лише executor виконує side-effect дії (cancel/repay/state reset).

Exchange reality > local state: рішення приймаються за даними біржі, baseline — якір.

Finalization-First: confirmed → cleanup → return.

                                                   Етапи впровадження ТЗ (інваріантний формат)
------------------------Phase 0 — Аудит і карта інтеграції (NO CODE)

Статус: ✅ DONE

Before

Немає модуля manual close

Executor працює як зараз

Agent does

Визначає:

де читаються balances / debt

де виконується cleanup

де викликається notifications.send_trade_closed

точку вставки на початку manage_v15_position

After

Є чітка карта інтеграції

Є контракт manual_close_detector.tick(...)

Контрольні / тонкі місця

1) Порядок: manual_close_detector.tick() має йти після sl_done early-exit, щоб не порушити контракт “no logic on already-closed positions”.

2) _finalize_close() є вкладеною функцією всередині manage_v15_position; наступні фази мають працювати через callback/сигнальний контракт, а не прямий виклик з модуля.

3) exchange_snapshot.py кешує лише openOrders; margin balances/debt читаються напряму з біржі → потрібні throttles + детермінізм після рестарту.

4) Invariant I13 — референтний шаблон exchange-truth + rate-limit + fail-loud escalation; manual-close логіка має узгоджуватись із цим стилем.

5) Нотифікації мають перевикористовувати send_trade_closed з dedupe через st["last_notified_close_trade_key"] (без нових spam-путів).

Never

Ніяких змін логіки

Ніяких diff

---------------------Phase 1 — Skeleton модуля (Zero behavior change)

Статус: ✅ DONE

Commit: eb0de85cbe989f3c8f0ca6d32a8d15f7f1c4c91b (Add manual close detector skeleton)

Before

manual_close_detector не існує

Agent does

Додає файл executor_mod/manual_close_detector.py

Реалізує tick(...)->False

Додає виклик tick() на початку manage_v15_position

After

Executor викликає tick()

Поведінка повністю ідентична попередній

Execution status

- Додано executor_mod/manual_close_detector.py з tick(...)->False без побічних ефектів.

- Виклик tick() підключено в manage_v15_position після sl_done early-exit і до openOrders/watchdog логіки.

- Додано unit test, який підтверджує відсутність side effects і API-викликів.

Non-blocking notes ⚠️

- executor.py тепер імпортує margin_policy, хоча tick на Stage 1 його не використовує (допустимий шум / потенційний дубль імпорту).

- Тест перевіряє api.method_calls == []; це не ловить лише читання атрибутів (допустимо для Stage 1).

Never

Жодних API викликів

Жодних side effects

Phase 2 — Throttle (детермінізм без дій)

Before

Немає контролю частоти

Agent does

Додає pos["manual_close_next_check_s"]

Додає MANUAL_CLOSE_CHECK_SEC = 120

tick():

поважає throttle

нічого не читає

нічого не змінює, окрім throttle key

After

Polling детермінований

Поведінка не змінена

Never

Ніяких логів

Ніяких cleanup

---------## Phase 2 — Exchange-truth Manual Close Detection (Finalization-First)

Статус: ✅ DONE

Зроблено:
- Реалізовано manual_close_detector.tick() з exchange-truth перевіркою балансів (base/quote) та margin debt.
- LONG / SHORT guard-умови розділені (guard = base + debt; quote не використовується).
- Two-step confirmation через manual_close_candidate_s + MANUAL_CLOSE_CONFIRM_SEC.
- Throttle з персистом (manual_close_next_check_s) для детермінізму після рестарту.
- Detector лише сигналізує (handled/reason/tag/details); фіналізація виконується через існуючий finalize-contract в executor (_close_slot / _finalize_close).
- Повторне використання існуючих механізмів: send_trade_closed, report_trade_close, margin_guard.on_after_position_closed.

Tests:
- Stage 1: no-side-effects test (detector не мутує state і не викликає API).
- Stage 2: guards (LONG/SHORT), confirm-window, throttle persistence, інтеграційний finalize-path через executor.

Примітки ⚠️:
- Confirm/throttle залежать від персисту state; при втраті запису підтвердження може відкластися.
- EPS-пороги зменшують, але не повністю усувають ризик false-positive при баланс-дріфті.
- Detector навмисно не викликає _close_slot напряму; фіналізація централізована в executor.

-------------------Phase 3 — Read-only exchange reality

Статус: ✅ ВИКОНАНО (Manual Close Detection)

Що зроблено:
- manual_close_detector переведено в режим read-only exchange snapshot.
- раз на MANUAL_CLOSE_CHECK_SEC (throttle через pos["manual_close_next_check_s"], персиститься в state).
- читає з біржі balances + debt snapshot (margin: margin_account + get_margin_debt_snapshot, spot: spot account).
- рахує totals + deltas vs baseline + has_debt.
- зберігає діагностику в pos["manual_close_diag"].
- пише один JSONL log line на кожен виконаний snapshot (MANUAL_CLOSE_SNAPSHOT_OK), і окремо MANUAL_CLOSE_SNAPSHOT_ERROR при помилці.
- нема side effects: не виставляє candidate/confirm/notified, не тригерить finalize/cleanup, не викликає close.

Примітка про “спам”:
- MANUAL_CLOSE_SNAPSHOT_OK логуватиметься кожен tick (наприклад, раз на 120 сек). Це нормально для Stage 3, бо це діагностичний snapshot.
- “OK один раз на trade_key” (антиспам для Telegram/webhook) — це етапи Stage 4/5, не Stage 3.

Примітка про executor.py:
- executor.py як і раніше очікує, що manual_close_detector.tick() може повернути handled=True, і тоді піде шлях фіналізації через _close_slot.
- Після Stage 3 (read-only) handled завжди False, тому manual close зараз не закриє позицію. Це очікувано до реалізації Stage 4/5.

Before

Executor не знає current exchange reality для manual close

Agent does

Реалізує read-only:

balances → base_total / quote_total

debt snapshot

Порівнює з baseline

After

Значення current vs baseline обчислюються

Але ніщо не тригериться

Never

Ніяких candidate

Ніяких confirm

Ніяких side effects

---------------------Phase 4 — Guards + 2-step confirm
📌 Stage 4 — Manual Close Detection: DONE

Що зроблено
- Реалізовано 2-step confirm для manual close:
  - 1-й tick → фіксує manual_close_candidate_s
  - 2-й tick після confirm window + throttle → handled=True
- Додано guard-умови:
  - base_close з допуском BASE_EPS (inclusive: `<=`)
  - відсутність боргу (has_debt == False) для LONG/SHORT
- Реалізовано скидання кандидата, якщо guard перестає виконуватись
- Прибрано спамний snapshot OK лог
- executor.py як і раніше очікує:
  - handled=True → стандартний шлях _close_slot

Тести
- Додані тести Phase 4
- Виправлено confirm-тест:
  - другий tick відбувається після throttle-вікна, згідно контракту
- Усі тести зелені:
  - pytest: OK
  - unittest: OK

Критичні моменти (важливо знати)
- Confirm ≠ throttle: підтвердження можливе лише коли tick реально виконав snapshot
- manual_close_next_check_s — обовʼязковий для детермінізму після рестарту
- manual_close_candidate_s — зберігається в state, не локальний

Зауваження
- Прод-код у цьому кроці коректний, змін не потребує
- Зміни на фіналі — test-only, контракт підтверджено

st["cooldown_until"] = now_s + COOLDOWN_SEC

st["baseline"]["active"] = None

st["last_closed"] — з причиною MANUAL_CLOSE_DETECTED та діагностикою (deltas + debt)

(опц.) st["last_notified_close_trade_key"] — через виклик notifications.send_trade_closed(...) (dedupe)

Заборона: tick() не повинен змінювати інші watchdog поля (SL/TP/trailing) і не повинен створювати/модифікувати ордери, окрім cancel exits та MARKET-flatten (якщо таке передбачено cleanup, але для manual close зазвичай не потрібно).

4) Повідомлення та логування (no-spam)

У tick() при confirmed:

1× notifications.log_event("MANUAL_CLOSE_DETECTED_OK", ...)

1× notify через notifications.send_trade_closed(st, pos, close_reason="MANUAL_CLOSE_DETECTED") або окремий webhook event MANUAL_CLOSE_OK

Дедуп/антиспам забезпечується:

pos["manual_close_notified"] (локально)

st["last_notified_close_trade_key"] (глобально, якщо використовується send_trade_closed)

Періодичність перевірок (Polling Policy)
Базовий режим

MANUAL_CLOSE_CHECK_SEC = 120 секунд.

Використовується за замовчуванням, коли немає активних WARN/WARM сигналів.

Мета: мінімізувати API-навантаження і шум, зберігаючи керованість без доступу до терміналу.

Підвищена частота при WARN/WARM

Якщо в state зафіксовано попереджувальний стан (WARN або WARM), executor дозволяє зменшити інтервал:

MANUAL_CLOSE_CHECK_SEC_WARN = 30 секунд (рекомендовано)

Джерело WARN/WARM: внутрішні алерти executor (watchdog, margin, invariant), не Telegram.

Реалізація throttle

Фактичний інтервал визначається в tick() динамічно:

якщо warn_active == True → використати MANUAL_CLOSE_CHECK_SEC_WARN

інакше → MANUAL_CLOSE_CHECK_SEC

Обраний інтервал персиститься через pos["manual_close_next_check_s"].

Безпека

Навіть у WARN/WARM режимі детектор не має права виконувати будь-які дії без підтвердження guard-умов.

Частіший polling не змінює бізнес-логіку, лише швидкість реакції.

Періодичність опитування (throttle policy)

Before

Немає формальної детекції

Agent does

Реалізує guards:

LONG: totals + debt gate

SHORT: debt gate + totals

Реалізує 2-step confirm:

tick₁ → candidate

tick₂ → confirmed

After

confirmed == True можливе лише після двох послідовних тиків

Candidate скидається при будь-якому mismatch

Never

Confirm за один тик

Cleanup на цьому етапі

----------Phase 5 — Cleanup (Finalization-First)
Статус: DONE (змерджено у коміт f4d349f).
Підсумок: handled=True шлях тепер = cleanup baseline/keys → _finalize_close → return.
Вилучено Phase 6 лог/notify та manual_close_notified з Phase 5.
Прибрано зайві save_state() до/після _finalize_close; лишається save_state всередині _close_slot().
Тепер НЕ робимо save_state() перед _finalize_close(). Це означає:
- cleanup baseline.active=None і pop ключів персистяться разом з _close_slot() save.
- Якщо процес впаде між cleanup і _close_slot() save — ці зміни не запишуться.
- Це нормально для Finalization-First: якщо close не відбувся, стан не має бути напівзакритим.

Додатково (Phase 5.x — restart determinism fix):
- baseline.active очищається лише в _close_slot() під маркером baseline_clear_pending.
- Мета: best-effort save під час cleanup не може зафіксувати baseline.active=None, поки position ще OPEN (crash-window).
- Додано регресійний тест: test_manual_close_defers_baseline_clear_until_close_slot.

Before

confirmed=True не має ефекту

Agent does

При confirmed=True:

cancel exit orders (best-effort)

repay debt (best-effort)

reset position

reset baseline

set cooldown

return з manage_v15_position

After

State консистентний

Executor не виконує жодної іншої логіки в цьому тіку

Never

Частковий cleanup

Watchdog / TP / SL після confirmed

-------------Phase 6 — Notifications + logging (no-spam)

Before

Cleanup не повідомляється

Agent does

При cleanup:

лог MANUAL_CLOSE_DETECTED_OK 1 раз

send_trade_closed(..., MANUAL_CLOSE_DETECTED) 1 раз

Дедуп:

pos["manual_close_notified"]

існуючий last_notified_close_trade_key

After

Один trade → одне повідомлення

Never

Повторні notify

Notify без cleanup

-------------Phase 7 — Tests (інваріанти)

Agent does

Тести гарантують:

confirm ≠ possible за 1 тик

SHORT без repay → no confirm

LONG/SHORT guards коректні

notify only once

After

Логіка захищена від регресій

Never

Тести на “логи”

Тести на execution

-----------Phase 8 — Rollout (концептуально)

Before

Manual close не обробляється

After

Ручне закриття на біржі →
exchange reality →
guards →
cleanup →
notify →
чистий state

Never

Ручні команди

Флаги

Часткові стани

Фінальна формула (інваріант)

Exchange reality — єдине джерело істини.
Якщо позиція фактично закрита на біржі, executor зобовʼязаний:

це виявити,

безпечно очистити state,

зробити це рівно один раз.

Це і є сутність ТЗ.

---
