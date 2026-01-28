# Executor

**Executor** — автоматизований торговельний виконавець для сигналів DeltaScout PEAK. Система забезпечує повний цикл виконання угод: від отримання сигналу до закриття позиції з підтримкою trailing stop, маржинальної торгівлі та комплексних інваріантів стану.

## Зміст

- [Огляд](#огляд)
- [Архітектура](#архітектура)
- [Основний модуль: executor.py](#основний-модуль-executorpy)
- [Допоміжні модулі](#допоміжні-модулі)
  - [baseline_policy.py](#baseline_policypy)
  - [binance_api.py](#binance_apipy)
  - [emergency.py](#emergencypy)
  - [event_dedup.py](#event_deduppy)
  - [exchange_snapshot.py](#exchange_snapshotpy)
  - [exit_safety.py](#exit_safetypy)
  - [exits_flow.py](#exits_flowpy)
  - [invariants.py](#invariantspy)
  - [margin_guard.py](#margin_guardpy)
  - [margin_policy.py](#margin_policypy)
  - [market_data.py](#market_datapy)
  - [notifications.py](#notificationspy)
  - [price_snapshot.py](#price_snapshotpy)
  - [reporting.py](#reportingpy)
  - [risk_math.py](#risk_mathpy)
  - [state_store.py](#state_storepy)
  - [trail.py](#trailpy)
- [Утиліти (tools/)](#утиліти-tools)
- [Конфігурація](#конфігурація)
- [Режими роботи](#режими-роботи)
- [Безпека та надійність](#безпека-та-надійність)
- [Встановлення та запуск](#встановлення-та-запуск)

---

## Огляд

Executor — це Python-застосунок для автоматизованої торгівлі на Binance, що працює в режимі single-position (одна позиція за раз). Система:

- **Читає сигнали** з JSONL лог-файлу DeltaScout
- **Виконує угоди** через Binance REST API (spot і margin)
- **Керує ризиками** через stop-loss, take-profit та trailing stop
- **Моніторить стан** через систему інваріантів
- **Підтримує margin** з автоматичним і ручним управлінням запозиченнями
- **Надсилає сповіщення** через вебхуки (n8n)
- **Генерує звіти** для offline аналізу та управлінської звітності

Ключові принципи:
- **Ізоляція даних**: Executor пише лише у власні файли стану/логів
- **Дедуплікація**: Стабільна система дедуплікації подій на основі ключа `action|ts|min|kind|price`
- **Відмовостійкість**: Cooldown після закриття, блокування після відкриття, ретраї для exits
- **Детермінованість**: Всі розрахунки через `Decimal` для уникнення float-артефактів
- **Safety-first**: TP/SL watchdog механізми для захисту від missing ордерів
- **Performance**: In-memory snapshots (openOrders, mid-price) для мінімізації API викликів

---

## Архітектура

```
Executor/
├── executor.py              # Головний виконавчий механізм
├── executor_mod/            # Модульна архітектура
│   ├── __init__.py
│   ├── baseline_policy.py   # Базові стратегії управління позицією
│   ├── binance_api.py       # REST API адаптер
│   ├── emergency.py         # 🆕 Emergency Shutdown Mode
│   ├── event_dedup.py       # Дедуплікація подій
│   ├── exchange_snapshot.py # Кеш стану біржі (openOrders)
│   ├── exit_safety.py       # TP/SL watchdog контроль
│   ├── exits_flow.py        # Логіка виходів
│   ├── invariants.py        # Детектори інваріантів
│   ├── margin_guard.py      # Хуки маржинальної торгівлі
│   ├── margin_policy.py     # Політика маржі
│   ├── market_data.py       # Ринкові дані
│   ├── notifications.py     # Логування та вебхуки
│   ├── price_snapshot.py    # Кеш mid-price (bookTicker)
│   ├── reporting.py         # Генерація trade reports
│   ├── risk_math.py         # Ризик-менеджмент математика
│   ├── state_store.py       # Менеджер стану
│   └── trail.py             # Trailing stop логіка
├── tools/                   # Утиліти
│   ├── enrich_trades_with_fees.py  # Збагачення trade reports комісіями
│   └── make_manager_report.py      # Генерація manager звітів
└── test/                    # Тести
    ├── test_executor.py
    ├── test_binance_api_smoke.py
    ├── test_state_store.py
    ├── test_notifications.py
    ├── test_event_dedup.py
    ├── test_invariants_*.py
    ├── test_margin_*.py
    ├── test_trail.py
    ├── test_tp_watchdog.py
    ├── test_sl_watchdog.py
    ├── test_exchange_snapshot.py
    ├── test_price_snapshot.py
    └── test_enrich_trades_with_fees.py
```

---

## Основний модуль: executor.py

**Файл**: `executor.py`
**Призначення**: Головний виконавчий цикл, координує всі модулі

### Основні функції

#### Ініціалізація та конфігурація
- `_validate_trade_mode()` — перевірка режиму торгівлі (spot/margin)
- `_preflight_margin_cross_usdc()` — preflight-перевірки для cross margin
- ENV словник — всі налаштування з environment variables

#### Робота з сигналами
- `read_tail_lines(path, n)` — читання останніх N рядків без повного сканування файлу
- `stable_event_key(evt)` — стабільний ключ дедуплікації з `event_dedup`
- `bootstrap_seen_keys_from_tail()` — ініціалізація seen_keys при старті

#### Обчислення entry/exit цін
- `build_entry_price(kind, close_price)` — розрахунок ціни входу з урахуванням офсету
- `notional_to_qty(entry, usd)` — конвертація USD в quantity
- `validate_qty(qty, entry)` — перевірка MIN_QTY та MIN_NOTIONAL
- `swing_stop_far(df, i, side, entry)` — розрахунок stop-loss на основі swing

#### Управління ордерами
- `place_entry_live()` — розміщення entry ордера (LIMIT/MARKET)
- `validate_exit_plan()` — валідація плану виходів (sl, tp1, tp2)
- `place_exits_v15()` — розміщення всіх exit ордерів (3 ноги)
- `check_entry_status()` — перевірка статусу entry ордера
- `manage_position()` — керування відкритою позицією (TP fills, trailing)

#### Trailing stop
- `activate_trail()` — активація trailing після TP2
- `update_trail()` — оновлення trailing stop
- `cancel_and_replace_sl()` — заміна SL ордера при trailing

#### Життєвий цикл позиції
- `open_flow()` — повний цикл відкриття позиції
- `close_position()` — закриття позиції з cooldown
- `failsafe_flatten()` — аварійне закриття market ордером
- `_finalize_close(reason, tag)` — централізоване закриття з cleanup (v2.1+)
- `_cancel_sibling_exits_best_effort(tag)` — throttled cleanup залишкових exit ордерів (v2.1+)
- `_tp1_be_transition(exit_side, be_stop, rem_qty, source)` — перехід SL до breakeven після TP1 з retry (v2.2+)

#### Синхронізація та відновлення
- `sync_from_binance(st, reason)` — синхронізація стану з біржею (attach до існуючої позиції)
- `handle_open_filled_exits_retry(st)` — retry логіка для exits при OPEN_FILLED
- `manage_v15_position(symbol, st)` — керування позицією v1.5 (TP fills, trailing, watchdog)

#### Головний цикл
- `main_loop()` — нескінченний polling loop
- Інваріанти перевіряються кожні `INVAR_EVERY_SEC`
- Управління позицією кожні `MANAGE_EVERY_SEC`
- Trailing оновлюється кожні `TRAIL_UPDATE_EVERY_SEC`

### Ключові особливості

1. **Single-position режим**: ігнорує нові PEAK поки позиція OPEN/PENDING
2. **Cooldown**: після закриття чекає `COOLDOWN_SEC` перед новим входом
3. **Lock**: після відкриття блокує `LOCK_SEC` для захисту від дублікатів
4. **Plan B**: якщо entry не спрацював вчасно, перевіряє актуальність через bookTicker
5. **TP/SL Watchdog**: автоматична детекція missing TP/SL ордерів з synthetic trailing fallback
6. **Exchange/Price Snapshots**: in-memory кеш openOrders та mid-price для зменшення API викликів
7. **Trade Reporting**: автоматична генерація trade reports для offline аналізу та fee enrichment
8. **Синхронізація стану**: можливість attach до існуючої позиції на біржі через `sync_from_binance()`
9. **Cleanup Refactoring (v2.1+)**: централізований механізм cancel залишкових exits при закритті
   - `_finalize_close()` — cleanup НІКОЛИ не блокує закриття позиції (`with suppress(Exception)`)
   - Throttling через `CLOSE_CLEANUP_RETRY_SEC` для захисту від rate limits
   - Логування через `CLOSE_CLEANUP_BEST_EFFORT` події
10. **TP1→BE Retry (v2.2+)**: надійний перехід SL до breakeven після TP1
   - Max attempts через `TP1_BE_MAX_ATTEMPTS` (default 5) для запобігання infinite loops
   - Strict old SL cancel verification (підтримка -2013/Unknown order/FILLED)
   - Insufficient balance handling з retry логікою
   - State sync: оновлює `pos["prices"]["sl"]`, `sl_status_next_s`, очищає `sl_done`
   - Webhook alerts: `TP1_BE_MAX_ATTEMPTS_REACHED` при досягненні max
   - **BE SL retry cooldown** (v2.2.1+): If BE placement fails repeatedly, the executor pauses attempts for `TP1_BE_COOLDOWN_SEC` seconds (default 300s = 5 min) after `TP1_BE_MAX_ATTEMPTS` retries, then automatically resumes (cooldown is time-limited, not permanent)
   - `tp1_be_disabled` auto-clears after cooldown, attempts reset to 0

### TP1 → BE Behavior

**Decoupled State Machine** (v2.2+): Перехід Stop Loss до Break-Even після TP1 FILLED є асинхронним процесом, що керується state machine.

#### Ключові принципи:

1. **Immediate TP1 Detection**: `tp1_done` встановлюється **одразу** при виявленні TP1 FILLED, незалежно від успіху BE переходу
   ```python
   # executor.py, при TP1 FILLED
   pos["tp1_done"] = True
   log_event("TP1_DONE", mode="live", order_id_tp1=tp1_id)
   ```

2. **Separate BE State Machine**: Перенесення SL у BE керується окремою state machine через `tp1_be_pending`
   ```python
   # Ініціалізація state machine
   pos["tp1_be_pending"] = True
   pos["tp1_be_old_sl"] = old_sl_id
   pos["tp1_be_exit_side"] = exit_side
   pos["tp1_be_stop"] = be_stop
   pos["tp1_be_rem_qty"] = rem_qty
   pos["tp1_be_source"] = "TP1"  # або "TP1_WATCHDOG"
   ```

3. **Watchdog Plan Key**: `exit_safety.tp_watchdog_tick()` повертає новий ключ:
   - **Новий**: `init_be_state_machine: True` — рекомендовано
   - **Старий**: `move_sl_to_be: True` — підтримується для зворотної сумісності
   ```python
   # executor.py обробляє обидва варіанти
   should_init_be = tp_plan.get("init_be_state_machine") or tp_plan.get("move_sl_to_be")
   ```

4. **Independent Execution**: `_tp1_be_transition_tick()` виконується незалежно в кінці `manage_v15_position()` після всіх watchdog операцій
   - Читає параметри зі state (`tp1_be_exit_side`, `tp1_be_stop`, `tp1_be_rem_qty`)
   - Retry логіка з throttling через `tp1_be_next_s`
   - Max attempts capture через `TP1_BE_MAX_ATTEMPTS` (default 5)

5. **Auto-Recovery Cooldown** (v2.2.1+): Після досягнення max attempts система **не блокується назавжди**:
   - `tp1_be_disabled` встановлюється на `TP1_BE_COOLDOWN_SEC` (default 300s = 5 хв)
   - Після cooldown flag **автоматично очищається**, attempts скидається до 0
   - Система отримує другий шанс для BE переходу
   - Захищає від тимчасових збоїв API/біржі
   ```python
   # Auto-clear після cooldown
   if pos.get("tp1_be_disabled") and now_s >= pos["tp1_be_next_s"]:
       pos.pop("tp1_be_disabled", None)
       pos["tp1_be_attempts"] = 0  # Fresh start
       log_event("TP1_BE_COOLDOWN_EXPIRED", mode="live")
   ```

**Переваги підходу**:
- ✅ TP1 FILLED fact фіксується негайно (критично для звітності)
- ✅ BE transition може retry при помилках без блокування TP1 detection
- ✅ State machine виживає restart executor
- ✅ Backward compatibility через підтримку обох plan keys
- ✅ Auto-recovery від тимчасових збоїв API через cooldown механізм

---

## Допоміжні модулі

### baseline_policy.py

**Призначення**: Модуль для реалізації базових стратегій управління позицією та ризиком.

#### Основні функції

- `configure()` — ініціалізація залежностей модуля
- Fallback-логіка для випадків, коли основна стратегія недоступна
- Контроль за станом позиції через `exchange_snapshot`
- Може використовуватись для тестування та порівняння з основними алгоритмами

#### Особливості

- Працює з in-memory кешем openOrders через `exchange_snapshot`
- Забезпечує детермінований baseline для порівняння з експериментальними стратегіями

---

### binance_api.py

**Призначення**: Адаптер для Binance REST API з підтримкою spot та margin

#### Основні функції

- `configure(env, fmt_qty, fmt_price, round_qty)` — ініціалізація з форматерами
- `_binance_signed_request(method, endpoint, params)` — підписаний запит з HMAC SHA256
- `binance_public_get(endpoint, params)` — публічний GET без підпису

#### Ордери
- `place_spot_limit(symbol, side, qty, price, client_id)` — LIMIT ордер (spot/margin)
- `place_spot_market(symbol, side, qty, client_id)` — MARKET ордер
- `flatten_market(symbol, pos_side, qty, client_id)` — аварійне закриття
- `cancel_order(symbol, order_id)` — скасування ордера
- `check_order_status(symbol, order_id)` — статус ордера
- `open_orders(symbol)` — всі відкриті ордери

#### Margin
- `margin_account(is_isolated, symbols)` — інформація про margin акаунт
- `margin_borrow(asset, amount, is_isolated, symbol)` — запозичення
- `margin_repay(asset, amount, is_isolated, symbol)` — погашення
- `get_margin_debt_snapshot(symbol, is_isolated)` — snapshot боргів для I13

#### Sanity
- `binance_sanity_check()` — перевірка підключення та автентифікації
- `get_mid_price(symbol)` — mid price з bookTicker

#### Особливості
- Автоматична синхронізація часу через `_BINANCE_TIME_OFFSET_MS`
- Підтримка `MARGIN_BORROW_MODE`: `manual` (NO_SIDE_EFFECT) / `auto` (AUTO_BORROW_REPAY)
- `isIsolated` нормалізується до `"TRUE"/"FALSE"` strings

---

### emergency.py 🆕

**Призначення**: Emergency Shutdown Mode — operator-controlled graceful shutdown

#### Компоненти

1. **Alert on First Failure** — негайне сповіщення через webhook при `save_state()` failure
2. **Emergency Shutdown Trigger** — файл-прапор `/data/state/emergency_shutdown.flag`
3. **Reconciliation-First Shutdown** — перевірка статусів ордерів перед очисткою
4. **Sleep Mode** — бот ігнорує нові сигнали до wake up

#### Ключові функції

```python
save_state_safe(st, where) -> bool
# Заміна _save_state_best_effort з алертами

check_flag() -> bool
# Перевіряє чи існує emergency_shutdown.flag

check_sleep_mode(st) -> bool
# Перевіряє sleep mode і wake_up.flag

shutdown(st, reason) -> bool
# Reconciliation-first shutdown procedure
```

#### Принципи

- **Fail-Aware, Not Fail-Loud**: алерт, але не halt
- **Human-in-the-Loop**: оператор вирішує коли shutdown
- **Reconciliation-First**: перевірка ордерів перед фіналізацією
- **Fail-Safe**: при сумнівах — передача контролю людині

---

### event_dedup.py

**Призначення**: Дедуплікація DeltaScout PEAK подій

#### Ключова функція

```python
stable_event_key(evt) -> Optional[str]
# Повертає: "PEAK|2025-01-13T20:00|long|95000.0" (округлено до DEDUP_PRICE_DECIMALS)
```

#### Fingerprint алгоритму

```python
dedup_fingerprint() -> str
# SHA256 хеш: "dedup_v1|source_code|DEDUP_PRICE_DECIMALS=1|STRICT_SOURCE=True"
```

#### Bootstrap

```python
bootstrap_seen_keys_from_tail(st, tail_lines)
# Ініціалізує seen_keys з останніх 300 рядків лога при старті
```

#### Особливості

- Ігнорує події від інших джерел якщо `STRICT_SOURCE=True`
- Бакетує ts до хвилини для стабільності
- Зберігає останні `SEEN_KEYS_MAX` (500) ключів

---

### exchange_snapshot.py

**Призначення**: In-memory кеш/знімок стану біржі (openOrders) для зменшення кількості API-викликів та підвищення продуктивності.

- Зберігає останній список відкритих ордерів, час оновлення, статус, джерело оновлення
- Оновлюється лише при статусі позиції `OPEN` (manage loop) або при спеціальних подіях (BOOT, MANUAL, RECOVERY)
- Дозволяє іншим модулям (invariants, baseline_policy) читати стан без прямих API-запитів
- Має throttling (SNAPSHOT_MIN_SEC) для захисту від надмірних викликів
- Всі споживачі отримують дані через get_snapshot()/refresh_snapshot()

**Обмеження:** Кешує **тільки** openOrders. Не впливає на margin debt перевірки (I13 інваріант), account balance API чи check_order_status виклики.

**Ключові методи:**
- `freshness_sec()` — вік snapshot
- `is_fresh(max_age_sec)` — чи актуальний
- `refresh()` — оновлення через openOrders API
- `get_orders()` — отримати список ордерів (або порожній список)
- `to_dict()` — серіалізація для логування

---

### exit_safety.py

**Призначення**: Модуль контролю безпечного закриття позицій з системою TP/SL watchdog.

#### TP Watchdog / Exit Safety (Missing Orders & Synthetic Trailing)

**Контекст проблеми**: Binance API може повертати помилку "unknown order" для ордерів, які вже були виконані, скасовані або не існують на біржі внаслідок затримок синхронізації стану. Без нормалізації цих помилок до детермінованого статусу, planner-логіка може застрягнути в неоднозначному стані, а позиція залишиться неочищеною.

**Рішення**: Додано three-layer safety механізм для обробки missing TP orders та synthetic trailing:

#### 1. Missing Order Detection

**Проблема**: `check_order_status()` викидає виключення для missing orders, що порушує детермінованість planner-логіки.

**Рішення**:
- Додано helper функцію `_is_unknown_order_error(e)` в `executor.py`, яка розпізнає сигнатури "unknown order" у повідомленнях виключень:
  - `"UNKNOWN ORDER"`, `"UNKNOWN_ORDER"`
  - `"ORDER DOES NOT EXIST"`, `"ORDER_NOT_FOUND"`
  - `"NO SUCH ORDER"`
- При виникненні такої помилки під час `check_order_status()`, інжектується synthetic payload `{"status": "MISSING"}` замість пропагації виключення
- `exit_safety.tp_watchdog_tick()` обробляє `"MISSING"` так само як `"CANCELED"`, `"REJECTED"`, `"EXPIRED"` (missing TP states)

**Гарантії**:
- Інші типи виключень (мережеві помилки, rate limits) пропагуються нормально без synthetic injection
- `"MISSING"` статус використовується ТІЛЬКИ для нормалізації unknown-order помилок, не для інших станів

#### 2. TP2 Synthetic Trailing Quantity

**Проблема**: Коли TP2 ордер missing/canceled/expired, аварійна trailing логіка має використовувати правильну кількість для trailing stop.

**Рішення**:
- `tp_watchdog_tick()` для missing TP2 ЗАВЖДИ активує trailing на `qty2 + qty3` (не повну qty)
- Це відповідає V1.5 exit policy: TP1=33%, TP2=33%, trailing=34% remaining
- Незалежно від стану `tp1_done`, TP2 synthetic trailing завжди працює тільки з `qty2 + qty3`

**Відмінність від нормального flow**:
- Нормальний TP2 FILLED flow: trailing активується на remaining qty після TP1 і TP2 fills (зазвичай qty3)
- Аварійний TP2 MISSING flow: synthetic trailing на `qty2 + qty3` (TP2 не був виконаний)

#### 3. One-Shot Event Logging

**Проблема**: Detection events (TP1_PARTIAL_DETECTED, TP1_MISSING_PRICE_CROSSED, TP2_MISSING_SYNTHETIC_TRAILING) можуть логуватися на кожному tick, створюючи alert spam.

**Рішення**:
- Додано per-position boolean flags:
  - `tp1_wd_partial_logged` — TP1 partial fill виявлено
  - `tp1_wd_missing_logged` — TP1 missing + price crossed
  - `tp2_wd_missing_logged` — TP2 missing synthetic trailing
- Detection events логуються ТІЛЬКИ якщо відповідний flag = False
- Після логування flag встановлюється в True і зберігається в state
- Action events (TP1_MARKET_FALLBACK, TP2_SYNTHETIC_TRAILING_ACTIVATED) логуються завжди

#### Developer Notes / Testing

**Запуск тестів**:
```bash
python -m unittest -q
python -m pytest test/test_tp_watchdog.py -v
```

**Важливо для тестів**: `exchange_snapshot` є singleton модулем, який може зберігати стан між тестами. У `test_tp_watchdog.py` використовується `reset_snapshot_for_tests()` в `setUp()` для ізоляції тестів. Ця функція призначена ТІЛЬКИ для тестів і НЕ має використовуватися в production runtime.

#### SL Watchdog

**Призначення**: Захист від зависання у OPEN_FILLED стані коли SL ордер missing/rejected

**Функції**:
```python
sl_watchdog_tick(st, pos, symbol, get_mid_price_fn, now_s) -> Dict[str, Any]
# Перевіряє стан SL ордера та активує fallback при необхідності
```

**Логіка**:
1. Виклик при `status == "OPEN_FILLED"` та `sl_wd_enabled=True`
2. Перевіряє наявність SL ордера через `exchange_snapshot`
3. Якщо SL missing + ціна crossed stop → активує market fallback
4. One-shot events логуються через `sl_wd_missing_logged` flag

**Особливості**:
- Інтегрується з `price_snapshot` для отримання mid-price
- Throttled detection для зменшення spam
- Fallback до `flatten_market()` при критичних умовах

---

### exits_flow.py

**Призначення**: Централізована логіка розміщення exits

#### Функція

```python
ensure_exits(st, pos, reason, best_effort=True, attempt=None, save_on_success=True, save_on_fail=False) -> bool
```

Виконує:
1. `validate_exit_plan()` — валідація sl/tp1/tp2
2. `place_exits_v15()` — розміщення 3 ордерів
3. `save_state()` — збереження
4. `log_event()` + `send_webhook()` — сповіщення

Використовується для:
- Першого розміщення exits після entry fill
- Ретраїв при помилках
- Attach flows (synced positions)

---

### margin_policy.py

**Призначення**: Управління запозиченнями в margin режимі

#### Функції

```python
ensure_borrow_if_needed(st, api, symbol, side, qty, plan)
# Запозичує якщо free balance < needed
# LONG: запозичує quote (USDC)
# SHORT: запозичує base (BTC)
```

```python
repay_if_any(st, api, symbol)
# Погашає всі борги після закриття позиції
```

#### Трекінг

```python
st["margin"] = {
  "borrowed_assets": {"USDC": 100.0},       # глобальний лічильник
  "borrowed_by_trade": {"trade_key": {...}}, # per-trade трекінг
  "borrowed_trade_keys": ["trade_key"],
  "repaid_trade_keys": ["trade_key"],
  "active_trade_key": "trade_key"
}
```

---

### margin_guard.py

**Призначення**: Lifecycle hooks для margin режиму

#### Hooks

```python
on_startup(state)
# Виконується при старті executor

on_before_entry(state, symbol, side, qty, plan)
# Виконується перед розміщенням entry ордера
# Викликає margin_policy.ensure_borrow_if_needed()

on_after_entry_opened(state, trade_key)
# Виконується після fill entry

on_after_position_closed(state, trade_key)
# Виконується після закриття позиції
# Викликає margin_policy.repay_if_any()

on_shutdown(state)
# Виконується при shutdown
```

#### Режими

- `MARGIN_BORROW_MODE=auto`: hooks no-op (Binance AUTO_BORROW_REPAY)
- `MARGIN_BORROW_MODE=manual`: hooks виконують borrow/repay через API

---

### invariants.py

**Призначення**: Детектори аномалій стану (detector-only, не виконують actions)

#### Інваріанти

- **I1**: Protection present — SL має бути після OPEN_FILLED
- **I2**: Exit price sanity — sl < entry < tp1 < tp2 (LONG)
- **I3**: Quantity accounting — qty1 + qty2 + qty3 = qty_total
- **I4**: Entry state consistency — order_id, client_id, entry_mode присутні
- **I5**: Trail state sane — trail_qty > 0, trail_last_update_s
- **I6**: Feed freshness for trail — aggregated.csv не stale
- **I7**: TP orders after fill — tp1_id, tp2_id після OPEN_FILLED
- **I8**: State shape — orders/prices є dict
- **I9**: Trail active SL missing — якщо trail_active, SL має бути
- **I10**: Repeated trail errors — детектує -2010 loops
- **I11**: Margin config sanity — manual mode потребує NO_SIDE_EFFECT
- **I12**: Trade key consistency — всі hooks бачать один trade_key
- **I13**: No debt after close — exchange має не показувати debt після закриття

#### Конфігурація

```python
INVAR_ENABLED=1               # увімкнути
INVAR_EVERY_SEC=20            # частота перевірок
INVAR_THROTTLE_SEC=600        # throttle між алертами
INVAR_GRACE_SEC=15            # grace period для нових позицій
I13_GRACE_SEC=300             # grace для I13 перед exchange check
I13_ESCALATE_SEC=180          # ескалація до ERROR
I13_KILL_ON_DEBT=false        # halt executor якщо I13 ERROR
```

#### Вивід

- `log_event("INVARIANT_FAIL", invariant_id=..., severity=..., msg=..., **details)`
- `send_webhook({"event": "INVARIANT_FAIL", ...})`
- Throttling per `invariant_id:position_key`

---

### market_data.py

**Призначення**: Утиліти для роботи з ринковими даними (aggregated.csv)

#### Основні функції

```python
configure(env)
# Ініціалізація залежностей

load_df_sorted() -> pd.DataFrame
# Завантажує aggregated.csv та нормалізує схему
# - Нормалізує Timestamp до UTC
# - Створює price колонку (ClosePrice/AvgPrice/Close fallback)
# - Заповнює HiPrice/LowPrice (якщо відсутні)
# - Сортує за Timestamp
# - Повертає порожній DataFrame при schema issues (robust)

locate_index_by_ts(df, ts) -> int
# Знаходить індекс рядка за timestamp (minute resolution)
# Використовується для синхронізації з PEAK подіями
```

#### Особливості

- **Robust loader**: повертає порожній DataFrame при schema mismatch
- **Schema tolerance**: підтримує різні варіанти назв колонок (ClosePrice/AvgPrice/Close)
- **Fallback логіка**: якщо HiPrice/LowPrice відсутні → використовує price
- Витягнуто з `executor.py` для покращення тестування та переусадності

---

### notifications.py

**Призначення**: Логування та вебхуки

#### Функції

- `log_event(action, **fields)` — додає JSON-рядок до `EXEC_LOG`
- `append_line_with_cap(path, line, cap)` — запис з обмеженням `LOG_MAX_LINES`
- `send_webhook(payload)` — POST до `N8N_WEBHOOK_URL` з basic auth
- `iso_utc(dt)` — ISO8601 timestamp

#### Формат лога

```json
{"ts": "2025-01-13T20:00:00+00:00", "source": "executor", "action": "ENTRY_PLACED", "symbol": "BTCUSDC", ...}
```

---

### price_snapshot.py

**Призначення**: In-memory кеш mid-price для зменшення redundant bookTicker API викликів

#### Основні функції

```python
configure(log_event_fn)
# Ініціалізація залежностей

class PriceSnapshot:
    freshness_sec() -> float
    # Повертає вік snapshot в секундах

    is_fresh(max_age_sec) -> bool
    # Перевіряє чи snapshot актуальний

    refresh(symbol, get_mid_price_fn, throttle_sec, source) -> bool
    # Оновлює snapshot з throttling

    get_price() -> Optional[float]
    # Повертає cached mid-price або None
```

#### Особливості

- **Singleton pattern**: один екземпляр на процес
- **Throttled refresh**: викликає `get_mid_price()` тільки якщо snapshot stale
- **Споживачі**: SL watchdog, trailing fallback, margin_guard
- Подібна архітектура до `exchange_snapshot.py`

---

### reporting.py

**Призначення**: Генерація trade reports (Reporting Spec v1)

#### Основні функції

```python
write_trade_open(pos, ts, symbol) -> None
# Записує trade open подію в /data/reports/trades.jsonl

write_trade_close(pos, ts, symbol, reason) -> None
# Записує trade close подію

_exit_type(reason) -> str
# Класифікує тип виходу: FAILSAFE_FLATTEN, EXIT_CLEANUP, MISSING,
# ABORTED, NORMAL_TRAIL, NORMAL_TP1, NORMAL_TP2, NORMAL_TP3, NORMAL
```

#### Trade Report Schema

```json
{
  "trade_key": "LIVE_2025-01-13T20:00:00Z",
  "open_ts": "2025-01-13T20:00:00Z",
  "close_ts": "2025-01-13T20:05:00Z",
  "symbol": "BTCUSDC",
  "side": "LONG",
  "qty": 0.001,
  "entry_price": 95000.0,
  "sl_price": 94800.0,
  "tp1_price": 95200.0,
  "tp2_price": 95400.0,
  "exit_type": "NORMAL_TP2",
  "close_reason": "TP2"
}
```

#### Особливості

- **Best-effort, read-only**: ніколи не блокує виконання
- **Детермінований**: один trade = один запис
- Записує JSONL у `/data/reports/trades.jsonl`
- Використовується для offline аналізу та fee enrichment

---

### risk_math.py

**Призначення**: Математичні утиліти для ризик-менеджменту

#### Функції

```python
floor_to_step(x, step) -> float
# Округлення вниз до кроку (qty/price)

ceil_to_step(x, step) -> float
# Округлення вгору

round_nearest_to_step(x, step) -> float
# Округлення до найближчого

fmt_price(p) -> str
# Форматування ціни з урахуванням TICK_SIZE

fmt_qty(q) -> str
# Форматування quantity з урахуванням QTY_STEP (trim trailing zeros)

round_qty(x) -> float
# Округлення qty вниз

split_qty_3legs_validate(qty_total_r) -> (qty1, qty2, qty3)
# Розбиття на 3 ноги: 33%/33%/34% з деградацією до 50%/50%/0% якщо qty мала

split_qty_3legs_place(qty_total_r) -> (qty1, qty2, qty3)
# Аналогічно для place_exits
```

#### Особливості

- Всі обчислення через `Decimal` для детермінованості
- `split_qty_3legs` працює в цілих "step units" для уникнення float-артефактів

---

### state_store.py

**Призначення**: Менеджер персистентного стану виконавця

#### Структура стану

```python
{
  "meta": {
    "seen_keys": [...],      # дедуплікація подій
    "dedup_fp": "...",       # fingerprint алгоритму
    "boot_ts": "ISO8601"
  },
  "position": {              # активна позиція або None
    "mode": "live",
    "side": "LONG",
    "status": "OPEN_FILLED",
    "qty": 0.001,
    "entry": 95000.0,
    "order_id": 123456,
    "client_id": "EX_...",
    "orders": {              # exit ордера
      "sl": 789,
      "tp1": 790,
      "tp2": 791,
      "qty1": 0.0003,
      "qty2": 0.0003,
      "qty3": 0.0004,
      "sl_prev": 788        # старий SL після TP1→BE (v2.2+)
    },
    "prices": {
      "entry": 95000.0,
      "sl": 94800.0,        # оновлюється до be_stop після TP1 (v2.2+)
      "tp1": 95200.0,
      "tp2": 95400.0
    },
    "trail_active": true,
    "trail_sl_price": 95100.0,
    "tp1_done": false,       # flag TP1 заповнення
    "tp1_be_disabled": false, # flag після max_attempts (v2.2+)
    "close_cleanup_next_s": 1234567890.0,  # throttle cleanup (v2.1+)
    ...
  },
  "last_closed": {...},      # остання закрита позиція
  "cooldown_until": 1234567890.0,
  "lock_until": 1234567890.0,
  "margin": {                # margin стан (якщо margin mode)
    "borrowed_assets": {"USDC": 100.0},
    "borrowed_by_trade": {},
    "active_trade_key": "..."
  }
}
```

#### Схема aggregated.csv v2

```
Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice
2025-01-13T20:00:00Z,123,1.5,0.01,0.8,0.7,95000.0,95010.0,95020.0,94990.0
```

---

### trail.py

**Призначення**: Логіка trailing stop на основі swing extremes

#### Функції

```python
_read_last_close_prices_from_agg_csv(path, n_rows) -> list[float]
# Читає останні N ClosePrice з aggregated.csv (для bar-close confirmation)

_read_last_low_prices_from_agg_csv(path, n_rows) -> list[float]
# Читає останні N LowPrice (для LONG swing detection)

_read_last_high_prices_from_agg_csv(path, n_rows) -> list[float]
# Читає останні N HiPrice (для SHORT swing detection)

_find_last_fractal_swing(series, lr, kind) -> Optional[float]
# Знаходить останній swing point з простою фрактал-логікою:
#   low:  x[i] < x[i-1..i-lr] and x[i] < x[i+1..i+lr]
#   high: x[i] > x[i-1..i-lr] and x[i] > x[i+1..i+lr]

_trail_desired_stop_from_agg(pos) -> Optional[float]
# Обчислює бажаний trailing stop на основі останнього swing:
#   LONG: stop = swing_low - TRAIL_SWING_BUFFER_USD
#   SHORT: stop = swing_high + TRAIL_SWING_BUFFER_USD
# Підтримує trail_wait_confirm: чекає поки bar ClosePrice пройде ref_price
```

#### Конфігурація

```python
TRAIL_SOURCE=AGG                    # "AGG" (aggregated.csv) або "BINANCE" (bookTicker)
TRAIL_SWING_LOOKBACK=240            # кількість рядків для пошуку swing
TRAIL_SWING_LR=2                    # L/R для fractal (мінімум 2 бари з кожного боку)
TRAIL_SWING_BUFFER_USD=15.0         # буфер від swing до stop
TRAIL_CONFIRM_BUFFER_USD=0.0        # буфер для bar-close confirmation
```

#### Особливості

- **Fail-loud** на schema mismatch (header != AGG_HEADER_V2)
- **Fail-closed** на missing file (startup/rotation)
- Використовує `read_tail_lines` для performance (не сканує весь файл)

---

## Утиліти (tools/)

Директорія `tools/` містить автономні скрипти для offline обробки та аналізу trade reports.

### enrich_trades_with_fees.py

**Призначення**: Offline збагачення trade reports комісіями з Binance API

#### Використання

```bash
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TRADE_MODE=spot  # або margin

# Базовий запуск (читає /data/reports/trades.jsonl → пише /data/reports/trades_enriched.jsonl)
python tools/enrich_trades_with_fees.py

# Кастомні шляхи
python tools/enrich_trades_with_fees.py \
  --input /path/to/trades.jsonl \
  --output /path/to/enriched.jsonl
```

#### Що робить

1. Читає `trades.jsonl` (TradeReportInternal schema)
2. Для кожного trade:
   - Витягує всі myTrades для відповідних orderId через Binance API
   - Обчислює `total_fee_quote` (комісії в quote asset, наприклад USDC)
   - Обчислює `realized_pnl` (з урахуванням комісій)
3. Додає поля `fee_enriched`, `fee_enriched_ts`, `total_fee_quote`, `realized_pnl`
4. Записує у `trades_enriched.jsonl`

#### Policy A (Strict Mode)

- **Вимагає** щоб усі orderId мали myTrades записи
- Якщо будь-який orderId не має trades → trade пропускається (`skipped_no_trades`)
- Гарантує 100% покриття для успішно enriched trades

#### Особливості

- **Atomic write**: використовує `.tmp` + `os.replace()`
- **Ідемпотентний**: може бути запущений повторно (перезаписує output)
- **Cron-safe**: підходить для періодичного запуску
- **Rate limit aware**: має retry логіку для 429 помилок

---

### make_manager_report.py

**Призначення**: Генерація manager звітів з enriched trades

#### Використання

```bash
# Базовий запуск (читає /data/reports/trades_enriched.jsonl → пише /data/reports/manager_report.md)
python tools/make_manager_report.py

# Кастомні шляхи
python tools/make_manager_report.py \
  --input /path/to/trades_enriched.jsonl \
  --output /path/to/report.md
```

#### Що генерує

Markdown звіт з наступними секціями:

1. **Summary**
   - Total trades
   - Win rate
   - Total realized PnL (gross/net з комісіями)
   - Average trade duration
   - Best/worst trade

2. **Breakdown by Exit Type**
   - Статистика по кожному типу виходу (TP1, TP2, TRAIL, FAILSAFE, тощо)
   - Win rate та PnL per exit type

3. **Recent Trades (last 10)**
   - Таблиця останніх 10 trades з ключовими метриками

4. **Daily Performance**
   - Aggregate PnL по датам
   - Daily win rate

#### Особливості

- **Read-only**: тільки читає enriched trades
- **Cron-safe**: безпечний для періодичного запуску
- **Human-readable**: генерує markdown для легкого читання
- **Atomic write**: використовує `.tmp` + `os.replace()`

---

### Workflow для reporting

Рекомендований workflow для генерації звітів:

```bash
# 1. Executor генерує trades.jsonl під час роботи (автоматично)
python executor.py

# 2. Періодично (наприклад, раз на день через cron) збагачуємо комісіями
python tools/enrich_trades_with_fees.py

# 3. Генеруємо manager звіт
python tools/make_manager_report.py

# 4. Звіт доступний у /data/reports/manager_report.md
cat /data/reports/manager_report.md
```

Файли у `/data/reports/`:
- `trades.jsonl` — raw trade events (генерується executor.py через reporting.py)
- `trades_enriched.jsonl` — збагачені комісіями (enrich_trades_with_fees.py)
- `manager_report.md` — фінальний звіт (make_manager_report.py)

---

## Конфігурація

Всі налаштування через environment variables:

### Основні

```bash
# Входи/виходи
DELTASCOUT_LOG=/data/logs/deltascout.log   # лог DeltaScout
AGG_CSV=/data/feed/aggregated.csv          # aggregated market data
STATE_FN=/data/state/executor_state.json   # стан executor
EXEC_LOG=/data/logs/executor.log           # лог executor

# Cleanup & TP1→BE (v2.1+, v2.2+)
CLOSE_CLEANUP_RETRY_SEC=2.0                # throttle між cleanup спробами
TP1_BE_MAX_ATTEMPTS=5                       # max спроб TP1→BE переходу
SL_RECON_FRESH_SEC=60                       # freshness gate для SL fallback (sec)

# Символ та sizing
SYMBOL=BTCUSDC
QTY_USD=100.0
QTY_STEP=0.00001
MIN_QTY=0.00001
MIN_NOTIONAL=5.0
TICK_SIZE=0.01

# Ризик-модель
SL_PCT=0.002                # stop-loss як % від entry
SWING_MINS=180              # lookback для swing stop
TP_R_LIST=1,2               # R-multiples для TP1, TP2

# Таймінги
POLL_SEC=5.0
COOLDOWN_SEC=180
LOCK_SEC=15
```

### Binance API

```bash
BINANCE_BASE_URL=https://api.binance.com
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
RECV_WINDOW=5000
```

### Режим торгівлі

```bash
TRADE_MODE=spot   # spot | margin

# Margin (якщо TRADE_MODE=margin)
MARGIN_ISOLATED=FALSE                      # TRUE для isolated, FALSE для cross
MARGIN_SIDE_EFFECT=AUTO_BORROW_REPAY       # або NO_SIDE_EFFECT
MARGIN_BORROW_MODE=manual                  # manual | auto
MARGIN_AUTO_REPAY_AT_CANCEL=false
```

### Entry/Exit

```bash
ENTRY_OFFSET_USD=0.5
ENTRY_MODE=LIMIT_THEN_MARKET   # LIMIT_ONLY | LIMIT_THEN_MARKET | MARKET_ONLY
LIVE_ENTRY_TIMEOUT_SEC=90
EXITS_RETRY_EVERY_SEC=15
```

### Trailing

```bash
TRAIL_ACTIVATE_AFTER_TP2=true
TRAIL_SOURCE=AGG
TRAIL_SWING_LOOKBACK=240
TRAIL_SWING_LR=2
TRAIL_SWING_BUFFER_USD=15.0
TRAIL_CONFIRM_BUFFER_USD=0.0
TRAIL_UPDATE_EVERY_SEC=20
```

### Watchdog (SL/TP Safety)

```bash
SL_WATCHDOG_GRACE_SEC=3        # Grace period перед активацією SL watchdog
SL_WATCHDOG_RETRY_SEC=5        # Retry інтервал для market fallback
```

### Інваріанти

```bash
INVAR_ENABLED=1
INVAR_EVERY_SEC=20
INVAR_THROTTLE_SEC=600
INVAR_GRACE_SEC=15
I13_GRACE_SEC=300
I13_ESCALATE_SEC=180
I13_EXCHANGE_CHECK=true
I13_KILL_ON_DEBT=false
```

### Вебхуки

```bash
N8N_WEBHOOK_URL=https://n8n.example.com/webhook/executor
N8N_BASIC_AUTH_USER=user
N8N_BASIC_AUTH_PASSWORD=pass
```

---

## Режими роботи

### 1. Spot режим

```bash
TRADE_MODE=spot
```

- Найпростіший режим
- Немає запозичень
- Працює тільки з наявними балансами

### 2. Cross Margin режим

```bash
TRADE_MODE=margin
MARGIN_ISOLATED=FALSE
MARGIN_BORROW_MODE=manual   # або auto
```

- **Auto mode**: Binance автоматично borrow/repay через `MARGIN_SIDE_EFFECT=AUTO_BORROW_REPAY`
- **Manual mode**: Executor викликає `margin_borrow()` / `margin_repay()` через margin_guard hooks

### 3. Isolated Margin режим

```bash
TRADE_MODE=margin
MARGIN_ISOLATED=TRUE
MARGIN_BORROW_MODE=manual
```

- Ізольований ризик на symbol
- Вимагає `symbol` параметр у всіх margin API calls

---

## Безпека та надійність

### 1. Дедуплікація

- Стабільний ключ: `action|ts_minute|kind|price_rounded`
- Fingerprint алгоритму для інвалідації при змінах
- Bootstrap з tail лога при старті

### 2. State Guards

- **Cooldown**: чекає `COOLDOWN_SEC` після закриття
- **Lock**: блокує `LOCK_SEC` після відкриття (захист від дублікатів при рестартах)
- **Single-position**: ігнорує нові PEAK поки позиція активна

### 3. Plan B

Якщо entry не fill вчасно:
- Перевіряє актуальність через `bookTicker`
- Якщо відхилення > `PLANB_MAX_DEV_R_MULT` або ціна вже за TP1 → abort
- Fallback to MARKET якщо `ENTRY_MODE=LIMIT_THEN_MARKET`

### 4. Failsafe

Якщо exits не розміщуються після `FAILSAFE_EXITS_MAX_TRIES`:
- Якщо `FAILSAFE_FLATTEN=true` → закриває MARKET ордером
- Інакше → halt (позиція залишається)

### 5. Інваріанти

13 детекторів аномалій стану з throttling та severity (WARN/ERROR)

### 6. Cleanup Guards (v2.1+)

- **AK-47 Contract**: `_finalize_close()` ЗАВЖДИ викликає `_close_slot()` навіть якщо cleanup fails
- **Throttling**: cleanup не спамить API через `CLOSE_CLEANUP_RETRY_SEC` (default 2s)
- **Best-effort**: cleanup wrapped у `with suppress(Exception)` — ніколи не блокує close

### 6a. Cleanup Throttling Contract (v2.2+)

When `position.exit_cleanup_pending` is active and `now < exit_cleanup_next_s`, executor continues passive reconciliation (status polling / snapshot / recon-derived SL_DONE) and may finalize close when SL is confirmed filled.

**Blocked (active mutations):**
- `flatten_market` (SL/TP watchdog market fallback)
- `cancel_order` / `_cancel_ignore_unknown` (trailing maintenance, synthetic trailing activation)
- BE transition (`tp1_be_pending` tick)
- Trail maintenance (`trail_active` cancel/replace SL)
- `sl_prev` orphan cancel

**NOT blocked (passive reconciliation):**
- `check_order_status` polling (SL/TP status detection)
- `exchange_snapshot` refresh (openOrders)
- `price_snapshot` refresh (mid-price via bookTicker)
- `_finalize_close()` / `_close_slot()` when SL confirmed FILLED
- State transitions based on already-filled facts

**Rationale**: avoids races and conflicting mutations while cancel-retry throttling is in progress; active actions resume after throttling window ends.

### 7. TP1→BE Safety (v2.2+)

- **Max attempts**: `TP1_BE_MAX_ATTEMPTS` (default 5) запобігає infinite loops
- **Strict verification**: old SL перевіряється на CANCELED/REJECTED/EXPIRED/NOT_FOUND перед new SL
- **FILLED handling**: якщо old SL filled → abort transition, normal SL-filled path обробить
- **Insufficient balance**: retry якщо -2010 error (old SL ще блокує qty)
- **State sync**: оновлює `prices["sl"]`, `sl_status_next_s`, `sl_done`, `sl_prev`
- **1h cooldown**: після max attempts → `tp1_be_disabled=True` на 3600s

### 8. Атомарний запис стану

```python
tmp = STATE_FN + ".tmp"
with open(tmp, "w") as f:
    json.dump(st, f)
os.replace(tmp, STATE_FN)  # atomic на POSIX
```

### 9. Emergency Shutdown Mode (v2.3+) 🆕

Оператор-контрольований graceful shutdown з reconciliation:

**Компоненти:**
1. **Alert on First Failure** — негайне сповіщення через webhook при помилці `save_state()`
2. **Emergency Shutdown Trigger** — оператор створює файл `/data/state/emergency_shutdown.flag`
3. **Reconciliation-First Shutdown** — перевірка статусів ордерів перед очисткою позиції
4. **Sleep Mode** — бот ігнорує нові сигнали до wake up

**Workflow:**
```bash
# 1. Оператор отримує alert "🚨 SAVE_STATE_FAILURE"
# 2. SSH на сервер:
touch /data/state/emergency_shutdown.flag
# 3. Бот:
#    - Перевіряє статус SL/TP1/TP2 на біржі
#    - Викликає margin repay
#    - Створює backup state
#    - Входить у sleep mode
# 4. Відновлення:
touch /data/state/wake_up.flag
```

**Принципи:**
- **Fail-Aware**: алерт оператору, але не halt
- **Human-in-the-Loop**: оператор вирішує коли shutdown
- **Reconciliation-First**: перевірка ордерів перед фіналізацією
- **Fail-Safe**: при сумнівах — передача контролю людині

### 10. Manual Exchange Clear (v2.3+) 🆕

Можливість ручного закриття позиції з телефону через Binance App:

**Налаштування:**
```bash
export I13_CLEAR_STATE_ON_EXCHANGE_CLEAR=true
```

**Workflow:**
1. 📱 Binance App → Sell BTC (Market)
2. 📱 Open Orders → Cancel All
3. ⏳ Чекати ~5 хв (sync throttle)
4. ✅ Бот автоматично:
   - Виявляє `open_orders = []`
   - Перевіряє `_exchange_position_exists() = False`
   - Логує `POSITION_CLEARED_BY_EXCHANGE`
   - Викликає margin repay
   - Очищає позицію
   - Чекає новий PEAK

---

## Встановлення та запуск

### Залежності

```bash
pip install pandas requests
```

### Запуск

```bash
export SYMBOL=BTCUSDC
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TRADE_MODE=spot
export QTY_USD=100.0

python executor.py
```

### Структура даних

```
/data/
├── logs/
│   ├── deltascout.log       # вхідний лог (читається)
│   └── executor.log         # вихідний лог (пишеться)
├── state/
│   ├── executor_state.json  # основний стан
│   └── invariants_state.json # metadata інваріантів
├── feed/
│   └── aggregated.csv       # ринкові дані для trailing
└── reports/                 # trade reports та звіти
    ├── trades.jsonl         # raw trade events (reporting.py)
    ├── trades_enriched.jsonl # збагачені комісіями (enrich_trades_with_fees.py)
    └── manager_report.md    # manager звіт (make_manager_report.py)
```

---

## Тестування

```bash
# Запустити всі тести
python -m pytest test/

# Окремі модулі
python -m pytest test/test_executor.py
python -m pytest test/test_state_store.py
python -m pytest test/test_binance_api_smoke.py
python -m pytest test/test_invariants_module.py
python -m pytest test/test_margin_policy.py
python -m pytest test/test_margin_policy_isolated.py
python -m pytest test/test_trail.py

# Watchdog тести
python -m pytest test/test_tp_watchdog.py -v
python -m pytest test/test_sl_watchdog.py -v

# Snapshot тести
python -m pytest test/test_exchange_snapshot.py
python -m pytest test/test_price_snapshot.py

# Інші функціональні тести
python -m pytest test/test_market_data.py
python -m pytest test/test_event_dedup.py
python -m pytest test/test_risk_math.py
python -m pytest test/test_notifications.py
python -m pytest test/test_enrich_trades_with_fees.py

# Запуск з verbose output
python -m pytest -v test/

# Запуск з print statements
python -m pytest -s test/test_executor.py
```

---

## Ліцензія

Проприєтарний код. Всі права захищені.

---

## Підтримка

Для питань та bug reports створіть issue в репозиторії або зверніться до команди розробки.
