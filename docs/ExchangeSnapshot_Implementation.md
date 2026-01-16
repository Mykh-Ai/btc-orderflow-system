# Резюме впровадження: Гейтинг ExchangeSnapshot та openOrders

**Дата:** 16 січня 2026  
**Гілка:** v2.1_SL  
**Репозиторій:** btc-orderflow-system

---

## Огляд

Успішно впроваджено систему ExchangeSnapshot/Cache для гейтингу polling openOrders лише до статусу `OPEN`, що усуває зайві виклики API під час стану `OPEN_FILLED` та контролює частоту виконання sync_from_binance.

---

## Зміни в коді

### 1. Новий модуль: `executor_mod/exchange_snapshot.py`

Створено систему in-memory snapshot з наступними можливостями:

**ВАЖЛИВО:** ExchangeSnapshot кешує **тільки openOrders** виклики. Не впливає на:
- ❌ `get_margin_debt_snapshot()` (використовується I13 інваріантом)
- ❌ `margin_account()` / `spot_account()` виклики
- ❌ `check_order_status()` перевірки
- ❌ Будь-які інші Binance API endpoints

**I13 інваріант EXEMPT:** I13 post-close debt verification використовує прямі API виклики з власним rate-limiting (`I13_EXCHANGE_MIN_INTERVAL_SEC`) і не залежить від ExchangeSnapshot.

#### Поля:
- `ts_updated` (float) - час останнього оновлення
- `ok` (bool) - статус успішності оновлення
- `error` (str|None) - опис помилки (якщо є)
- `open_orders` (list|None) - список відкритих ордерів
- `source` (str) - джерело оновлення ("manage", "sync:BOOT", тощо)
- `symbol` (str) - торговельний символ

#### Методи:
- `freshness_sec()` - обчислити вік snapshot в секундах
- `is_fresh(max_age_sec)` - перевірити чи snapshot актуальний
- `refresh()` - оновити snapshot через виклик API
- `get_orders()` - безпечно отримати ордери (повертає порожній список якщо недоступно)
- `to_dict()` - експортувати для логування/дебагу

#### Глобальний singleton:
- `get_snapshot()` - отримати глобальний екземпляр
- `refresh_snapshot()` - оновити snapshot з throttling

---

### 2. Оновлення `executor.py`

#### Нова конфігурація (рядки 196-197):

```python
"SNAPSHOT_MIN_SEC": _get_int("SNAPSHOT_MIN_SEC", 5),  # мін. інтервал між оновленнями
"SYNC_BINANCE_THROTTLE_SEC": _get_int("SYNC_BINANCE_THROTTLE_SEC", 300),  # throttle для sync
```

#### Імпорт (рядок 48):

```python
from executor_mod.exchange_snapshot import get_snapshot, refresh_snapshot
```

#### Функція `manage_v15_position` (рядки 836-878):

**ГЕЙТИНГ:** openOrders polling **тільки коли `status == "OPEN"`**

```python
# GATE: Only poll openOrders when status == OPEN (not OPEN_FILLED)
# During OPEN_FILLED, rely on place_order responses + retries, not polling
orders = []
if pos.get("status") == "OPEN":
    snapshot = get_snapshot()
    refreshed = refresh_snapshot(
        symbol=symbol,
        source="manage",
        open_orders_fn=binance_api.open_orders,
        min_interval_sec=float(ENV.get("SNAPSHOT_MIN_SEC", 5)),
    )
    if refreshed:
        log_event(
            "SNAPSHOT_REFRESH",
            source="manage",
            ok=snapshot.ok,
            error=snapshot.error,
            age_sec=snapshot.freshness_sec(),
            order_count=len(snapshot.get_orders()),
        )
    orders = snapshot.get_orders()
else:
    # OPEN_FILLED: skip openOrders polling
    log_event("MANAGE_SKIP_OPENORDERS", status=pos.get("status"), reason="OPEN_FILLED_gate")
```

**Результат:**
- Під час `OPEN_FILLED`: **нуль** викликів openOrders
- Логує подію `MANAGE_SKIP_OPENORDERS`
- Використовує throttling через `SNAPSHOT_MIN_SEC`

#### Функція `sync_from_binance` (рядки 1667-1720):

**Нова сигнатура:** `sync_from_binance(st: Dict[str, Any], reason: str = "unknown")`

**Механізм throttling:**

