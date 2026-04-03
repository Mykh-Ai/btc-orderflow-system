# Після Watcher до LLM

Цей runbook описує, що робити після того, як `post_close_watcher` уже відпрацював, і потрібно підготувати локальний DeltaScout research package для аналітика або LLM.

Цей документ не пояснює, як працює watcher.
Він описує наступний workflow layer після завершення watcher-процесу.

---

## Призначення

Використовуй цей runbook, коли:

- server-side post-close watcher уже обробив close date
- потрібно синхронізувати research artifacts у локальний repo
- потрібно підготувати research base для analyst review або LLM handoff

Типовий кінцевий результат:

- локальний `research_material` синхронізований
- локально існує придатний review package
- пакет готовий для analyst або LLM analysis

---

## Межа workflow

### Що відбувається до цього runbook

До початку цього runbook server-side watcher уже має виконати daily materialization pipeline:

1. `build_phase1_derived`
2. `build_close_outcomes`
3. `delta_analyzer.cli`
4. `delta_analyzer.cli --build-review`

Це описано в:

- `post_close_watcher.md`

### Що покриває цей runbook

Після завершення watcher цей runbook покриває:

1. перевірку, яку дату було оброблено
2. синхронізацію локальних research artifacts за потреби
3. вибір правильного agent prompt або builder step
4. підготовку пакета, який реально придатний для LLM analysis

---

## Канонічне правило вибору

Після завершення watcher наступний крок потрібно обирати за реальною ціллю.

### Ціль A — синхронізувати останній оброблений день і швидко подивитися, що доступно

Використовуй:

- `agent_analyze_materials_prompt.md`

Використовуй це, коли:

- watcher уже відпрацював
- потрібна тільки latest processed date
- потрібно синхронізувати локальні materials
- потрібен короткий pre-summary
- повний final research bundle поки не потрібен

Очікуваний результат:

- локальний daily review package для latest processed date
- короткий pre-summary
- достатньо матеріалу, щоб вирішити, чи потрібен deeper analysis

### Ціль B — підготувати повний handoff package для аналітика або сильнішого LLM по явному date range

Використовуй:

- `agent_full_research_handoff_prompt.md`

Використовуй це, коли:

- потрібен повний пакет по явному date range
- потрібні sync плюс final compact summary
- потрібен standard local research bundle
- потрібно довести пакет до стану analyst/LLM handoff

Вибір mode:

- використовуй `sync_only`, коли server artifacts уже існують і потрібні лише local sync плюс pre-summary
- використовуй `summary_only`, коли локальні файли вже існують і потрібні тільки final summary плюс standard bundle
- використовуй `full_rebuild` тільки коли цей date range треба заново перебудувати на сервері

Очікуваний результат:

- локальні review materials синхронізовані для потрібного range, якщо це потрібно
- створено final compact markdown summary
- створено standard research bundle outputs

### Ціль C — зібрати standard bundle напряму з уже синхронізованих локальних матеріалів

Використовуй bundle builder CLI.

Рекомендована команда:

```bash
python -m deltascout.research_bundle.build_bundle --input-root deltascout/research_material/reviews --output-root deltascout/research_material/bundles --raw-feed-root deltascout/research_material/raw_feed
```

Використовуй це, коли:

- локальні review folders уже синхронізовані
- потрібно уникнути ручного складання bundle
- ціль — саме standard research bundle

Очікуваний результат:

- index summary
- selected cases
- sequence context
- raw micro
- manifest

---

## Мінімальна операційна процедура

### Крок 1 — підтвердити завершення watcher

Перевір:

- `/root/volume-alert/data/state/post_close_watcher_state.json`

Підтверди щонайменше:

- `last_processed_date`
- `last_processed_trade_key` або еквівалентний processed marker

Якщо watcher state відсутній або застарілий, не припускай, що latest date уже оброблена.

### Крок 2 — визначити цільовий scope

Обери один варіант:

- тільки latest processed date
- явний UTC date range
- тільки вже синхронізований локальний scope

Не використовуй нечіткий scope типу “latest”, якщо фактичний watcher state не був прочитаний.

### Крок 3 — обрати правильний шлях виконання

Використовуй таку карту:

