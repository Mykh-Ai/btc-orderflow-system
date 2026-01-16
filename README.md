# Executor

**Executor** — автоматизований торговельний виконавець для сигналів DeltaScout PEAK. Система забезпечує повний цикл виконання угод: від отримання сигналу до закриття позиції з підтримкою trailing stop, маржинальної торгівлі та комплексних інваріантів стану.

## Зміст

- [Огляд](#огляд)
- [Архітектура](#архітектура)
- [Основний модуль: executor.py](#основний-модуль-executorpy)
- [Допоміжні модулі](#допоміжні-модулі)
  - [baseline_policy.py](#baseline_policypy)
  - [binance_api.py](#binance_apipy)
  - [event_dedup.py](#event_deduppy)
  - [exchange_snapshot.py](#exchange_snapshotpy)
  - [exit_safety.py](#exit_safetypy)
  - [exits_flow.py](#exits_flowpy)
  - [invariants.py](#invariantspy)
  - [margin_guard.py](#margin_guardpy)
  - [margin_policy.py](#margin_policypy)
  - [market_data.py](#market_datapy)
  - [notifications.py](#notificationspy)
  - [risk_math.py](#risk_mathpy)
  - [state_store.py](#state_storepy)
  - [trail.py](#trailpy)
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

Ключові принципи:
- **Ізоляція даних**: Executor пише лише у власні файли стану/логів
- **Дедуплікація**: Стабільна система дедуплікації подій на основі ключа `action|ts|min|kind|price`
- **Відмовостійкість**: Cooldown після закриття, блокування після відкриття, ретраї для exits
- **Детермінованість**: Всі розрахунки через `Decimal` для уникнення float-артефактів

---

## Архітектура

```
Executor/
├── executor.py              # Головний виконавчий механізм
├── executor_mod/            # Модульна архітектура
│   ├── __init__.py
│   ├── baseline_policy.py   # Базові стратегії управління позицією
│   ├── binance_api.py       # REST API адаптер
│   ├── event_dedup.py       # Дедуплікація подій
│   ├── exchange_snapshot.py # Кеш стану біржі
│   ├── exit_safety.py       # Контроль безпечного закриття позицій
│   ├── exits_flow.py        # Логіка виходів
│   ├── invariants.py        # Детектори інваріантів
│   ├── margin_guard.py      # Хуки маржинальної торгівлі
│   ├── margin_policy.py     # Політика маржі
│   ├── market_data.py       # Ринкові дані
│   ├── notifications.py     # Логування та вебхуки
│   ├── risk_math.py         # Ризик-менеджмент математика
│   ├── state_store.py       # Менеджер стану
│   └── trail.py             # Trailing stop логіка
└── test/                    # Тести
    ├── test_executor.py
    ├── test_binance_api_smoke.py
    ├── test_state_store.py
    ├── test_notifications.py
    ├── test_event_dedup.py
    ├── test_invariants_*.py
    ├── test_margin_*.py
    └── test_trail.py
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

---

## Допоміжні модулі

### baseline_policy.py

**Призначення**: Модуль для реалізації базових стратегій управління позицією та ризиком. Забезпечує fallback-логіку для випадків, коли основна стратегія недоступна або виникають нестандартні ситуації. Може використовуватись для тестування та порівняння з основними алгоритмами.

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

**Призначення**: Модуль контролю безпечного закриття позицій. Відстежує умови, за яких вихід з позиції може бути ризикованим (наприклад, нестабільність API, аномалії ринку) та застосовує додаткові перевірки або обмеження для мінімізації втрат.

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
      "qty3": 0.0004
    },
    "prices": {
      "entry": 95000.0,
      "sl": 94800.0,
      "tp1": 95200.0,
      "tp2": 95400.0
    },
    "trail_active": true,
    "trail_sl_price": 95100.0,
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

## Конфігурація

Всі налаштування через environment variables:

### Основні

```bash
# Входи/виходи
DELTASCOUT_LOG=/data/logs/deltascout.log   # лог DeltaScout
AGG_CSV=/data/feed/aggregated.csv          # aggregated market data
STATE_FN=/data/state/executor_state.json   # стан executor
EXEC_LOG=/data/logs/executor.log           # лог executor

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

### 6. Атомарний запис стану

```python
tmp = STATE_FN + ".tmp"
with open(tmp, "w") as f:
    json.dump(st, f)
os.replace(tmp, STATE_FN)  # atomic на POSIX
```

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
└── feed/
    └── aggregated.csv       # ринкові дані для trailing
```

---

## Тестування

```bash
# Запустити всі тести
python -m pytest test/

# Окремі модулі
python -m pytest test/test_state_store.py
python -m pytest test/test_binance_api_smoke.py
python -m pytest test/test_invariants_module.py
python -m pytest test/test_margin_policy.py
python -m pytest test/test_trail.py
```

---

## Ліцензія

Проприєтарний код. Всі права захищені.

---

## Підтримка

Для питань та bug reports створіть issue в репозиторії або зверніться до команди розробки.
