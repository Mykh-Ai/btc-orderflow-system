# DeltaScout

Order-flow signal detection module with research instrumentation.

Monitors the aggregated trade feed (`aggregated.csv`) produced by the Aggregator,
processes each minute row through a five-stage decision pipeline,
and emits PEAK signals for downstream consumers (Buyer, Executor).

## Pipeline

```
CSV row → Delta Detection → Comparison (3/3 rule) → Gate Logic → PEAK Emit
```

1. **Feed Ingestion** — tail-poll `aggregated.csv`, yield dict per row
2. **Raw Delta Detection** — compute `delta = buy - sell`, track rolling window max/min
3. **Comparison Logic (3/3 rule)** — current peak must beat previous on price, volume, AND vwap
4. **Gate Logic** — regime filters: EMA50 position, VWAP position, CHOP30, COH10, IMB range
5. **PEAK Emit** — write JSONL to live signal bus + mirror to research archive

---

## Storage

### Хвилинний feed (вхідні дані)

| Що | Шлях | Опис |
|----|------|------|
| Live feed | `/data/feed/aggregated.csv` | Rolling 1500 рядків. Пише Aggregator кожну хвилину. DeltaScout читає |
| **Feed archive** | `/data/archive/feed/YYYY-MM-DD.csv` | Повний добовий архів хвилинок. Append-only, dedup по Timestamp. Пише Aggregator |

Формат CSV (10 колонок):
```
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
```

### PEAK сигнали (вихід для трейдингу)

| Що | Шлях | Опис |
|----|------|------|
| **Live signal bus** | `/data/logs/deltascout.log` | JSONL. Читають Buyer і Executor. Truncate на 500 рядків (залишає 30). Містить `PEAK`, `INIT_MAX`, `INIT_MIN` |

Приклад PEAK:
```json
{"ts": "2026-03-16 19:09:00", "source": "DeltaScout", "action": "PEAK", "kind": "long", "delta": 114.88, "vol": 195.12, "imb": 0.589, "price": 74148.10, "vwap": 73398, "poc": 73980}
```

### Дослідницький архів (Research Phase 1)

| Що | Шлях | Опис |
|----|------|------|
| **Decision archive** | `/data/archive/deltascout/YYYY-MM-DD.jsonl` | Append-only, один файл на добу. Всі дельти, всі реджекти, всі PEAK. Ніколи не truncate'ується |

Тут зберігається **кожна подія** конвеєра DeltaScout:

| Подія | Коли записується | Що зберігає |
|-------|------------------|-------------|
| `DELTA_MAX` | Знайдено новий максимум дельти в rolling window | ts, delta, vol, imb, price, vwap, poc |
| `DELTA_MIN` | Знайдено новий мінімум дельти в rolling window | ts, delta, vol, imb, price, vwap, poc |
| `CANDIDATE_COMPARISON_REJECT` | Кандидат не пройшов базові перевірки або правило 3/3 | ts, kind, reject_reason (`no_prev_peak`, `direction_mismatch`, `vwap_side`, `vwap_distance`, `3of3_fail`), prev_* значення |
| `CANDIDATE_GATE_REJECT` | Кандидат пройшов порівняння, але зрізався на гейті | ts, kind, reject_reason (`ema50_regime`, `vwap_regime`, `chop30`, `coh10`, `imb_band`), gate_values, thresholds |
| `PEAK_EMIT` | PEAK пройшов всі перевірки | Повний PEAK payload + значення гейтів (chop30, coh10, ema50) |

Приклад запису:
```json
{"schema": 1, "event": "CANDIDATE_GATE_REJECT", "seq": 15, "ts": "2026-03-16 15:40:00", "kind": "short", "reject_reason": "chop30", "gate_values": {"chop30": 2.8, "coh10": 0.35}, "thresholds": {"chop30_max": 2.6}}
```

Кожен запис містить: `schema` (версія формату), `seq` (порядковий номер за сесію), `event` (тип події).

### Derived datasets (offline)

| Що | Шлях | Будується з | Скрипт |
|----|------|-------------|--------|
| Пропущені вікна | `/data/archive/datasets/` | DELTA_MAX/MIN + feed archive | `scripts/offline/build_phase1_derived.py` |
| Закриття позицій | `/data/archive/datasets/` | Executor log + state | `scripts/offline/build_close_outcomes.py` |

---

## Data Contracts

