# Аудит Рефакторингу executor.py

**Дата:** 21 січня 2026  
**Версія:** v2.0  
**Поточний розмір:** 3093 рядки

---

## 📊 Підсумкова Статистика

| Метрика | Значення |
|---------|----------|
| **Всього рядків** | 3093 |
| **Рядків коду (у функціях)** | 2995 |
| **ENV конфігурація + imports** | ~98 |
| **Всього функцій** | 36 |

---

## 🎯 Приорітети Рефакторингу

### ТОП-3 Найбільші Функції (1997 рядків = 64.6% файлу)

#### 1. `manage_v15_position()` — **1207 рядків** (39% файлу) 🔴
**Рядки:** 847-2054

**Структура:**
- Рядків коду: 1059
- Коментарів: 65
- Порожніх: 84
- **Вкладених функцій: 6**

**Вкладені функції:**
- `_update_order_fill()` — 61 рядок
- `_close_slot()` — **718 рядків** ⚠️ (найбільша вкладена функція)
- `_is_unknown_order_error()` — **322 рядки** ⚠️
- `_cancel_ignore_unknown()` — 18 рядків
- `_save_state_best_effort()` — 17 рядків
- `_status_is_filled()` — 6 рядків

**Функціональні блоки:**
1. OpenOrders polling + snapshot management
2. Order fill tracking + reporting
3. SL/TP watchdogs
4. Trailing stop logic
5. Position closure + cleanup
6. Error handling + recovery

**Рекомендація:** 
✅ **ВИСОКА ПРИОРИТЕТНІСТЬ** — можна безпечно винести ~800+ рядків

---

#### 2. `main()` — **553 рядки** (17.9% файлу) 🟡
**Рядки:** 2540-3093

**Структура:**
- Основний event loop
- Signal handlers (SIGTERM, SIGINT)
- State initialization
- DeltaScout log parsing
- Entry flow orchestration
- Periodic tasks (invariants, manage)

**Рекомендація:**
✅ **СЕРЕДНЯ ПРИОРИТЕТНІСТЬ** — можна винести ~250-300 рядків

---

#### 3. `sync_from_binance()` — **430 рядків** (13.9% файлу) 🟡
**Рядки:** 2076-2506

**Функціональні блоки:**
1. Throttling logic
2. Snapshot/openOrders fetching
3. Exchange-truth reconciliation
4. Debt checking (I13 integration)
5. Position recovery/cleanup

**Рекомендація:**
✅ **СЕРЕДНЯ ПРИОРИТЕТНІСТЬ** — можна винести ~200-250 рядків

---

## 🔧 План Рефакторингу по Фазах

### ФАЗА 1: Витяг з `manage_v15_position()` — **~800 рядків** 🚀

**Новий модуль:** `executor_mod/position_manager.py`

#### 1.1. Витягти `_close_slot()` (718 рядків)
```python
# executor_mod/position_manager.py

def close_position_slot(
    st: dict,
    pos: dict,
    symbol: str,
    reason: str,
    # dependencies
    log_event_fn,
    send_trade_closed_fn,
    save_state_fn,
    margin_guard_on_after_position_closed,
    binance_api,
) -> None:
    """Extracted from manage_v15_position._close_slot()"""
    # ... 718 рядків логіки закриття позиції
```

**Безпека:** ✅ Висока
- Вже ізольована як вкладена функція
- Чіткі входи/виходи
- Немає прихованих залежностей від батьківської функції

**Економія:** ~720 рядків з executor.py

---

#### 1.2. Витягти `_is_unknown_order_error()` та error handling (322+ рядки)
```python
# executor_mod/position_manager.py

def is_unknown_order_error(e: Exception) -> bool:
    """Extracted from manage_v15_position._is_unknown_order_error()"""
    # ... 322 рядки логіки обробки помилок

def cancel_ignore_unknown(order_id: int, binance_api) -> Optional[Exception]:
    """Extracted from manage_v15_position._cancel_ignore_unknown()"""
    # ... 18 рядків
```

**Безпека:** ✅ Висока  
**Економія:** ~340 рядків

