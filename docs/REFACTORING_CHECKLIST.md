# ✅ Чеклист Рефакторингу executor.py

**Версія:** v2.1  
**Мета:** Зменшити executor.py з 3093 до ~1523 рядків (-50.8%)

---

## 🎯 ФАЗА 4: Helpers + Config (~260 рядків, 2-3 дні)

### День 1: Створення модулів

- [ ] **Створити `executor_mod/config.py`**
  - [ ] Перемістити `_get_bool()`, `_get_int()`, `_get_float()`, `_get_str()`
  - [ ] Створити `build_env() -> Dict[str, Any]` функцію
  - [ ] Перемістити весь ENV dict build (рядки 85-212 з executor.py)
  - [ ] Додати docstring з поясненням
  
- [ ] **Створити `executor_mod/helpers.py`**
  - [ ] Перемістити `read_tail_lines()` (31 рядок)
  - [ ] Перемістити `_avg_fill_price()` (20 рядків)
  - [ ] Перемістити `_oid_int()` (8 рядків)
  - [ ] Перемістити `_as_f()` (12 рядків)
  - [ ] Перемістити `_as_env_bool()` (9 рядків)
  - [ ] Перемістити `now_utc()` та `iso_utc()` (7 рядків)
  - [ ] Перемістити `_split_symbol_guess()` (17 рядків)
  - [ ] Додати docstrings

### День 2: Інтеграція

- [ ] **Оновити executor.py**
  - [ ] Додати import: `from executor_mod.config import build_env`
  - [ ] Додати import: `from executor_mod.helpers import *`
  - [ ] Замінити локальні функції на імпорти
  - [ ] Видалити старі функції
  - [ ] Перевірити, що ENV правильно будується

- [ ] **Оновити інші модулі (якщо потрібно)**
  - [ ] trail.py — перевірити використання `read_tail_lines()`
  - [ ] Інші модулі — перевірити використання helpers

### День 3: Тестування

- [ ] **Запустити тести**
  ```bash
  python -m pytest test/ -v
  python -m pytest test/test_smoke_imports.py -v
  ```

- [ ] **Створити тести для нових модулів**
  - [ ] `test/test_config.py` — тест build_env()
  - [ ] `test/test_helpers.py` — тести для helpers

- [ ] **Staging deployment**
  - [ ] Deploy на staging
  - [ ] Запустити executor з `LIVE_VALIDATE_ONLY=true`
  - [ ] Перевірити логи

- [ ] **Merge + Tag**
  - [ ] Git merge до main
  - [ ] Tag: `v2.1-phase4`
  - [ ] Update CLAUDE.md з новою структурою

**Результат:** executor.py: 3093 → **2833 рядки** (-260, -8.4%) ✅

---

## 🔥 ФАЗА 1.1: Витяг _close_slot() (~720 рядків, 3-4 дні)

### День 1: Аналіз та підготовка

- [ ] **Аналіз залежностей `_close_slot()`**
  - [ ] Знайти всі виклики binance_api.*
  - [ ] Знайти всі виклики log_event()
  - [ ] Знайти всі виклики save_state()
  - [ ] Знайти всі виклики margin_guard.*
  - [ ] Знайти всі виклики send_trade_closed()
  - [ ] Виписати список усіх залежностей

- [ ] **Підготувати тестові дані**
  - [ ] Зібрати приклади state з різними статусами
  - [ ] Підготувати mock responses для Binance API
  - [ ] Створити test fixtures

### День 2: Створення модуля

- [ ] **Створити `executor_mod/position_manager.py`**
  - [ ] Додати `configure()` функцію (dependency injection pattern)
  - [ ] Скопіювати `_close_slot()` → `close_position_slot()`
  - [ ] Замінити прямі виклики на dependency injection:
    ```python
    # Було: binance_api.cancel_order(...)
    # Стало: deps['binance_api'].cancel_order(...)
    ```
  - [ ] Додати docstring з поясненням + link до original location
  - [ ] Додати type hints

- [ ] **Додати helper functions в position_manager.py**
  - [ ] `_update_order_fill()` (якщо використовується тільки в _close_slot)
  - [ ] Інші внутрішні helper functions

### День 3: Інтеграція з executor.py

- [ ] **Оновити manage_v15_position() в executor.py**
  - [ ] Імпортувати position_manager
  - [ ] Викликати `position_manager.configure()` при старті
  - [ ] Замінити `_close_slot(reason)` на:
    ```python
    position_manager.close_position_slot(
        st=st, pos=pos, symbol=symbol, reason=reason,
        log_event_fn=log_event,
        send_trade_closed_fn=send_trade_closed,
        save_state_fn=save_state,
        margin_guard=margin_guard,
        binance_api=binance_api,
        ENV=ENV,
    )
    ```
  - [ ] Видалити стару вкладену функцію `_close_slot()`