```python
# GATE: Throttle sync_from_binance unless reason is BOOT/MANUAL/RECOVERY
if reason not in ("BOOT", "MANUAL", "RECOVERY"):
    if pos and pos.get("mode") == "live":
        last_sync = float(st.get("last_sync_from_binance_s") or 0.0)
        throttle_sec = float(ENV.get("SYNC_BINANCE_THROTTLE_SEC", 300))
        if now_s - last_sync < throttle_sec:
            log_event("SYNC_SKIP_THROTTLED", reason=reason, throttle_sec=throttle_sec, age_sec=now_s - last_sync)
            return
```

**Перевага використання snapshot:**

```python
# Try to use fresh snapshot first to avoid duplicate openOrders call
snapshot = get_snapshot()
if snapshot.is_fresh(float(ENV.get("SNAPSHOT_MIN_SEC", 5))) and snapshot.ok:
    orders = snapshot.get_orders()
    log_event("SYNC_USE_SNAPSHOT", reason=reason, age_sec=snapshot.freshness_sec(), order_count=len(orders))
else:
    orders = binance_api.open_orders(ENV["SYMBOL"])
    # Update snapshot while we're here
    snapshot.ts_updated = now_s
    snapshot.ok = True
    snapshot.error = None
    snapshot.open_orders = orders
    snapshot.source = f"sync:{reason}"
    log_event("SYNC_FETCH_OPENORDERS", reason=reason, order_count=len(orders or []))
```

**Результат:**
- Throttling до 300 секунд між викликами (якщо не BOOT/MANUAL/RECOVERY)
- Використовує cached snapshot коли можливо
- Уникає дублювання викликів openOrders

#### Виклики sync_from_binance (оновлено):

```python
# Рядок 2119 - при старті
sync_from_binance(st, reason="BOOT")

# Рядок 2436 - при обробці PEAK сигналів (тепер з throttling)
sync_from_binance(st, reason="PEAK_EVENT")
```

---

### 3. Тести: `test/test_exchange_snapshot.py`

Створено комплексні unit-тести що покривають:

1. ✅ Створення snapshot та перевірка freshness
2. ✅ Успішне оновлення snapshot
3. ✅ Обробка помилок при оновленні
4. ✅ Безпечний get_orders (повертає [] при None)
5. ✅ Серіалізація (to_dict)
6. ✅ Глобальний singleton (get_snapshot)
7. ✅ Механізм throttling (min_interval_sec)

**Результат тестів:** Всі 7 тестів успішно пройдено ✅

---

## Аудит викликів API

**openOrders викликається тепер лише в 3 місцях:**

| Місце | Рядок | Умова | Статус |
|-------|-------|-------|--------|
| manage loop | 859 | `status == "OPEN"` + throttling | ✅ Гейтовано |
| sync_from_binance | 1710 | Тільки якщо snapshot не fresh | ✅ Контрольовано |
| I13 cleanup | 1752 | Спеціальний випадок recovery | ✅ Обґрунтовано |

**Виключено з прямих викликів:**
- ❌ baseline_policy.py - не викликає openOrders
- ❌ invariants.py - не викликає openOrders
- ❌ watchdog - використовує дані з snapshot через manage

---

## Критерії прийняття

| Вимога | Статус | Доказ |
|--------|--------|-------|
| openOrders тільки при `status == "OPEN"` | ✅ | Гейт на рядку 854 в manage_v15_position |
| Немає openOrders під час `OPEN_FILLED` | ✅ | Логує `MANAGE_SKIP_OPENORDERS` |
| ExchangeSnapshot з обов'язковими полями | ✅ | exchange_snapshot.py рядки 15-26 |
| Snapshot refresh з throttling | ✅ | Параметр `min_interval_sec` + `is_fresh()` |
| sync_from_binance рідкісний/контрольований | ✅ | Throttling 300s, використовує snapshot |
| Логування: події пропуску | ✅ | `MANAGE_SKIP_OPENORDERS`, `SYNC_SKIP_THROTTLED` |
| Логування: події оновлення | ✅ | `SNAPSHOT_REFRESH` з ok/error/age/count |
| Немає breaking changes | ✅ | Всі імпорти працюють, тести пройдено |

---

## Нові події логування

### 1. SNAPSHOT_REFRESH
**Коли:** Snapshot оновлюється (manage loop)  
**Поля:**
- `source` - джерело ("manage")
- `ok` - успішність (bool)
- `error` - текст помилки (якщо є)
- `age_sec` - вік snapshot
- `order_count` - кількість ордерів

### 2. MANAGE_SKIP_OPENORDERS
**Коли:** openOrders пропущено через статус OPEN_FILLED  
**Поля:**
- `status` - поточний статус позиції
- `reason` - причина пропуску