---

#### 1.3. Витягти watchdog wrapper логіку (SL/TP orchestration)

**Важливо:** Core watchdog логіка вже винесена в `exit_safety.py` (530 рядків)!
- `sl_watchdog_tick()` — planner logic
- `tp_watchdog_tick()` — planner logic

**Що залишилося в executor.py:** Wrapper/orchestration код (~400-450 рядків):
- Price snapshot refresh + throttling
- State persistence (watchdog flags)
- Error handling + one-shot event logging
- Market fallback execution (`flatten_market()`)
- Dust remainder handling
- SL-to-BE move після TP1 (для TP watchdog)
- Synthetic trailing activation

```python
# executor_mod/watchdog_manager.py (новий модуль)

def manage_sl_watchdog(
    st: dict,
    pos: dict,
    symbol: str,
    now_s: float,
    ENV: dict,
    binance_api,
    exit_safety,
    price_snapshot,
    log_event_fn,
    save_state_fn,
) -> None:
    """SL watchdog orchestration extracted from manage_v15_position
    
    - Refreshes price snapshot with throttling
    - Calls exit_safety.sl_watchdog_tick()
    - Handles plan execution (market fallback, dust)
    - Persists state changes
    """

def manage_tp_watchdog(
    st: dict,
    pos: dict,
    symbol: str,
    now_s: float,
    ENV: dict,
    binance_api,
    exit_safety,
    price_snapshot,
    log_event_fn,
    save_state_fn,
    send_webhook_fn,
    fmt_price_fn,
    fmt_qty_fn,
    round_qty_fn,
) -> None:
    """TP watchdog orchestration extracted from manage_v15_position
    
    - Refreshes price snapshot with throttling
    - Calls exit_safety.tp_watchdog_tick()
    - Handles plan execution (market fallback, SL-to-BE, synthetic trailing)
    - Persists state changes
    """
```

**Безпека:** ✅ Середня-Висока  
- Core логіка вже ізольована (exit_safety.py)
- Wrapper код добре структурований
- Вже є тести: `test/test_sl_watchdog.py`, `test/test_tp_watchdog.py`
- Потребує інтеграційних тестів для wrapper

**Економія:** ~400-450 рядків

---

**Всього ФАЗА 1:** ~1210 рядків → ~400 рядків (економія **~1210 рядків**)
- ФАЗА 1.1: -720 рядків (close_position_slot)
- ФАЗА 1.2: -340 рядків (error handling)
- ФАЗА 1.3: -450 рядків (watchdog wrappers) ⬅️ **ВИПРАВЛЕНО**

---

### ФАЗА 2: Витяг з `main()` — **~300 рядків** 🟢

**Новий модуль:** `executor_mod/main_loop.py`

#### 2.1. Event parsing + dedup (вже частково в event_dedup.py)
```python
# executor_mod/event_dedup.py (доповнити)

def parse_deltascout_event(line: str, ENV: dict) -> Optional[dict]:
    """Parse and validate PEAK event from DeltaScout log"""
    # Перемістити логіку з main()
```

**Економія:** ~80-100 рядків

---

#### 2.2. Entry flow orchestration
```python
# executor_mod/entry_flow.py (новий модуль)

def handle_peak_signal(
    event: dict,
    st: dict,
    ENV: dict,
    # dependencies
    binance_api,
    log_event_fn,
    save_state_fn,
    margin_guard,
) -> bool:
    """Orchestrate full entry flow from PEAK signal to position open"""
    # 1. Validate signal freshness
    # 2. Check dedup
    # 3. Build entry price
    # 4. Calculate qty
    # 5. Margin hook
    # 6. Place entry order
    # 7. Poll status
    # 8. Plan B logic
    # 9. Place exits
```

**Безпека:** ✅ Середня  
- Критична логіка, потребує інтеграційних тестів  
- Вже є частково в `exits_flow.py`

**Економія:** ~150-200 рядків

---