### День 4: Тестування

- [ ] **Створити `test/test_position_manager.py`**
  - [ ] Тест close_position_slot() з mock dependencies
  - [ ] Тест різних reason: "SL_HIT", "TP1_FILLED", "TP2_FILLED", "MANUAL"
  - [ ] Тест margin repay flow
  - [ ] Тест reporting v1 spec compliance

- [ ] **Regression tests**
  ```bash
  python -m pytest test/test_executor.py -v
  python -m pytest test/test_position_manager.py -v
  python -m pytest test/ -v
  ```

- [ ] **Integration test**
  - [ ] Запустити повний flow: PEAK → OPEN → TP2 → CLOSE
  - [ ] Перевірити state persistence
  - [ ] Перевірити логи

- [ ] **Staging deployment**
  - [ ] Deploy + smoke test
  - [ ] Моніторинг 24 години

- [ ] **Merge + Tag**
  - [ ] Code review
  - [ ] Merge до main
  - [ ] Tag: `v2.1-phase1.1`

**Результат:** executor.py: 2833 → **2113 рядків** (-720, -25.5%) ✅  
manage_v15_position: 1207 → **487 рядків** ✅

---

## 🎯 ФАЗА 1.2: Витяг error handling (~340 рядків, 2-3 дні)

### День 1: Витяг функцій

- [ ] **Доповнити `executor_mod/position_manager.py`**
  - [ ] Скопіювати `_is_unknown_order_error()` → `is_unknown_order_error()`
  - [ ] Скопіювати `_cancel_ignore_unknown()` → `cancel_ignore_unknown()`
  - [ ] Додати docstrings
  - [ ] Експортувати функції

### День 2: Інтеграція + тестування

- [ ] **Оновити manage_v15_position()**
  - [ ] Замінити виклики вкладених функцій на `position_manager.*`
  - [ ] Видалити старі вкладені функції

- [ ] **Тести**
  - [ ] Додати тести в `test/test_position_manager.py`
  - [ ] Regression tests
  - [ ] Staging deployment

- [ ] **Merge + Tag**
  - [ ] Tag: `v2.1-phase1.2`

**Результат:** executor.py: 2113 → **1773 рядки** (-340, -19.2%) ✅

---

## 🔍 ФАЗА 1.3: Витяг watchdog wrappers (~450 рядків, 3-4 дні) ⬅️ ВИПРАВЛЕНО

**Важливо:** Core watchdog логіка вже в `executor_mod/exit_safety.py` (530 рядків)!
- `sl_watchdog_tick()` — planner
- `tp_watchdog_tick()` — planner

**Що витягуємо:** Wrapper/orchestration код з `manage_v15_position()` (~400-450 рядків)

### День 1-2: Створення модуля

- [ ] **Створити `executor_mod/watchdog_manager.py`**
  - [ ] Витягти SL watchdog wrapper → `manage_sl_watchdog()`
    - Price snapshot refresh + throttling (~100 рядків)
    - State persistence (watchdog flags) (~50 рядків)
    - Plan execution (market fallback, dust) (~80 рядків)
  - [ ] Витягти TP watchdog wrapper → `manage_tp_watchdog()`
    - Price snapshot refresh + throttling (~100 рядків)
    - State persistence (TP flags) (~50 рядків)
    - Plan execution (market, SL-to-BE, synthetic trailing) (~150 рядків)
  - [ ] Додати `configure()` для dependency injection
  - [ ] Додати docstrings з посиланням на exit_safety.py

### День 2: Інтеграція + тестування

- [ ] **Оновити manage_v15_position()**
  - [ ] Імпортувати watchdogs
  - [ ] Викликати `watchdogs.configure()` при старті
  - [ ] Замінити inline watchdog code на виклики модуля
  - [ ] Видалити старий код

- [ ] **Використати існуючі тести**
  - [ ] `test/test_sl_watchdog.py` — адаптувати для нового модуля
  - [ ] `test/test_tp_watchdog.py` — адаптувати для нового модуля
  - [ ] Regression tests

- [ ] **Merge + Tag**
  - [ ] Tag: `v2.1-phase1.3`

**Результат:** executor.py: 1773 → **~1383 рядки** (-450, -32.6%) ✅ ⬅️ ВИПРАВЛЕНО  
manage_v15_position: 487 → **~400 рядків** ✅

