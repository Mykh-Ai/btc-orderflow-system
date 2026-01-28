# Технічне завдання: Manual Close Detection (Finalization-First)

## Мета

Забезпечити, щоб при ручному закритті позиції на біржі (через Binance App/Web) бот:
- Автоматично детектував це через порівняння поточного балансу з baseline
- Виконував повний cleanup (скасування ліміток, repay боргу, очистка state)
- Робив це на самому початку manage_v15_position (позиція 1/10), до будь-яких watchdog/trailing/TP/SL дій
- Дотримувався принципу Finalization-First: cleanup → return, нічого більше не виконується в цьому циклі

---

## Вимоги

1. **Детекція manual close**
   - Порівнювати поточний баланс base asset з baseline (`st["baseline"]["active"]["balances"]["base_free"]`)
   - Толеранс: EPS = 0.00001 BTC (або еквівалент для іншого base)
   - Якщо $|current\_base - baseline\_base| < EPS$ → вважати позицію закритою вручну

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

---