- latest day sync і pre-summary: `agent_analyze_materials_prompt.md`
- повний handoff package по явному range: `agent_full_research_handoff_prompt.md`
- уже синхронізовані локальні materials до standard bundle: `research_bundle` CLI

### Крок 4 — перевірити локальну готовність пакета

Пакет вважається LLM-ready лише тоді, коли потрібні локальні artifacts реально існують.

Мінімально очікуваний локальний пакет, залежно від шляху:

- daily review summaries
- accepted/reject/interesting review tables
- final review markdown, якщо потрібен full handoff
- selected cases, якщо потрібен standard bundle
- sequence context, якщо потрібен standard bundle
- raw micro, якщо потрібен standard bundle
- manifest, якщо bundle CLI уже існує

### Крок 5 — чесно зафіксувати фінальний статус

Фінальний статус має бути одним із:

- `ready for LLM handoff`
- `partial but usable`
- `blocked`

Не називай пакет готовим, якщо sync неповний або є відома missing coverage без явного acknowledgement.

---

## Bundle CLI usage

### Канонічний запуск

```bash
python -m deltascout.research_bundle.build_bundle --input-root deltascout/research_material/reviews --output-root deltascout/research_material/bundles --raw-feed-root deltascout/research_material/raw_feed
```

### Де шукати outputs

Після запуску bundle builder перевіряй outputs у:

- `deltascout/research_material/bundles/<START>_to_<END>/`

Якщо builder запускався з кастомним `--output-root`, перевіряй саме той шлях.

### Що перевіряти після запуску

У bundle output directory перевір:

- `reviews_<START>_to_<END>_index_summary.csv`
- `selected_cases_<START>_to_<END>.csv`
- `selected_case_sequence_context_<START>_to_<END>.csv`
- `selected_case_raw_feed_micro_<START>_to_<END>.csv`
- `research_bundle_manifest.csv`

---

## Як читати статуси

### `complete`

Артефакт існує і для поточного етапу bundle виглядає повним.

### `partial`

Артефакт побудовано, але coverage неповна.
Це прийнятно лише тоді, коли missingness явно відображена в content або manifest.

### `missing`

Артефакт відсутній або цей етап bundle ще не реалізований / не відпрацював.

### Практичне правило

- `complete` = можна покладатися на артефакт для поточного workflow
- `partial` = можна використовувати обережно, з урахуванням missing coverage
- `missing` = не вважати пакет повним handoff package

---

## Рекомендоване поточне використання

### Якщо watcher щойно відпрацював і потрібен найновіший локальний research package

Запускай логіку з:

- `agent_analyze_materials_prompt.md`

### Якщо watcher уже відпрацював і потрібен повний LLM-ready package по відомому date range

Запускай логіку з:

- `agent_full_research_handoff_prompt.md`

Рекомендовані mode:

- `sync_only`, якщо server outputs уже існують і потрібні лише sync/pre-summary
- `summary_only`, якщо локальні materials уже синхронізовані і потрібні лише final summary плюс bundle

### Якщо bundle builder уже існує і локальні materials уже на місці

Запускай:

```bash
python -m deltascout.research_bundle.build_bundle --input-root deltascout/research_material/reviews --output-root deltascout/research_material/bundles --raw-feed-root deltascout/research_material/raw_feed
```

Потім перевір у bundle output directory:

- чи існує index summary
- чи існує selected cases
- чи існує sequence context
- чи існує raw micro
- чи існує manifest

---

## Чим цей runbook не є

Цей runbook не є:

- watcher implementation doc
- rebuild runbook
- review-analysis prompt як таким
- фінальним analyst memo

Це operator bridge між:

- завершенням watcher
- локальним sync / bundle preparation
- LLM-ready research handoff

---

## Швидка шпаргалка

- Watcher уже відпрацював, потрібен latest sync і короткий огляд: запускай `agent_analyze_materials_prompt.md`.
- Watcher уже відпрацював, потрібен повний пакет по range: запускай `agent_full_research_handoff_prompt.md`.
- Є локально синхронізовані review folders і потрібен standard bundle: запускай `research_bundle` CLI.
- Перед запуском завжди перевіряй `post_close_watcher_state.json` і фактичний scope.
- Після виконання перевіряй, чи реально існують index summary, selected cases, sequence context, raw micro і manifest.
- Якщо coverage неповна, статус має бути `partial but usable` або `blocked`, а не `ready`.