**Примітка:** Економія більша завдяки витягу wrapper логіки навколо exit_safety викликів

---

## 🚀 ОПЦІОНАЛЬНО: ФАЗА 2 — Entry Flow (~300 рядків)

### Якщо є час та ресурси:

- [ ] **Створити `executor_mod/entry_flow.py`**
  - [ ] Витягти entry orchestration з main()
  - [ ] Функція `handle_peak_signal()`
  - [ ] Plan B logic
  - [ ] Entry timeout handling

- [ ] **Тести**
  - [ ] `test/test_entry_flow.py`
  - [ ] Integration tests

**Результат:** executor.py: 1623 → **1323 рядки** (-300) ✅

---

## 🚀 ОПЦІОНАЛЬНО: ФАЗА 3 — Reconciliation (~200 рядків)

### Якщо є час та ресурси:

- [ ] **Створити `executor_mod/reconciliation.py`**
  - [ ] Витягти exchange-truth checking з sync_from_binance()
  - [ ] Функції reconciliation logic
  - [ ] Debt checking

- [ ] **Тести**
  - [ ] `test/test_reconciliation.py`
  - [ ] Margin account integration tests

**Результат:** executor.py: 1323 → **~1523 рядки** (з orchestration) ✅

---

## 📝 Після Кожної Фази

### Обов'язкові кроки:

- [ ] **Тестування**
  ```bash
  # All tests
  python -m pytest test/ -v
  
  # Critical paths
  python -m pytest test/test_executor.py -v
  python -m pytest test/test_margin_guard.py -v
  python -m pytest test/test_invariants_module.py -v
  ```

- [ ] **Документація**
  - [ ] Оновити CLAUDE.md
  - [ ] Оновити .github/copilot-instructions.md
  - [ ] Додати changelog entry

- [ ] **Code Review**
  - [ ] Self-review коду
  - [ ] Перевірити backward compatibility
  - [ ] Перевірити dependency injection pattern

- [ ] **Deployment**
  - [ ] Staging deploy
  - [ ] Smoke tests
  - [ ] Моніторинг 24h
  - [ ] Production deploy (якщо OK)

---

## 🎯 Критерії Успіху

### Після ФАЗА 4:
- ✅ executor.py < 2900 рядків
- ✅ config.py працює
- ✅ helpers.py працює
- ✅ Всі тести green

### Після ФАЗА 1.1:
- ✅ executor.py < 2200 рядків
- ✅ manage_v15_position < 500 рядків
- ✅ position_manager.py працює
- ✅ Всі тести green

### Після ФАЗА 1.2:
- ✅ executor.py < 1800 рядків
- ✅ Error handling працює
- ✅ Всі тести green

### Після ФАЗА 1.3:
- ✅ executor.py < 1700 рядків
- ✅ manage_v15_position < 420 рядків
- ✅ watchdogs.py працює
- ✅ Всі тести green

### Фінальний успіх:
- ✅ executor.py < 1600 рядків (-50%+)
- ✅ Найбільша функція < 450 рядків
- ✅ Всі тести green
- ✅ Production stable 7+ днів
- ✅ Документація оновлена

---

## ⚠️ Червоні Прапорці

### ЗУПИНИТИСЬ ЯКЩО:
- ❌ Тести падають без очевидної причини
- ❌ Staging показує неочікувану поведінку
- ❌ Рефакторинг змінює business logic
- ❌ Dependency injection не працює
- ❌ Backward compatibility порушена

### ВИПРАВИТИ ПЕРЕД ПРОДОВЖЕННЯМ:
- ⚠️ Усі тести повинні бути green
- ⚠️ Code review повинен бути пройдений
- ⚠️ Staging повинен працювати стабільно 24h
- ⚠️ Документація повинна бути оновлена

---

## 📊 Прогрес Tracking

```
ФАЗА 4: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done
ФАЗА 1.1: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done
ФАЗА 1.2: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done
ФАЗА 1.3: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done
ФАЗА 2: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done  [✓] Skipped
ФАЗА 3: [ ] Not Started  [ ] In Progress  [ ] Testing  [ ] Done  [✓] Skipped

Поточний розмір executor.py: _____ рядків (з 3093)
Економія: _____ рядків (___%)
```

---

**Готові починати?** Почніть з ФАЗА 4! 🚀

**Посилання:**
- [REFACTORING_AUDIT.md](REFACTORING_AUDIT.md) — детальний аудит
- [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md) — короткий огляд
- [REFACTORING_VISUAL.md](REFACTORING_VISUAL.md) — візуалізація
