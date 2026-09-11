# LLM entry snapshot v2

Це локальний research/runtime-safe adapter для одноразової оцінки якості
сигналу в момент входу. Окремий live-safe builder
`executor_mod.entry_snapshot` тепер підключений до формування prompt-а
Executor, але зміна не відкриває, закриває або модифікує позиції.

Модуль `deltascout.research_bundle.llm_entry_snapshot` приймає:

- pre-cutoff evidence з `analysis_cutoff_ts`;
- snapshot, побудований `monitor_feed_contract.build_data_snapshot`;
- manifest з hash-ами файлів feed.

Offline-результат має `LLM_ENTRY_SNAPSHOT_V2`, `decision_cutoff_utc`, явний домен
`BTCUSDT`, одиниці полів, часовий контракт, readiness/gaps, source/code/input
hash-и й `pre_cutoff_evidence_sha256`. Відсутні OI/funding/liquidation та інші
непідтверджені значення залишаються `null` у вхідному monitor snapshot.

Live snapshot містить лише напрямок, ціну входу, PEAK-поля, пояснену provenance
двох upstream loss-avoidance фільтрів A/B, явну `execution_geometry` (entry,
planned stop/targets, risk distance і R) та monitor-контекст. У ньому немає
order IDs, order status, PnL, outcome або trailing state. Якщо provenance A/B
відсутня у старому сигналі, обидва фільтри позначаються `UNKNOWN`, а не
вигадуються як такі, що пройшли.

Offline payload містить лише напрямок, ціну входу, PEAK-поля, вікна, завершені bars,
описовий market state/zones, conflicts і data quality. Якщо lifecycle рівнів,
реакції на рівні або state memory не передані, adapter ставить явний статус
`NOT_IMPLEMENTED_IN_THIS_ADAPTER` і додає gap. Він не вигадує ці дані.

Перед побудовою offline adapter перевіряє, що всі відомі timestamp-поля не пізніші за
cutoff. Поля з execution management або післявхідним станом (`SL`, `TP`,
orders, PnL, outcome тощо) викликають fail-closed помилку. Це означає, що
поточний повний Executor evidence pack спочатку треба явно спроєктувати до
entry-підмножини; adapter не маскує небезпечні поля мовчки.

`executor_mod.entry_snapshot.build_entry_prompt` формує `LLM_ENTRY_PROMPT_V2`:
модель робить один
entry-time verdict `SUPPORT`, `REJECT` або `UNCLEAR`, використовує лише JSON
до cutoff, поважає домени/одиниці й трактує null/partial/recovered evidence як
невизначеність. Prompt не описує подальше супроводження угоди.

Перевірка:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q tests/offline/test_llm_entry_snapshot.py tests/offline/test_monitor_feed_contract.py
```

Очікуваний результат offline adapter-а: `22 passed`. Live boundary додатково
перевіряється `tests/executor/test_executor_entry_snapshot.py` і
`tests/executor/test_llm_trade_judge_entry_boundary.py`.

Свідомо не зроблено: server deployment, перенесення 39A state machine,
генерація level-reaction history, прогнозна калібровка, server deployment і
будь-який policy/action use. `live_decision_eligible` залишається `false`, доки
arrival-time/freshness/state completeness не будуть окремо сертифіковані.
