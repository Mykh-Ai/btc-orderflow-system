# Watchdog SL & TP Specification v2.0

## Зміст

1. [Загальні принципи](#загальні-принципи)
2. [Ключовий принцип: CANCEL-FIRST](#ключовий-принцип-cancel-first)
3. [Post-Market Verification](#post-market-verification)
4. [Watchdog SL](#watchdog-sl)
5. [Watchdog TP1](#watchdog-tp1)
6. [Watchdog TP2](#watchdog-tp2)
7. [State-Machine для Cancel Verification](#state-machine-для-cancel-verification)
8. [Tick Ordering](#tick-ordering)
9. [Поточні невідповідності](#поточні-невідповідності)

---

## Загальні принципи

| Принцип | Опис |
|---------|------|
| **Exchange = Truth** | Біржа — джерело правди, state — кеш для детермінізму між тиками/рестартами |
| **Finalization-first** | SL filled → негайно finalize, блокує ВСІ інші дії (TP/Trailing/Watchdog) |
| **Fail-loud** | Невизначеність → лог/webhook, без хаотичних дій |
| **Throttled polling** | Всі API виклики через throttle (`*_next_s` timestamps) |

---

## Ключовий принцип: CANCEL-FIRST

### Проблема

На margin account неможливо розмістити новий exit ордер поки старий не скасовано — Binance поверне `-2010 "insufficient balance"`.

### Правило

```
ПОСЛІДОВНІСТЬ ДЛЯ ВСІХ WATCHDOG ДІЙ:
1. Cancel старого ордера
2. Verify cancel (CANCELED/NOT_FOUND/FILLED)
3. Якщо старий FILLED → finalize_close (Finalization-first)
4. ТІЛЬКИ ПІСЛЯ підтвердження cancel → MARKET flatten або новий ордер
5. POST-MARKET VERIFY → якщо старий ордер встиг заповнитись → REBALANCE
```

---

## Post-Market Verification

### Race Condition Problem

```
Timeline:
t0: SL ордер активний, price слизнув
t1: Watchdog → cancel(SL)
t2: Watchdog → verify cancel... (polling)
t3: Біржа → SL triggered (price hit), started filling
t4: Watchdog → verify returns CANCELED (cancel дійшов)
t5: Watchdog → MARKET SELL залишок
t6: Біржа → SL FILLED (fill завершився ПІСЛЯ cancel response)
t7: Результат: ПОДВІЙНИЙ SELL → ми тепер SHORT на повну qty
```

### Рішення: Double-Fill Rebalance

```python
def _check_and_rebalance_after_market(
    order_id: int,
    executed_before: float,
    original_side: str,  # "BUY" or "SELL"
    symbol: str,
) -> None:
    """
    Після MARKET flatten перевіряє чи старий ордер не заповнився,
    і виравнює маркетом якщо потрібно.
    """
    try:
        od = check_order_status(symbol, order_id)
    except Exception as e:
        if is_unknown_order_error(e):
            return  # Ордер не знайдено — все ОК
        log_event("REBALANCE_CHECK_ERROR", error=str(e))
        return
    
    status = od.get("status", "").upper()
    final_executed = float(od.get("executedQty") or 0.0)
    
    if status == "FILLED" and final_executed > executed_before:
        extra_qty = final_executed - executed_before
        reverse_side = "BUY" if original_side == "SELL" else "SELL"
        
        try:
            flatten_market(symbol, reverse_side, extra_qty)
            log_event("DOUBLE_FILL_REBALANCE", 
                      extra_qty=extra_qty, 
                      reverse_side=reverse_side,
                      order_id=order_id)
        except Exception as e:
            log_event("DOUBLE_FILL_REBALANCE_ERROR", error=str(e))
            send_webhook({
                "event": "DOUBLE_FILL_REBALANCE_ERROR",
                "extra_qty": extra_qty,
                "error": str(e)
            })
```

### Таблиця дій

| Крок | Verify #1 (post-cancel) | MARKET | Verify #2 (post-market) | Дія |
|------|-------------------------|--------|-------------------------|-----|
| 1 | FILLED | ❌ Skip | — | finalize |
| 2 | CANCELED | ✅ Do | CANCELED | finalize |
| 3 | CANCELED | ✅ Do | FILLED (extra > 0) | REBALANCE + finalize |
| 4 | NOT_FOUND | ✅ Do | NOT_FOUND | finalize |

---

## Watchdog SL

### Сценарій A: SL Partial Fill

```
ТРИГЕР: executedQty > 0 AND status ≠ FILLED

ПОСЛІДОВНІСТЬ:
1. Зафіксувати executed_before = executedQty
2. Обчислити залишок: remaining_qty = origQty - executedQty
3. Cancel старого SL ордера ← ПЕРШИМ!
4. Verify cancel status (throttled polling):
   - FILLED → extra_qty = final_executedQty - executed_before
             → якщо extra_qty > 0: уся позиція закрита → finalize_close("SL")
             → якщо extra_qty = 0: продовжити (partial залишився partial)
   - CANCELED/NOT_FOUND → продовжити
   - PENDING/UNKNOWN → retry later (state-machine)
5. MARKET flatten на remaining_qty
6. POST-MARKET VERIFY:
   a. check_order_status(old_sl_id)
   b. Якщо status = FILLED AND executedQty > executed_before:
      - extra_qty = executedQty - executed_before
      - MARKET REVERSE (зворотний напрямок) на extra_qty
      - Log: DOUBLE_FILL_REBALANCE
7. finalize_close("SL_PARTIAL")

DUST POLICY:
- Якщо remaining_qty < MIN_QTY або notional < MIN_NOTIONAL:
  - Skip MARKET (неможливо)
  - Log: SL_DUST_REMAINDER
  - Proceed to finalize
```

### Сценарій B: SL Slippage (Price Crossed)

```
ТРИГЕР: price_now <= sl_stop (LONG) OR price_now >= sl_stop (SHORT)
        AND status ≠ FILLED
        AND grace_sec elapsed

ПОСЛІДОВНІСТЬ:
1. Зафіксувати executed_before = executedQty (може бути 0)
2. Cancel старого SL ордера ← ПЕРШИМ!
3. Verify cancel status:
   - FILLED → finalize_close("SL"), STOP
   - CANCELED/NOT_FOUND → продовжити
   - PENDING → retry later (state-machine)
4. MARKET flatten на full position qty
5. POST-MARKET VERIFY:
   a. check_order_status(old_sl_id)
   b. Якщо status = FILLED AND executedQty > executed_before:
      - extra_qty = executedQty - executed_before
      - reverse_side = "BUY" if original_side == "SELL" else "SELL"
      - MARKET(reverse_side, extra_qty)
      - Log: DOUBLE_FILL_REBALANCE
6. finalize_close("SL_WATCHDOG")
```

### Сценарій C: SL FILLED (Normal)

```
ТРИГЕР: status = FILLED (через throttled polling)

ПОСЛІДОВНІСТЬ:
1. pos["sl_done"] = True
2. finalize_close("SL")

ВАЖЛИВО: Жодних cancel/MARKET дій — ордер вже виконано
```

---

## Watchdog TP1

### Сценарій A: TP1 Partial Fill

```
ТРИГЕР: executedQty > 0 AND status ≠ FILLED

ПОСЛІДОВНІСТЬ:
1. Зафіксувати executed_before = executedQty
2. Обчислити залишок: remaining_qty = origQty - executedQty
3. Cancel старого TP1 ордера ← ПЕРШИМ!
4. Verify cancel status:
   - FILLED → pos["tp1_done"] = True, skip MARKET, go to step 7
   - CANCELED/NOT_FOUND → продовжити
   - PENDING → retry later
5. MARKET flatten на remaining_qty (exit side)
6. POST-MARKET VERIFY:
   a. check_order_status(old_tp1_id)
   b. Якщо status = FILLED AND executedQty > executed_before:
      - extra_qty = executedQty - executed_before
      - MARKET REVERSE на extra_qty
      - Log: TP1_DOUBLE_FILL_REBALANCE
7. pos["tp1_done"] = True
8. Ініціювати BE state-machine:
   a. Cancel поточного SL
   b. Verify SL cancel:
      - FILLED → finalize_close("SL")
      - CANCELED/NOT_FOUND → place SL_BE для qty2+qty3
   c. POST-MARKET VERIFY для SL (якщо був cancel)

DUST POLICY: аналогічно SL
```

### Сценарій B: TP1 Slippage (Price Crossed + Missing)

```
ТРИГЕР: status ∈ (CANCELED, EXPIRED, MISSING, REJECTED)
        AND price_now > tp1_price (LONG) OR price_now < tp1_price (SHORT)

ПОСЛІДОВНІСТЬ:
1. Зафіксувати executed_before = executedQty (зазвичай 0)
2. Cancel TP1 ордера (якщо ще існує) ← best-effort
3. Verify status (throttled)
4. MARKET flatten на qty1 (TP1 portion)
5. POST-MARKET VERIFY:
   a. check_order_status(old_tp1_id)
   b. Якщо status = FILLED AND executedQty > executed_before:
      - extra_qty = executedQty - executed_before
      - MARKET REVERSE на extra_qty
      - Log: TP1_DOUBLE_FILL_REBALANCE
6. pos["tp1_done"] = True
7. Ініціювати BE state-machine:
   a. Cancel поточного SL
   b. Verify SL cancel:
      - FILLED → finalize_close("SL")
      - CANCELED/NOT_FOUND → place SL_BE для qty2+qty3
   c. POST-MARKET VERIFY для SL

ВАЖЛИВО: "MISSING" статус інжектиться тільки при unknown_order exception,
          НЕ при відсутності в openOrders
```

### Сценарій C: TP1 FILLED (Normal)

```
ТРИГЕР: status = FILLED (через throttled polling)

ПОСЛІДОВНІСТЬ:
1. pos["tp1_done"] = True
2. Ініціювати BE state-machine:
   a. Cancel поточного SL ← ПЕРШИМ!
   b. Verify SL cancel:
      - FILLED → finalize_close("SL") (Finalization-first)
      - CANCELED/NOT_FOUND → продовжити
      - PENDING → retry later (tp1_be_pending state-machine)
   c. Place новий SL_BE на entry рівні для qty2+qty3
   d. POST-MARKET VERIFY для SL (якщо був cancel)
```

---

## Watchdog TP2

### Сценарій A: TP2 Partial Fill

```
ТРИГЕР: executedQty > 0 AND status ≠ FILLED

ПОСЛІДОВНІСТЬ:
1. Зафіксувати executed_before = executedQty
2. Обчислити залишок: remaining_qty = origQty - executedQty
3. Cancel старого TP2 ордера ← ПЕРШИМ!
4. Verify cancel status:
   - FILLED → pos["tp2_done"] = True, skip MARKET, go to step 8
   - CANCELED/NOT_FOUND → продовжити
   - PENDING → retry later
5. MARKET flatten на remaining_qty (exit side)
6. POST-MARKET VERIFY:
   a. check_order_status(old_tp2_id)
   b. Якщо status = FILLED AND executedQty > executed_before:
      - extra_qty = executedQty - executed_before
      - MARKET REVERSE на extra_qty
      - Log: TP2_DOUBLE_FILL_REBALANCE
7. pos["tp2_done"] = True
8. Якщо TRAIL_ACTIVATE_AFTER_TP2 AND qty3 > 0:
   a. Cancel поточного SL_BE ← ПЕРШИМ!
   b. Verify SL cancel:
      - FILLED → finalize_close("SL")
      - CANCELED/NOT_FOUND → place trailing SL для qty3
   c. POST-MARKET VERIFY для SL
   d. pos["trail_active"] = True
9. Якщо qty3 = 0 OR NOT TRAIL_ACTIVATE_AFTER_TP2:
   → finalize_close("TP2_PARTIAL")

DUST POLICY: аналогічно SL/TP1
```

### Сценарій B: TP2 Slippage (Price Crossed + Missing)

```
ТРИГЕР: status ∈ (CANCELED, EXPIRED, MISSING, REJECTED)
        AND price_now > tp2_price (LONG) OR price_now < tp2_price (SHORT)  ← PRICE GATE!

ПОСЛІДОВНІСТЬ:
1. Зафіксувати tp2_executed_before = executedQty (зазвичай 0)
2. Cancel TP2 ордера ← best-effort
3. Verify TP2 cancel status
4. POST-MARKET VERIFY для TP2:
   - Якщо FILLED → use filled qty, adjust trailing qty
5. Cancel поточного SL_BE ← ОБОВ'ЯЗКОВО перед trailing SL!
6. Verify SL cancel status:
   - FILLED → finalize_close("SL") (Finalization-first)
   - CANCELED/NOT_FOUND → продовжити
   - PENDING → retry later (state-machine)
7. Place новий trailing SL (swing-based) для qty2+qty3
8. pos["tp2_synthetic"] = True, pos["trail_active"] = True
9. POST-MARKET VERIFY для SL:
   - Якщо FILLED → MARKET REVERSE + finalize

ВАЖЛИВО: 
- БЕЗ price gate → НЕ активувати trailing (fail-loud)
- Trailing веде qty2+qty3
```

### Сценарій C: TP2 Missing WITHOUT Price Crossed

```
ТРИГЕР: status ∈ (CANCELED, EXPIRED, MISSING)
        AND price NOT crossed tp2

ДІЯ: 
- Log: TP2_MISSING_NOT_IN_ZONE
- Webhook alert
- НЕ скасовувати SL_BE (захист позиції!)
- НЕ активувати trailing (очікуємо ціну)
```

### Сценарій D: TP2 FILLED (Normal)

```
ТРИГЕР: status = FILLED

ПОСЛІДОВНІСТЬ:
1. pos["tp2_done"] = True
2. Якщо TRAIL_ACTIVATE_AFTER_TP2 AND qty3 > 0:
   a. Cancel поточного SL_BE ← ПЕРШИМ!
   b. Verify SL cancel status:
      - FILLED → finalize_close("SL") (Finalization-first)
      - CANCELED/NOT_FOUND → продовжити
      - PENDING → retry later
   c. Place новий trailing SL (swing-based) для qty3
   d. pos["trail_active"] = True
   e. POST-MARKET VERIFY для SL:
      - Якщо FILLED → MARKET REVERSE + finalize
3. Якщо qty3 = 0 OR NOT TRAIL_ACTIVATE_AFTER_TP2:
   → finalize_close("TP2")
```

### Порівняння: qty при trailing activation

| Сценарій | Trailing qty | Причина |
|----------|--------------|---------|
| TP2 FILLED (normal) | **qty3** | TP1 закрила qty1, TP2 закрила qty2, залишок = qty3 |
| TP2 Missing + slippage | **qty2 + qty3** | TP1 закрила qty1, TP2 не виконався, залишок = qty2+qty3 |

---

## State-Machine для Cancel Verification

### Стани верифікації

```python
CANCEL_STATE = {
    "NOT_STARTED": "ще не почали cancel",
    "CANCEL_SENT": "cancel request відправлено",
    "VERIFYING": "polling статусу",
    "VERIFIED_CANCELED": "підтверджено CANCELED/NOT_FOUND",
    "VERIFIED_FILLED": "ордер встиг заповнитись",
    "RETRY_NEEDED": "потрібен retry",
    "FAILED": "не вдалось скасувати після max_attempts",
}
```

### Поля state для кожного watchdog

```python
# SL Watchdog
pos["sl_wd_cancel_state"] = "NOT_STARTED"
pos["sl_wd_cancel_attempts"] = 0
pos["sl_wd_cancel_next_s"] = 0.0
pos["sl_wd_executed_before"] = 0.0  # для double-fill detection

# TP1 Watchdog
pos["tp1_wd_cancel_state"] = "NOT_STARTED"
pos["tp1_wd_cancel_attempts"] = 0
pos["tp1_wd_cancel_next_s"] = 0.0
pos["tp1_wd_executed_before"] = 0.0

# TP2 Watchdog (для cancel SL при trailing activation)
pos["tp2_wd_sl_cancel_state"] = "NOT_STARTED"
pos["tp2_wd_sl_cancel_attempts"] = 0
pos["tp2_wd_sl_cancel_next_s"] = 0.0
pos["tp2_wd_sl_executed_before"] = 0.0
```

### Діаграма Cancel-First Flow

```
                    ┌─────────────────┐
                    │ Watchdog Trigger│
                    │ (partial/slip)  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 1. Save         │
                    │ executed_before │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 2. Cancel       │
                    │    старого      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 3. Verify cancel │
                    │   (throttled)   │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
      ┌──────────┐    ┌──────────┐    ┌──────────┐
      │ FILLED   │    │CANCELED/ │    │ PENDING/ │
      │          │    │NOT_FOUND │    │ UNKNOWN  │
      └────┬─────┘    └────┬─────┘    └────┬─────┘
           │               │               │
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │ finalize   │  │ 4. MARKET  │  │ Retry later│
    │ _close()   │  │   flatten  │  │ (state-    │
    │            │  │            │  │  machine)  │
    └────────────┘  └─────┬──────┘  └────────────┘
                          │
                          ▼
                   ┌────────────┐
                   │ 5. POST-   │
                   │ MARKET     │
                   │ VERIFY     │
                   └─────┬──────┘
                         │
                ┌────────┴────────┐
                ▼                 ▼
         ┌──────────┐      ┌──────────┐
         │ FILLED   │      │ CANCELED │
         │ extra>0  │      │          │
         └────┬─────┘      └────┬─────┘
              │                 │
              ▼                 │
       ┌────────────┐           │
       │ 6. MARKET  │           │
       │  REVERSE   │           │
       └─────┬──────┘           │
             │                  │
             └────────┬─────────┘
                      ▼
               ┌────────────┐
               │ 7. finalize│
               │   _close() │
               └────────────┘
```

---

## Tick Ordering

### Критичний порядок в manage_v15_position()

```
manage_v15_position() tick:

Step 1: Terminal Detection FIRST
  └─ if sl_done OR SL FILLED → finalize_close(); return

Step 2: Exit Cleanup Pending
  └─ if exit_cleanup_pending → retry cancels; return

Step 3: SL Watchdog
  └─ Check SL status (throttled)
  └─ Handle partial/slippage → Cancel → Verify → MARKET → Post-verify → Rebalance

Step 4: TP1 Watchdog  
  └─ Check TP1 status (throttled)
  └─ Handle partial/slippage/filled → Cancel → Verify → MARKET → Post-verify → Rebalance → BE

Step 5: TP2 Watchdog
  └─ Check TP2 status (throttled)
  └─ Handle missing + price gate → Cancel TP2 → Cancel SL → Verify → Trailing SL → Post-verify

Step 6: Trailing Maintenance
  └─ if trail_active → update trailing stop

Step 7: BE State-Machine
  └─ if tp1_be_pending → execute BE transition (Cancel → Verify → Place)
```

---

## Поточні невідповідності

| # | Проблема | Поточний стан | Очікування |
|---|----------|---------------|------------|
| 1 | Terminal detection порядок | SL check ПІСЛЯ TP watchdog | SL check ПЕРШИЙ |
| 2 | TP2 price gate | Відсутній | Обов'язковий |
| 3 | Double fill rebalance | Відсутній | POST-MARKET VERIFY + REBALANCE |
| 4 | sl_done блокує TP watchdog | Не перевіряється в `tp_watchdog_tick` | Потрібна перевірка |
| 5 | executed_before tracking | Не зберігається | Потрібен для rebalance |
| 6 | Cancel SL before trailing SL | Є частково | Потрібна повна state-machine |
| 7 | POST-MARKET VERIFY | Відсутній | Потрібен для всіх cancel+market |

---

## План імплементації

### Фаза 1: Tick Ordering
- Перемістити Terminal Detection (SL check) на початок manage_v15_position()
- Додати sl_done check в tp_watchdog_tick()

### Фаза 2: TP2 Price Gate
- Додати перевірку `price_now > tp2` (LONG) / `price_now < tp2` (SHORT) в tp_watchdog_tick()
- Додати TP2_MISSING_NOT_IN_ZONE event

### Фаза 3: Cancel State-Machine
- Додати state fields для cancel verification
- Рефакторити cancel+verify логіку в state-machine

### Фаза 4: POST-MARKET VERIFY + Rebalance
- Додати executed_before tracking
- Додати post-market verification
- Додати DOUBLE_FILL_REBALANCE логіку

### Фаза 5: Модульність
- Винести watchdog логіку в окремий модуль `executor_mod/watchdog.py`
- Зберегти planner-only логіку в `exit_safety.py`

---

## Changelog

| Версія | Дата | Зміни |
|--------|------|-------|
| 2.0 | 2026-01-23 | Initial specification з CANCEL-FIRST та POST-MARKET VERIFY |