To guarantee reproducible research and deterministic replay, all storage
channels follow strict data contracts.

### Feed archive contract

`/data/archive/feed/YYYY-MM-DD.csv`

Properties:

* Append-only
* One file per UTC day
* Deduplicated by `Timestamp`
* Same schema as `aggregated.csv`
* Chronologically ordered

Schema (10 columns):

```
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty,
AvgPrice, ClosePrice, HiPrice, LowPrice
```

Rules:

* `Timestamp` is unique within a file
* `Timestamp` is minute-aligned
* Rows must be strictly increasing in time
* Files are immutable after day close

The feed archive is the **canonical historical dataset** for research
and backtesting.

All offline analysis must use the archive rather than the rolling
`aggregated.csv` file.

---

### Research decision archive contract

`/data/archive/deltascout/YYYY-MM-DD.jsonl`

Properties:

* Append-only
* Never truncated
* One JSON object per event
* Events written in runtime order

Every record contains:

```
schema
seq
event
ts
```

Where:

* `schema` — archive schema version
* `seq` — monotonic session sequence number
* `event` — event type
* `ts` — event timestamp

Supported events:

```
DELTA_MAX
DELTA_MIN
CANDIDATE_COMPARISON_REJECT
CANDIDATE_GATE_REJECT
PEAK_EMIT
```

---

### Event ordering guarantees

Within a single runtime session:

```
seq strictly increases
```

Across sessions:

```
timestamp order is preserved
```

The archive therefore forms a **complete deterministic trace
of the DeltaScout decision pipeline**.

---

### Separation from runtime logs

Runtime log:

```
/data/logs/deltascout.log
```

Research archive:

```
/data/archive/deltascout/
```

The runtime log may be truncated and is used only for live consumers
(Buyer / Executor).

The research archive is **permanent and immutable**.

---

## Ізоляція дослідницького архіву

- Окремий файл від `deltascout.log` — Buyer і Executor його **не читають**
- Не використовує truncation логіку live bus
- Помилки запису в архів **ніколи** не блокують емісію PEAK
- Архівні файли — read-only для аналізу, write-only для DeltaScout

---



## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FILE_PATH` | `/data/feed/aggregated.csv` | Input CSV path |
| `DELTASCOUT_LOG` | `/data/logs/deltascout.log` | Live signal bus output |
| `RESEARCH_ARCHIVE_DIR` | `/data/archive/deltascout` | Research archive directory |
| `POLL_SECS` | `20` | Feed poll interval |
| `ROLL_WINDOW_MIN` | `180` | Rolling window (minutes) |
| `STARTUP_LOOKBACK_MIN` | `1500` | Warmup rows |
| `WEBHOOK_URL` | — | Debug webhook |

Gate parameters: `CHOP30_MAX`, `COH10_MIN`, `IMB_LONG_MIN/MAX`, `IMB_SHORT_MIN/MAX`, `VWAP_MAX_DIST_USD`. See `.env.example`.

## Як користуватись дослідницьким шаром (Phase-1)

Фаза 1 додає до системи дослідницький шар, який дозволяє аналізувати
сигнали DeltaScout на основі накопичених архівів.
Нижче описано типовий workflow використання.

---

### 1. Накопичення даних

Система автоматично накопичує два архіви:

```
/data/archive/feed/YYYY-MM-DD.csv
/data/archive/deltascout/YYYY-MM-DD.jsonl
```
Ніяких дій виконувати не потрібно.
Рекомендовано накопичити **1–2 тижні даних**, щоб отримати статистично корисну вибірку.

---

###### 2. Побудова dataset-ів у день закриття угоди

У день закриття угоди на сервері потрібно запустити Phase-1 rebuild.

Використовується мікрокоманда:

