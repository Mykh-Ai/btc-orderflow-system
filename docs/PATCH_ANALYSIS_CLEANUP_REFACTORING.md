# Аналіз патча: Cleanup Refactoring для manage_v15_position

**Дата**: 21 січня 2026  
**Версія**: v2.0 (ОНОВЛЕНО v2.1)  
**Автор аналізу**: GitHub Copilot  
**Статус v2.0**: ⚠️ НЕ РЕКОМЕНДОВАНО  
**Статус v2.1**: ✅ **УМОВНО БЕЗПЕЧНИЙ** з обмеженнями

---

## Зміст

1. [Огляд патча](#огляд-патча)
2. [Критичні ризики](#критичні-ризики)
3. [Середні ризики](#середні-ризики)
4. [Переваги](#переваги)
5. [Вердикт](#вердикт)
6. [Рекомендації](#рекомендації)
7. [План міграції](#план-міграції)

---

## Огляд патча

Патч рефакторить cleanup логіку в `manage_v15_position()` з метою:

- **DRY**: Видалити дублювання cancel логіки (~100 рядків)
- **Централізація**: Один механізм cleanup замість розкиданого коду
- **Throttling**: Захист від rate limits через `CLOSE_CLEANUP_RETRY_SEC`
- **TP1→BE retry**: Надійніший перехід SL до breakeven після TP1

### Ключові зміни

| Компонент | Було | Стало |
|-----------|------|-------|
| Cleanup при close | Розкидано по коду | `_cancel_sibling_exits_best_effort()` |
| TP1→BE перехід | Одна спроба | State machine з retry |
| SL detection | Тільки через `sl_id` | Fallback через `recon["sl_status"]` |
| sync_from_binance | Детальні `preserve_*` умови | Проста `preserve` перевірка |

---

## Критичні ризики

### 🔴 Ризик #1: Затримка закриття позиції через throttling

**Проблема**: Throttling може блокувати закриття позиції навіть після спрацювання SL.

```python
# ПОТОЧНИЙ КОД: негайне закриття після SL_DONE
if sl_filled:
    pos["sl_done"] = True
    # ... cancel orders ...
    _close_slot("SL")  # Миттєве закриття

# НОВИЙ КОД: може бути throttled
if sl_filled:
    pos["sl_done"] = True
    send_webhook({"event": "SL_DONE", ...})
    _finalize_close("SL", tag="SL_FILLED")
      ↓
    _cancel_sibling_exits_best_effort(tag="SL_FILLED")
      ↓
    next_s = float(pos.get("close_cleanup_next_s") or 0.0)
    if now_s < next_s:
        return  # 🚨 ПОЗИЦІЯ НЕ ЗАКРИВАЄТЬСЯ!
```

**Сценарій атаки**:
1. SL спрацював, `sl_done=True`, webhook відправлено
2. `close_cleanup_next_s` ще не настав (залишилось 1.5s)
3. Функція повертає `return` БЕЗ виклику `_close_slot()`
4. **Позиція залишається відкритою** в state, навіть якщо реально закрита на біржі
5. Інваріанти почнуть тригерити `I13_DEBT_CHECK` через невідповідність
6. Cooldown не активується → новий сигнал може прийти до фактичного close

**Вплив**:
- ⚠️ Порушення AK-47 контракту: "SL заповнено → позиція закрита негайно"
- ⚠️ State machine corruption
- ⚠️ Можливе подвійне відкриття позиції

**Оцінка**: **КРИТИЧНО** 🔴

---

### 🔴 Ризик #2: State machine complexity для TP1→BE переходу

**Проблема**: Додано 7+ нових полів стану з складною логікою retry.

```python
# Нові поля стану
pos["tp1_be_pending"]        # Флаг процесу
pos["tp1_be_old_sl"]          # ID старого SL для cancel
pos["tp1_be_source"]          # "TP1" або "TP1_WATCHDOG"
pos["tp1_be_attempts"]        # Лічильник спроб
pos["tp1_be_next_s"]          # Timestamp наступної спроби
pos["tp1_be_last_status"]     # Останній статус old_sl
pos["tp1_be_last_error"]      # Остання помилка
```

**Сценарії збоїв**:

#### Сценарій A: Restart під час TP1→BE переходу
```
1. TP1 filled → tp1_be_pending=True, tp1_be_old_sl=12345
2. Container restart
3. Завантаження state: tp1_be_pending=True, але:
   - old_sl вже скасований? невідомо
   - new_sl вже створений? невідомо
   - Retry loop продовжиться безкінечно?
```

#### Сценарій B: Old SL в невідомому статусі
```python
st_c = str((od_c or {}).get("status", "")).upper()
if st_c not in ("CANCELED", "REJECTED", "EXPIRED"):
    # Що якщо st_c == "PARTIALLY_FILLED"? "PENDING_CANCEL"?
    # Код буде retry безкінечно
```

#### Сценарій C: Конфлікт з TP1 watchdog
```
1. TP1 FILLED виявлено в основному loop → tp1_be_pending=True
2. TP watchdog запускається паралельно (через 0.5s)
3. Watchdog також викликає _tp1_be_transition()
4. Подвійне створення BE SL? Race condition на pos["orders"]["sl"]?
```

**Вплив**:
- ⚠️ Зависання в `tp1_be_pending=True` після restart
- ⚠️ Безкінечні retry loops
- ⚠️ Подвійне створення SL ордерів
- ⚠️ Складність debug (7 додаткових полів стану)

**Оцінка**: **КРИТИЧНО** 🔴

---

### 🔴 Ризик #3: Fallback для SL без ID може закрити позицію помилково

**Проблема**: Новий fallback код довіряє stale data з `recon`.

```python
# НОВИЙ КОД
sl_id2 = int((pos.get("orders") or {}).get("sl") or 0)
if not sl_id2 and not pos.get("sl_done"):
    recon = pos.get("recon") if isinstance(pos.get("recon"), dict) else {}
    sl_recon_status = str(recon.get("sl_status") or "").upper()
    if sl_recon_status == "FILLED":  # 🚨 Може бути stale!
        log_event("SL_FILLED_MISSING_ID_FALLBACK", mode="live", status=sl_recon_status)
        send_webhook({"event": "SL_FILLED_MISSING_ID_FALLBACK", ...})
        _finalize_close("SL", tag="SL_FILLED_MISSING_ID_FALLBACK")
        return
```

**Проблема**: `recon["sl_status"]` встановлюється тільки в `sync_from_binance()`:
- Викликається при startup або throttled (600s default)
- Може містити данні про **попередній** SL, а не поточний
- Якщо `sl_id` обнулиться через баг, stale `recon["sl_status"] = "FILLED"` закриє позицію помилково

**Сценарій атаки**:
```
T0: TP1 filled, створюємо новий SL (BE) з ID=67890
T1: sync_from_binance() бачить старий SL 12345 як FILLED
    → recon["sl_status"] = "FILLED"
T2: Bug в коді: pos["orders"]["sl"] = 0 (обнулився)
T3: Наступний tick manage_v15_position():
    sl_id2 = 0  (обнулений)
    recon["sl_status"] = "FILLED"  (stale data про 12345)
    → _finalize_close("SL") викликано ПОМИЛКОВО
    → Активна позиція закрита передчасно
```

**Вплив**:
- ⚠️ Передчасне закриття позиції
- ⚠️ Втрата потенційного профіту
- ⚠️ Складність debug (stale data)

**Оцінка**: **КРИТИЧНО** 🔴

---

### 🔴 Ризик #4: Спрощення sync_from_binance() прибирає критичну логіку

**Було**: Детальна перевірка умов для збереження ордера

```python
preserve_tp1 = (
    key == "tp1"
    and pos.get("status") in ("OPEN", "OPEN_FILLED")
    and (not tp1_done)             # TP1 ще не виконано
    and has_tp1_price              # Є ціна TP1
    and orders_qty1 > 0.0          # Є qty для TP1
)
preserve_tp2 = (
    key == "tp2"
    and pos.get("status") in ("OPEN", "OPEN_FILLED")
    and (not tp2_done)             # TP2 ще не виконано
    and (not tp2_synthetic)        # Не синтетичний trailing
    and has_tp2_price
    and orders_qty2 > 0.0
)
preserve = preserve_tp1 or preserve_tp2 or preserve_sl
```

**Стало**: Проста перевірка

```python
preserve = pos.get("status") in ("OPEN", "OPEN_FILLED")
```

**Проблема**: Тепер `recon` структура заповнюється навіть для:
- Вже виконаних ордерів (`tp1_done=True`)
- Синтетичних TP2 (`tp2_synthetic=True`)
- Ордерів з qty=0

**Наслідки**:
```python
# Сценарій:
1. TP1 filled, tp1_done=True
2. sync_from_binance() бачить TP1 order_id як NOT_FOUND
3. Раніше: preserve_tp1=False → skip (TP1 вже done)
4. Тепер: preserve=True → recon["tp1_status"] = "NOT_FOUND"
5. Watchdog бачить recon["tp1_status"] = "NOT_FOUND"
6. Watchdog може спробувати retry або помилково активувати cleanup
```

**Вплив**:
- ⚠️ Шум в `recon` структурі
- ⚠️ Можливі помилкові дії watchdog'ів
- ⚠️ Складність debug (зайві alerts)

**Оцінка**: **ВИСОКИЙ** 🔴

---

## Середні ризики

### 🟡 Ризик #5: Зміна порядку cleanup vs close

**Проблема**: Cleanup тепер виконується **ДО** `_close_slot()`.

```python
# ПОТОЧНИЙ КОД
_close_slot("SL")  # State persist + margin hook + reporting
# Окремі cancel виклики після (best-effort)

# НОВИЙ КОД
_finalize_close("SL", tag="SL_FILLED")
  ↓
_cancel_sibling_exits_best_effort()  # Мережеві виклики
_close_slot(reason)                   # State persist
```

**Ризик**: Якщо `_cancel_sibling_exits_best_effort()` виконується довго (API timeout, rate limit), затримка перед `_close_slot()` може спричинити:
- Неконсистентний state під час cleanup
- Інваріанти тригеруються на "позиція відкрита, але SL FILLED"
- Margin hook запізнюється (для margin mode)

**Mitigation**: У коді є `suppress(Exception)` в cancel логіці, але:
- State mutations в `_cancel_sibling_exits_best_effort()` можуть створити race conditions
- Throttling може заблокувати весь `_finalize_close()`

**Оцінка**: **СЕРЕДНІЙ** 🟡

---

### 🟡 Ризик #6: Дублювання cleanup логіки

**Проблема**: Cleanup тепер у **двох місцях**:

1. **Новий**: `_cancel_sibling_exits_best_effort()` в `_finalize_close()`
2. **Старий**: `exit_cleanup_pending` механізм (залишився без змін)

```python
# Обидва механізми можуть спрацювати для одного ордера:

# Шлях A: _finalize_close()
_cancel_sibling_exits_best_effort()
  → attempted.append(("tp1", tp1_id))
  → _cancel_ignore_unknown(tp1_id)

# Шлях B: exit_cleanup_pending
if pos.get("exit_cleanup_pending"):
    retry_ids = pos.get("exit_cleanup_order_ids") or []
    for oid in retry_ids:
        _cancel_ignore_unknown(oid)  # Той самий tp1_id?
```

**Сценарій конфлікту**:
```
T0: SL watchdog встановив exit_cleanup_pending=True, 
    exit_cleanup_order_ids=[tp1_id, tp2_id]
T1: Перед retry cleanup, TP2 filled
T2: TP2 викликає _finalize_close() 
    → _cancel_sibling_exits_best_effort() скасовує tp1_id
T3: Наступний tick: exit_cleanup retry також скасовує tp1_id
    → Подвійний cancel → помилка -2011 "Order already canceled"
```

**Вплив**:
- ⚠️ Зайві помилки в логах
- ⚠️ Можлива плутанина в retry counters
- ⚠️ Але: функціонально не критично (`_cancel_ignore_unknown` ігнорує -2011)

**Оцінка**: **СЕРЕДНІЙ** 🟡

---

## Переваги

### 🟢 Перевага #1: DRY принцип — видалено ~100 рядків дублювання

**Було**: Cancel логіка повторювалась у 5+ місцях

```python
# TP2 filled close
if tp1_id:
    with suppress(Exception):
        binance_api.cancel_order(symbol, tp1_id)
if sl_now:
    with suppress(Exception):
        binance_api.cancel_order(symbol, sl_now)
if sl_prev2:
    with suppress(Exception):
        binance_api.cancel_order(symbol, sl_prev2)
_close_slot("TP2")

# SL filled close
if tp1_id:
    with suppress(Exception):
        binance_api.cancel_order(symbol, tp1_id)
if tp2_id:
    with suppress(Exception):
        binance_api.cancel_order(symbol, tp2_id)
if sl_prev3:
    with suppress(Exception):
        binance_api.cancel_order(symbol, sl_prev3)
_close_slot("SL")

# SL watchdog close
# ... ще одна копія ...
```

**Стало**: Один централізований виклик

```python
_finalize_close("TP2", tag="TP2_DONE")
_finalize_close("SL", tag="SL_FILLED")
_finalize_close(str(plan.get("reason")), tag="SL_WATCHDOG_DONE")
```

**Вигода**:
- ✅ Легше підтримувати
- ✅ Менше місць для багів
- ✅ Єдине джерело правди для cleanup логіки

---

### 🟢 Перевага #2: Централізований throttling → захист від rate limits

**Механізм**:

```python
def _cancel_sibling_exits_best_effort(tag: str, throttle_sec: float = 2.0):
    next_s = float(pos.get("close_cleanup_next_s") or 0.0)
    if now_s < next_s:
        return  # Throttling
    
    # ... cancel logic ...
    
    pos["close_cleanup_next_s"] = now_s + retry_sec
    save_state(st)
```

**Вигода**:
- ✅ Захист від Binance rate limits (1200 req/min)
- ✅ Менше зайвих API викликів
- ✅ Конфігурується через `CLOSE_CLEANUP_RETRY_SEC`

**Примітка**: Це перевага **тільки якщо виправити критичний баг** з throttling на final close.

---

### 🟢 Перевага #3: Надійніший TP1→BE перехід з retry

**Поточний код**: Одна спроба, якщо падає — лог помилки і все

```python
try:
    sl_new = binance_api.place_order_raw({...})
except Exception as e:
    log_event("TP1_SL_TO_BE_ERROR", error=str(e), ...)
    # Позиція залишається БЕЗ BE SL!
```

**Новий код**: State machine з retry

```python
def _tp1_be_transition(exit_side, be_stop, rem_qty, source):
    # 1. Спочатку скасувати старий SL
    old_sl_id = pos.get("tp1_be_old_sl")
    if old_sl_id:
        _cancel_ignore_unknown(old_sl_id)
        # Перевірити чи скасувався
        if status not in ("CANCELED", "REJECTED", "EXPIRED"):
            # Retry пізніше
            pos["tp1_be_next_s"] = now_s + retry_sec
            return False
    
    # 2. Створити новий BE SL
    try:
        sl_new = binance_api.place_order_raw({...})
    except Exception as e:
        # Retry з error tracking
        pos["tp1_be_last_error"] = str(e)
        pos["tp1_be_next_s"] = now_s + retry_sec
        return False
    
    # Success: clear state
    pos["orders"]["sl"] = sl_new["orderId"]
    pos["tp1_done"] = True
    pos.pop("tp1_be_pending", None)
    return True
```

**Вигода**:
- ✅ Retry при тимчасових помилках (network timeout)
- ✅ Гарантія cancel старого SL перед новим
- ✅ Краще error tracking (`tp1_be_last_error`, `tp1_be_attempts`)

**Але**: Додана complexity (7 полів стану) — ризик зависання.

---

### 🟢 Перевага #4: Кращий observability

**Новий логінг**:

```python
log_event(
    "CLOSE_CLEANUP_BEST_EFFORT",
    mode="live",
    tag=tag,
    count=len(attempted),
    keys=[k for (k, _) in attempted],
)
```

**Приклад лога**:
```json
{
  "event": "CLOSE_CLEANUP_BEST_EFFORT",
  "mode": "live",
  "tag": "SL_FILLED",
  "count": 3,
  "keys": ["tp1", "tp2", "sl_prev"],
  "ts": "2026-01-21T12:34:56Z"
}
```

**Вигода**:
- ✅ Видно скільки ордерів скасовано при кожному close
- ✅ Легше debug (тег показує причину)
- ✅ Metrics: можна рахувати середню кількість cleanup ордерів

---

## Вердикт

### Загальна оцінка

| Критерій | Оцінка | Коментар |
|----------|--------|----------|
| **Безпека** | 🔴 **4/10** | Throttling блокує close; fallback на stale data |
| **Надійність** | 🟡 **6/10** | State machine complexity збільшує ризик edge cases |
| **Performance** | 🟢 **8/10** | Менше API викликів через throttling |
| **Maintainability** | 🟢 **9/10** | DRY, централізація логіки |
| **Observability** | 🟢 **9/10** | Кращі логи cleanup процесу |

### Фінальний вердикт

⚠️ **НЕ РЕКОМЕНДОВАНО** застосовувати патч без критичних виправлень.

**Причини**:
1. **Критичний баг**: Throttling може заблокувати закриття позиції після SL
2. **Ризик corruption**: State machine для TP1→BE може зависнути після restart
3. **Stale data**: Fallback на `recon["sl_status"]` може закрити позицію помилково
4. **Regression**: Спрощення `sync_from_binance()` може спричинити шум в alerts

**Якщо все ж застосовуєте** → див. [Рекомендації](#рекомендації).

---

## Рекомендації

### Критичні виправлення (ОБОВ'ЯЗКОВО)

#### Виправлення #1: NO throttling на final close

```python
def _cancel_sibling_exits_best_effort(tag: str, throttle_sec: float = 2.0, 
                                       override_throttle: bool = False) -> None:
    """
    Best-effort sibling exit cleanup with optional throttle override.
    """
    if not override_throttle:
        try:
            next_s = float(pos.get("close_cleanup_next_s") or 0.0)
        except Exception:
            next_s = 0.0
        if now_s < next_s:
            return  # Throttled
    
    # ... cleanup logic ...

def _finalize_close(reason: str, tag: str) -> None:
    """
    AK-47 contract: ALWAYS try cleanup, ALWAYS close position.
    NO throttling on final close.
    """
    _cancel_sibling_exits_best_effort(tag=tag, override_throttle=True)
    _close_slot(reason)
```

#### Виправлення #2: Видалити SL fallback без ID

```python
# ВИДАЛИТИ цей блок повністю:
# if not sl_id2 and not pos.get("sl_done"):
#     recon = pos.get("recon") if isinstance(pos.get("recon"), dict) else {}
#     sl_recon_status = str(recon.get("sl_status") or "").upper()
#     if sl_recon_status == "FILLED":
#         ...

# Замість цього: покластися на SL watchdog для виявлення filled SL
```

#### Виправлення #3: Додати timeout для TP1 BE state machine

```python
def _tp1_be_transition(...):
    # Prevent infinite retry loops
    max_attempts = int(ENV.get("TP1_BE_MAX_ATTEMPTS") or 10)
    attempts = int(pos.get("tp1_be_attempts") or 0)
    
    if attempts >= max_attempts:
        log_event("TP1_BE_MAX_ATTEMPTS_EXCEEDED", 
                  mode="live", attempts=attempts, max_attempts=max_attempts)
        send_webhook({"event": "TP1_BE_FAILED_PERMANENT", 
                      "symbol": symbol, "attempts": attempts})
        # Clear pending state, continue with old SL
        pos.pop("tp1_be_pending", None)
        pos.pop("tp1_be_old_sl", None)
        # ... clear all tp1_be_* fields ...
        pos["tp1_done"] = True  # Mark TP1 as done anyway
        st["position"] = pos
        save_state(st)
        return False
    
    # ... existing retry logic ...
```

#### Виправлення #4: Відновити детальну логіку в sync_from_binance

```python
# Повернути старі preserve_* перевірки:
preserve_tp1 = (
    key == "tp1"
    and pos.get("status") in ("OPEN", "OPEN_FILLED")
    and (not tp1_done)
    and has_tp1_price
    and orders_qty1 > 0.0
)
preserve_tp2 = (
    key == "tp2"
    and pos.get("status") in ("OPEN", "OPEN_FILLED")
    and (not tp2_done)
    and (not tp2_synthetic)
    and has_tp2_price
    and orders_qty2 > 0.0
)
preserve_sl = (
    key == "sl"
    and pos.get("status") in ("OPEN", "OPEN_FILLED")
    and has_sl_price
)
preserve = preserve_tp1 or preserve_tp2 or preserve_sl
```

---

### Рекомендовані тести

#### Тест #1: TP1 BE retry на cancel fail

```python
# test/test_executor.py
def test_tp1_be_retry_on_old_sl_cancel_fail(monkeypatch):
    """TP1 BE transition retries if old SL cancel fails."""
    
    # Mock: cancel returns error, status check shows NEW (not canceled)
    cancel_calls = []
    def mock_cancel(symbol, order_id):
        cancel_calls.append(order_id)
        raise Exception("API timeout")
    
    status_responses = [
        {"status": "NEW"},       # T0: not canceled yet
        {"status": "NEW"},       # T1: still not canceled
        {"status": "CANCELED"},  # T2: finally canceled
    ]
    def mock_status(symbol, order_id):
        return status_responses.pop(0) if status_responses else {"status": "CANCELED"}
    
    monkeypatch.setattr(binance_api, "cancel_order", mock_cancel)
    monkeypatch.setattr(binance_api, "check_order_status", mock_status)
    
    # Setup: TP1 filled
    st = _make_state_tp1_filled(tp1_id=111, sl_id=999)
    
    # T0: First attempt -> old SL not canceled
    manage_v15_position("BTCUSDC", st)
    assert st["position"]["tp1_be_pending"] is True
    assert st["position"]["tp1_be_old_sl"] == 999
    assert st["position"].get("tp1_done") is None  # Not done yet
    
    # T1: Retry -> still not canceled
    manage_v15_position("BTCUSDC", st)
    assert st["position"]["tp1_be_pending"] is True
    
    # T2: Finally canceled -> new SL created
    manage_v15_position("BTCUSDC", st)
    assert st["position"].get("tp1_be_pending") is None  # Cleared
    assert st["position"]["tp1_done"] is True
    assert st["position"]["orders"]["sl"] != 999  # New SL ID
```

#### Тест #2: Throttling НЕ блокує final close

```python
def test_finalize_close_ignores_throttle(monkeypatch):
    """_finalize_close() MUST close position even if throttle active."""
    
    # Setup: set throttle timestamp in future
    st = _make_state_sl_filled(sl_id=999)
    st["position"]["close_cleanup_next_s"] = time.time() + 999  # Far future
    
    # Should still close despite throttle
    manage_v15_position("BTCUSDC", st)
    
    assert st["position"] is None  # Position MUST be closed
    assert st["last_closed"]["reason"] == "SL"
```

#### Тест #3: Cleanup не конфліктує з exit_cleanup_pending

```python
def test_cleanup_no_conflict_with_exit_cleanup_pending(monkeypatch):
    """Ensure _finalize_close doesn't conflict with exit_cleanup_pending."""
    
    # Setup: exit_cleanup_pending активний для tp1_id
    st = _make_state_sl_watchdog_cleanup_pending(tp1_id=111)
    st["position"]["exit_cleanup_pending"] = True
    st["position"]["exit_cleanup_order_ids"] = [111]
    
    # TP2 filled -> викличе _finalize_close() з tp1_id в cleanup
    st["position"]["orders"]["tp2"] = 222
    monkeypatch.setattr(binance_api, "check_order_status", 
                        lambda s, oid: {"status": "FILLED"} if oid == 222 else {})
    
    cancel_calls = []
    def mock_cancel(symbol, order_id):
        cancel_calls.append(order_id)
        if cancel_calls.count(order_id) > 1:
            raise AssertionError(f"Order {order_id} canceled twice!")
    
    monkeypatch.setattr(binance_api, "cancel_order", mock_cancel)
    
    # Should handle gracefully (either skip or suppress -2011)
    manage_v15_position("BTCUSDC", st)
    
    # Verify tp1_id canceled max once
    assert cancel_calls.count(111) <= 1
```

---

### Моніторинг та алерти

#### Alert #1: TP1 BE зависання

```python
# В manage_v15_position(), додати після watchdog логіки:

if pos.get("tp1_be_pending"):
    pending_start = pos.get("tp1_be_first_attempt_ts")
    if not pending_start:
        pos["tp1_be_first_attempt_ts"] = iso_utc()
        st["position"] = pos
        save_state(st)
    else:
        from datetime import datetime
        start_dt = datetime.fromisoformat(pending_start.replace('Z', '+00:00'))
        now_dt = datetime.fromisoformat(iso_utc().replace('Z', '+00:00'))
        elapsed_sec = (now_dt - start_dt).total_seconds()
        
        if elapsed_sec > 60:  # 1 хвилина
            log_event("TP1_BE_STUCK_WARNING", 
                      mode="live", 
                      elapsed_sec=elapsed_sec,
                      attempts=pos.get("tp1_be_attempts"),
                      last_error=pos.get("tp1_be_last_error"))
            send_webhook({
                "event": "TP1_BE_STUCK",
                "symbol": symbol,
                "elapsed_sec": elapsed_sec,
                "attempts": pos.get("tp1_be_attempts"),
            })
```

#### Alert #2: Cleanup throttle на close

```python
# В _finalize_close(), перед викликом _close_slot():

if not override_throttle:
    # Цього не повинно бути! Log warning
    log_event("CLOSE_THROTTLE_WARNING", 
              mode="live", 
              tag=tag, 
              reason=reason,
              severity="WARNING")
```

---

## План міграції

Якщо все ж вирішите застосувати патч після виправлень:

### Фаза 1: Підготовка (1 день)

1. ✅ Створити feature branch `feature/cleanup-refactoring-safe`
2. ✅ Застосувати патч
3. ✅ Імплементувати всі 4 критичні виправлення
4. ✅ Додати 3 обов'язкові тести
5. ✅ Code review

### Фаза 2: Тестування на testnet (3-5 днів)

1. ✅ Deploy на testnet з `TRADE_MODE=spot`, малими сумами
2. ✅ Моніторинг метрик:
   - `CLOSE_CLEANUP_BEST_EFFORT` event frequency
   - `TP1_BE_*` event patterns
   - Average time from `sl_done=True` to `position=None`
3. ✅ Симулювати edge cases:
   - Container restart під час `tp1_be_pending=True`
   - API timeouts під час cleanup
   - Rapid TP1→TP2→SL fills
4. ✅ Verify invariants не тригеруються

### Фаза 3: Canary deploy (2-3 дні)

1. ✅ Deploy на 1 продакшн instance (10% трафіку)
2. ✅ Monitor:
   - State file corruption frequency
   - `TP1_BE_STUCK` alerts
   - Compare PnL vs baseline
3. ✅ Rollback plan готовий (automated)

### Фаза 4: Full rollout (1 день)

1. ✅ Якщо canary успішний → 100% deploy
2. ✅ Моніторинг 24h після deploy
3. ✅ Post-mortem документація

### Rollback plan

```bash
# If issues detected:
git revert <commit-hash>
./deploy.sh --emergency-rollback

# Clear corrupted state files (if needed):
rm /data/state/executor_state.json
# Restart will bootstrap from DeltaScout log
```

---

## Висновок

Патч має **хороші ідеї** (DRY, централізація, throttling), але **небезпечну реалізацію**:

### ✅ Застосовувати ТІЛЬКИ якщо:
1. Виправлено всі 4 критичні баги
2. Додано мінімум 3 тести
3. Пройдено testnet validation (5+ днів)
4. Готовий rollback plan

### ❌ НЕ застосовувати якщо:
1. Немає часу на proper testing
2. Production downtime критичний
3. Немає monitoring/alerting інфраструктури

### Альтернатива: Incremental refactoring

Замість великого патча, можна рефакторити поетапно:

**Крок 1** (safe): Створити `_cancel_sibling_exits_best_effort()` але **без throttling**, просто як helper function.

**Крок 2** (safe): Замінити дублюючий код на виклики helper'а, залишивши `_close_slot()` в тому ж місці.

**Крок 3** (risky): Додати throttling **тільки для non-critical cleanup** (sl_prev), не для final close.

**Крок 4** (risky): TP1→BE state machine як окремий PR після 2 тижнів моніторингу кроків 1-3.

Така стратегія знижує ризик і дозволяє rollback кожного кроку окремо.

---

**Документ створено**: 21 січня 2026  
**GitHub Copilot**: Claude Sonnet 4.5  
**Версія**: 1.0
