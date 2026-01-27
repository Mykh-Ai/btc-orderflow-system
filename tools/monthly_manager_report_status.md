# Monthly Manager Report → Gmail

Стан проєкту автоматизації місячних звітів для менеджера.

---

## Мета

Раз на місяць отримувати на Gmail звіт з фінансовими показниками бота за попередній календарний місяць.

Щоб це не заважало основній роботі бота (executor/другі сервіси) і VPS.

---

## Що зроблено (по факту)

### 1) Дані для звіту вже збираються автоматично під час роботи бота

**Producer:** `executor_mod/reporting.py`

На закритті позиції executor викликає `reporting.report_trade_close(st, pos, reason)`

Це створює/дописує рядок у:
- `/data/reports/trades.jsonl` (в контейнері executor)
- що фізично на хості: `/root/volume-alert/data/reports/trades.jsonl`

**Факт:** `trades.jsonl` у тебе наповнюється (ти показував записи угод).

### 2) Зібраний офлайн-пайплайн формування manager_report.md

**Пайплайн такий:**

**A. Enrich** (комісії/fees і PnL, де можливо)
- tool: `tools/enrich_trades_with_fees.py`
- input: `trades.jsonl`
- output: `trades_enriched.jsonl`

**B. Build manager report** (markdown з таблицями)
- tool: `tools/make_manager_report.py`
- input: `trades_enriched.jsonl`
- output: `manager_report.md`

**Артефакти:**
- `/root/volume-alert/data/reports/trades.jsonl`
- `/root/volume-alert/data/reports/trades_enriched.jsonl`
- `/root/volume-alert/data/reports/manager_report.md`

### 3) Доставка: зроблено відправку email через Gmail SMTP з хоста

**Зроблено host-level runner скрипт:**
- Скрипт: `/root/volume-alert/tools/run_monthly_manager_report.sh`

**Він:**
1. запускає tools в контейнері executor через `docker compose exec -T executor ...`
2. створює `manager_report.md`
3. читає env-файл SMTP
4. відправляє email з вкладенням `manager_report.md`

**ENV для пошти:**
- `/root/volume-alert/.reporter.env`
  - `SMTP_USER`
  - `SMTP_PASS` (app password)
  - `MAIL_FROM`
  - `MAIL_TO`
  - `SMTP_HOST`
  - `SMTP_PORT`

**Логи runner-а:**
- `/root/volume-alert/data/logs/manager_report_monthly.log`

---

## Де що лежить на сервері (точні шляхи)

### Код / оркестрація
- `/root/volume-alert/tools/run_monthly_manager_report.sh` ✅ створено/оновлено
- `/root/volume-alert/.reporter.env` ✅ існує (0600)

### Артефакти репортингу
- `/root/volume-alert/data/reports/trades.jsonl` ✅ пишеться executor-ом
- `/root/volume-alert/data/reports/trades_enriched.jsonl` ✅ генерується runner-ом
- `/root/volume-alert/data/reports/manager_report.md` ✅ генерується runner-ом

### Логи
- `/root/volume-alert/data/logs/manager_report_monthly.log` ✅ пишеться runner-ом

---

## Які компоненти/виклики задіяні (ланцюжок)

### 1. Executor runtime
```
executor.py → _close_slot() → executor_mod/reporting.py:report_trade_close()
→ пише trades.jsonl
```

### 2. Offline pipeline
```
tools/run_monthly_manager_report.sh
  → docker compose exec -T executor python /app/tools/enrich_trades_with_fees.py ...
  → docker compose exec -T executor python /app/tools/make_manager_report.py ...
```

### 3. Email delivery
```
run_monthly_manager_report.sh
  → python3 - <<PY ... smtplib ... PY (на хості)
  → SMTP creds із /root/volume-alert/.reporter.env
```

---

## Поточний статус (as-is)

- ✅ **Генерація репорту працює**: `manager_report.md` формується.
- ✅ **Email відправляється**: лист приходить на твій Gmail (перевірено `EMAIL_SENT`).
- ⚠️ **Якість репорту для керівника не відповідає очікуванням**, бо:
  - markdown-таблиці в Gmail виглядають "криво" (це проблема формату/рендеру, не генерації)
  - багато N/A/null метрик → enrichment не може порахувати все для всіх угод (частина ABORTED/без даних/без fees)

---

## Основні команди для перевірки

### A) Перевірити наявність файлів та права
```bash
ls -lah /root/volume-alert/tools/run_monthly_manager_report.sh
ls -lah /root/volume-alert/.reporter.env
ls -lah /root/volume-alert/data/reports/
ls -lah /root/volume-alert/data/logs/manager_report_monthly.log
```

### B) Запустити пайплайн вручну
```bash
bash -lc '/root/volume-alert/tools/run_monthly_manager_report.sh; echo "RC=$?"'
```

### C) Подивитися лог останнього запуску
```bash
tail -n 200 /root/volume-alert/data/logs/manager_report_monthly.log
```

### D) Перевірити, що репорт реально згенерився
```bash
ls -lah /root/volume-alert/data/reports/manager_report.md
sed -n '1,120p' /root/volume-alert/data/reports/manager_report.md
```

### E) Перевірити що env реально підхоплюється (без показу паролю)
```bash
bash -lc 'set -a; source /root/volume-alert/.reporter.env; set +a; \
echo "SMTP_USER=$SMTP_USER"; echo "MAIL_FROM=$MAIL_FROM"; echo "MAIL_TO=$MAIL_TO"; \
echo "SMTP_HOST=$SMTP_HOST"; echo "SMTP_PORT=$SMTP_PORT"; \
[ -n "${SMTP_PASS:-}" ] && echo "SMTP_PASS=set" || echo "SMTP_PASS=EMPTY"'
```

### F) Перевірити дані: скільки угод з pnl/fees реально пораховано
```bash
docker compose exec executor sh -lc "python - <<'PY'
import json, pathlib
p=pathlib.Path('/data/reports/trades_enriched.jsonl')
rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def nn(k): return sum(1 for r in rows if r.get(k) is not None)
print('rows=',len(rows))
for k in ['fees_total_quote','pnl_quote','roi_pct','entry_price','avg_exit_price','trade_key','exit_type']:
    print(k, nn(k))
PY"
```

---

## Цілі на майбутнє (чітко)

### 1) "Керівницький" вигляд: HTML/PDF замість markdown
- Генерувати HTML лист з нормальними таблицями (або PDF як вкладення).
- Markdown залишити як технічний артефакт.

### 2) Якість метрик: домогтися, щоб PnL/fees/ROI були не "N/A"
- Визначити, чому enrichment дає `pnl_non_null=1` (мало угод з повними даними)
- Рішення може бути:
  - чіткіше логувати/зберігати order fills / fee info в `trades.jsonl`
  - коректно виключати ABORTED/MANUAL з "фінансових" KPI або розносити в окрему секцію

### 3) Автоматизація "раз на місяць"
- Додати cron або systemd timer на хості, який запускає:
  ```bash
  /root/volume-alert/tools/run_monthly_manager_report.sh
  ```
- Важливо: з low priority + lock (вже є), щоб не заважало VPS.

### 4) Ідемпотентність (щоб не слати дубль)
- Додати "sent marker" для місяця (наприклад файл/рядок стану):
  ```
  /root/volume-alert/data/state/manager_report_sent_YYYY-MM
  ```
- Якщо вже sent → skip.