```bash
./run_phase1_after_close.sh MM-DD

Приклад:

./run_phase1_after_close.sh 03-17

Скрипт автоматично підставляє рік 2026 і виконує:

build_phase1_derived

build_close_outcomes

3. Що повинно з’явитись після запуску

Після виконання мікрокоманди потрібно перевірити:

ls /root/volume-alert/data/archive/datasets

Очікування:

створені або оновлені файли за дату закриття:

reject_dataset_YYYY-MM-DD.csv

baseline_init_YYYY-MM-DD.csv

window_owner_miss_YYYY-MM-DD.csv

late_peak_YYYY-MM-DD.csv

close_outcomes_YYYY-MM-DD.csv

4. Перевірка результату угоди

Перевірка dataset результатів угод:

head -n 20 /root/volume-alert/data/archive/datasets/close_outcomes_YYYY-MM-DD.csv

Очікування:

у файлі є рядок по закритій угоді

close_reason відповідає фактичному результату (SL, TP тощо)

5. Важливо

запуск виконується вручну

дата для запуску — це дата закриття угоди (UTC)

дата відкриття угоди значення не має

якщо join_status = missing, це означає, що відповідний PEAK_EMIT відсутній у research archive

Ці скрипти дозволяють аналізувати:

- розподіл сигналів
- прибутковість сигналів
- ефективність фільтрів
- пропущені можливості

---

## Подальший розвиток дослідницького шару

Дослідницький шар буде розвиватись у декілька фаз.

---

### Phase 1 — Data accumulation

Мета: накопичити великий масив спостережень.

Очікуваний обсяг:

```
3–6 місяців хвилинних даних
```

Завдання:

- накопичення feed archive
- накопичення DeltaScout decision archive
- побудова базових dataset.

---

### Phase 2 — Signal research

Мета Phase 2 — аналіз накопичених сигналів і пошук статистичного edge.

На цьому етапі досліджуються характеристики сигналів DeltaScout на основі накопичених архівів:

/data/archive/feed/
/data/archive/deltascout/

Основні напрями досліджень:

signal density maps

profitability by delta bucket

profitability by regime

reject signal analysis

threshold sensitivity

Dataset registry

Починаючи з Phase 2, усі дослідницькі dataset реєструються у файлі:

/data/archive/datasets/manifest.json

Цей файл містить метадані побудованих dataset:

назву dataset

файл dataset

час побудови

часовий діапазон джерельних даних

скрипт, яким dataset був згенерований

кількість рядків

Приклад запису:

{
  "name": "phase1_derived",
  "file": "phase1_derived_2026-03-16.csv",
  "built_at": "2026-03-16T18:21:00Z",
  "source_feed_start": "2026-03-01",
  "source_feed_end": "2026-03-16",
  "rows": 12483,
  "script": "build_phase1_derived.py"
}

manifest.json дозволяє:

відстежувати всі побудовані dataset

відтворювати дослідження

розуміти, з яких даних був отриманий результат

Це забезпечує reproducible research для дослідницького шару системи.

Research data principles

Дослідницький шар системи дотримується таких принципів:

Append-only datasets
Dataset не редагуються після побудови. Нові версії створюються як нові файли.

Deterministic builds
Офлайн-скрипти повинні будувати однаковий dataset з однакових архівів.

Traceable lineage
Кожен dataset реєструється у manifest.json і містить інформацію про джерело даних і скрипт побудови.

Research isolation
Дослідницькі dataset не використовуються безпосередньо у runtime-логіці торгівлі.

Майбутні дослідницькі інструменти

У Phase 2 планується додати інструменти для аналізу сигналів:

scripts/offline/signal_density_map.py
scripts/offline/reject_signal_analysis.py
scripts/offline/threshold_sensitivity.py

Ці інструменти дозволять досліджувати:

розподіл сигналів

ефективність гейтів

пропущені сигнали

чутливість порогів

Результат Phase 2 

Очікуваний результат цієї фази:

виявлення статистичного edge
визначення оптимальних порогів сигналів
аналіз ефективності фільтрів
підготовка моделей для Phase 3.

Phase 2 — Success criteria

Phase 2 вважається завершеною після виконання наступних умов:

накопичено щонайменше 4–12 тижнів хвилинних даних

побудовано дослідницькі dataset сигналів і результатів угод

проведено базовий аналіз сигналів (density, regime, reject)

виявлено кандидатні джерела статистичного edge

сформовано гіпотези для моделей Phase 3

Результатом Phase 2 є набір перевірених гіпотез, які переходять у фазу Strategy modelling.


### Phase 3 — Strategy modelling

Мета: побудувати нові моделі сигналів.

Можливі напрямки:

- adaptive thresholds
- regime-specific signals
- multi-factor signal scoring.

---

### Phase 4 — Production strategy

Після статистичної перевірки моделі можуть бути інтегровані
у торгову систему.

Це може включати:

- нові гейти
- зміну порогів
- нові типи сигналів.

---

## Run

```bash
pip install pandas numpy
python -u delta_scout.py
```

## Tests

```bash
pytest deltascout/test/ -v
```