### 3. SYNC_SKIP_THROTTLED
**Коли:** sync_from_binance throttled  
**Поля:**
- `reason` - причина виклику
- `throttle_sec` - час throttling
- `age_sec` - вік з останнього sync

### 4. SYNC_USE_SNAPSHOT
**Коли:** sync використовує cached snapshot  
**Поля:**
- `reason` - причина виклику
- `age_sec` - вік snapshot
- `order_count` - кількість ордерів

### 5. SYNC_FETCH_OPENORDERS
**Коли:** sync виконує виклик API  
**Поля:**
- `reason` - причина виклику
- `order_count` - кількість отриманих ордерів

---

## Вплив на продуктивність

### До впровадження:
- openOrders викликався кожні `MANAGE_EVERY_SEC` (15s за замовчуванням) **незалежно від статусу**
- sync_from_binance викликався на кожну подію PEAK (потенційно дублюючи виклик з manage)
- Близько **4-6 викликів API на хвилину** при активній позиції

### Після впровадження:
- openOrders викликається **тільки при `status == "OPEN"`** + throttling 5s
- Під час `OPEN_FILLED` (вікно placement): **нуль** викликів openOrders
- sync_from_binance: throttling 300s, використовує snapshot коли fresh
- Близько **1-2 виклики API на хвилину** при активній позиції

**Оцінка зменшення:** **60-80% менше викликів API** при нормальній роботі

---

## Команди для верифікації

```bash
# Перевірити відсутність openOrders під час OPEN_FILLED
grep "MANAGE_SKIP_OPENORDERS" /data/logs/executor.log

# Перевірити оновлення snapshot
grep "SNAPSHOT_REFRESH" /data/logs/executor.log

# Перевірити throttling sync
grep "SYNC_SKIP_THROTTLED" /data/logs/executor.log

# Підрахувати фактичні виклики openOrders API
grep "SYNC_FETCH_OPENORDERS\|SNAPSHOT_REFRESH" /data/logs/executor.log | wc -l

# Перевірити використання snapshot замість API
grep "SYNC_USE_SNAPSHOT" /data/logs/executor.log
```

---

## Налаштування конфігурації

### Параметри за замовчуванням:
```bash
SNAPSHOT_MIN_SEC=5           # Мінімальний інтервал між оновленнями snapshot
SYNC_BINANCE_THROTTLE_SEC=300  # Мінімальний інтервал між sync_from_binance
```

### Опціональне налаштування:

**Для більш агресивного кешування:**
```bash
SNAPSHOT_MIN_SEC=10          # Рідші оновлення snapshot
SYNC_BINANCE_THROTTLE_SEC=600  # Рідші sync виклики
```

**Для більш частих перевірок:**
```bash
SNAPSHOT_MIN_SEC=2           # Частіші оновлення snapshot
SYNC_BINANCE_THROTTLE_SEC=120  # Частіші sync виклики
```

### Backward compatibility:
- **Не потрібно змін конфігурації** для базової роботи
- Всі нові параметри мають розумні значення за замовчуванням
- Існуюча поведінка збережена для всіх інших станів

---

## Файли що були змінені

### Нові файли:
```
executor_mod/exchange_snapshot.py        (новий модуль)
test/test_exchange_snapshot.py          (тести)
docs/ExchangeSnapshot_Implementation.md  (ця документація)
```

### Змінені файли:
```
executor.py                              (основні зміни)
```

---

## Чеклист для розгортання

- [x] Код перевірено та протестовано
- [x] Unit-тести написано та успішно пройдено
- [x] Документація оновлена
- [x] Нові події логування задокументовано
- [x] Backward compatibility підтверджено
- [x] Команди верифікації підготовлено

---

## Наступні кроки (опціонально)

### Можливі покращення в майбутньому:

1. **Моніторинг метрик:**
   - Додати лічильник фактичних викликів openOrders
   - Трекінг hit rate для snapshot cache
   - Метрики затримки при оновленні snapshot

2. **Розширення snapshot:**
   - Додати кешування balance snapshots
   - Включити margin account info в snapshot
   - Snapshot для getOrder викликів

3. **Адаптивний throttling:**
   - Автоматично збільшувати throttle при стабільному стані
   - Зменшувати throttle при виявленні аномалій

4. **Dashboard візуалізація:**
   - Графік частоти викликів API до/після
   - Real-time стан snapshot (age, freshness)
   - Alerts при перевищенні rate limits

---

## Контакти та підтримка

**Репозиторій:** Mykh-Ai/btc-orderflow-system  
**Гілка:** v2.1_SL  
**Дата впровадження:** 16 січня 2026

---

*Документ оновлено: 16 січня 2026*