#### 2.3. Signal handlers + cleanup
```python
# executor_mod/runtime.py (новий модуль)

def setup_signal_handlers(shutdown_fn) -> None:
    """Setup SIGTERM/SIGINT handlers"""

def graceful_shutdown(st: dict, save_state_fn, log_event_fn) -> None:
    """Cleanup on shutdown"""
```

**Економія:** ~50 рядків

---

**Всього ФАЗА 2:** 553 рядки → ~250 рядків (економія **~300 рядків**)

---

### ФАЗА 3: Витяг з `sync_from_binance()` — **~200 рядків** 🟡

**Новий модуль:** `executor_mod/reconciliation.py`

#### 3.1. Exchange-truth checking
```python
# executor_mod/reconciliation.py

def check_exchange_position(symbol: str, base: str, quote: str, binance_api) -> dict:
    """Check actual position/debt on exchange"""

def reconcile_state_with_exchange(
    st: dict,
    symbol: str,
    ENV: dict,
    binance_api,
    log_event_fn,
    save_state_fn,
) -> None:
    """Full reconciliation logic extracted from sync_from_binance"""
```

**Безпека:** ✅ Середня  
- Використовується тільки при BOOT/RECOVERY  
- Потребує margin тестів

**Економія:** ~200-250 рядків

---

**Всього ФАЗА 3:** 430 рядків → ~230 рядків (економія **~200 рядків**)

---

### ФАЗА 4: Винос допоміжних функцій — **~200 рядків** 🟢

#### 4.1. Перемістити в `executor_mod/helpers.py` або `executor_mod/utils.py`

**Кандидати (безпечні, без залежностей):**
- `read_tail_lines()` — 31 рядок → вже використовується тільки в trail.py
- `_avg_fill_price()` — 20 рядків
- `_oid_int()` — 8 рядків
- `_as_f()` — 12 рядків
- `_as_env_bool()` — 9 рядків
- `now_utc()`, `iso_utc()` — 7 рядків
- `_split_symbol_guess()` — 17 рядків

**Всього:** ~100 рядків  
**Безпека:** ✅ **ДУЖЕ ВИСОКА** (чисті функції без побічних ефектів)

---

#### 4.2. Перемістити в `executor_mod/config.py`

**ENV конфігурація** (рядки 85-212):
- `_get_bool()`, `_get_int()`, `_get_float()`, `_get_str()` — 30 рядків
- `ENV` dict build — 127 рядків

**Всього:** ~160 рядків  
**Безпека:** ✅ ВИСОКА

---

**Всього ФАЗА 4:** економія **~260 рядків**

---

## 📦 Нові Модулі (Структура)

```
executor_mod/
├── position_manager.py      # ФАЗА 1 (~800 рядків)
│   ├── close_position_slot()
│   ├── is_unknown_order_error()
│   └── cancel_ignore_unknown()
│
├── watchdogs.py             # ФАЗА 1 (~150 рядків)
│   ├── sl_watchdog()
│   └── tp_watchdog()
│
├── entry_flow.py            # ФАЗА 2 (~200 рядків)
│   └── handle_peak_signal()
│
├── runtime.py               # ФАЗА 2 (~50 рядків)
│   ├── setup_signal_handlers()
│   └── graceful_shutdown()
│
├── reconciliation.py        # ФАЗА 3 (~200 рядків)
│   ├── check_exchange_position()
│   └── reconcile_state_with_exchange()
│
├── config.py                # ФАЗА 4 (~160 рядків)
│   └── build_env() → ENV dict
│
└── helpers.py               # ФАЗА 4 (~100 рядків)
    ├── read_tail_lines()
    ├── avg_fill_price()
    └── time helpers
```

---

## 📈 Очікуваний Результат

| Метрика | До | Після | Економія |
|---------|-----|-------|----------|
| **executor.py** | 3093 | **~1313** | **1780 рядків** (-57.6%) |
| **Кількість модулів** | 17 | 24 (+7) | — |
| **Найбільша функція** | 1207 | ~400 | -807 рядків |
| **Середній розмір функції** | 83 | ~33 | -60% |

---

## ⚠️ Ризики і Мітігація

### Високий Ризик
1. **`manage_v15_position()` — критична логіка управління позицією**
   - **Мітігація:** Покрокова міграція через ФАЗА 1.1 → 1.2 → 1.3
   - Запуск повного regression test suite після кожного кроку
   - Тестування на staging з real API

### Середній Ризик
2. **Entry flow в `main()`**
   - **Мітігація:** Вже є тести в `test/test_executor.py`
   - Додати інтеграційні тести для `entry_flow.py`

3. **`sync_from_binance()` margin reconciliation**
   - **Мітігація:** Тестування з margin account на staging
   - Логування всіх reconciliation events

### Низький Ризик
4. **Допоміжні функції (ФАЗА 4)**
   - **Мітігація:** Прості pure functions, легко тестувати

---

## 🧪 План Тестування

### Обов'язкові тести після кожної фази:

```bash
# Запуск всіх тестів
python -m pytest test/ -v

# Критичні тести
python -m pytest test/test_executor.py -v
python -m pytest test/test_sl_watchdog.py -v
python -m pytest test/test_tp_watchdog.py -v
python -m pytest test/test_margin_guard.py -v

# Smoke test imports
python -m pytest test/test_smoke_imports.py -v
```

### Інтеграційне тестування:
1. Запуск executor на staging з `LIVE_VALIDATE_ONLY=true`
2. Симуляція PEAK signal → перевірка entry flow
3. Симуляція fill → перевірка exits placement
4. Симуляція TP2 fill → перевірка trailing
5. Симуляція restart → перевірка reconciliation

---

## 🚀 Рекомендований План Виконання

### Тиждень 1: ФАЗА 4 (низький ризик, швидкий результат)
- ✅ День 1-2: Створити `config.py` + `helpers.py`
- ✅ День 3: Тести + міграція
- **Економія: ~260 рядків**

### Тиждень 2: ФАЗА 1.1 (найбільша економія)
- ✅ День 1-2: Створити `position_manager.py`, витягти `close_position_slot()`
- ✅ День 3-4: Regression tests
- **Економія: ~720 рядків**

### Тиждень 3: ФАЗА 1.2-1.3
- ✅ День 1-2: Витягти error handling + watchdogs
- ✅ День 3-4: Тести + staging
- **Економія: ~340 рядків**

### Тиждень 4: ФАЗА 2 + ФАЗА 3
- ✅ День 1-3: Entry flow + reconciliation
- ✅ День 4-5: Інтеграційні тести
- **Економія: ~500 рядків**

---

## 📋 Чеклист Рефакторингу

### Перед початком кожної фази:
- [ ] Створити feature branch: `refactor/phase-N`
- [ ] Запустити всі тести (baseline)
- [ ] Зробити backup state files

### Під час рефакторингу:
- [ ] Використовувати dependency injection (pattern з `.github/copilot-instructions.md`)
- [ ] Зберігати backward compatibility (старі імпорти)
- [ ] Додавати docstrings з посиланням на original location
- [ ] Оновлювати CLAUDE.md з новою структурою

### Після кожної фази:
- [ ] Всі тести green
- [ ] Оновити imports в executor.py
- [ ] Staging deployment + smoke test
- [ ] Merge до main
- [ ] Tag релізу: `v2.1-phaseN`

---

## 🎯 Висновки

### ✅ Найбезпечніші кроки (почати з них):
1. **ФАЗА 4** — helpers + config (~260 рядків, мінімальний ризик)
2. **ФАЗА 1.1** — `_close_slot()` (~720 рядків, ізольована функція)

### ⚡ Найбільша економія:
1. **ФАЗА 1** — `manage_v15_position()` (~810 рядків total)
2. **ФАЗА 2** — `main()` (~300 рядків)

### 🎁 Бонус:
- Покращена читабельність
- Легше писати тести (меншi unit test targets)
- Простіша підтримка (кожен модуль < 500 рядків)
- Краща масштабованість для майбутніх фічей

---

**Prepared by:** GitHub Copilot (Claude Sonnet 4.5)  
**Next Steps:** Обговорити з командою → Почати з ФАЗА 4 або ФАЗА 1.1
