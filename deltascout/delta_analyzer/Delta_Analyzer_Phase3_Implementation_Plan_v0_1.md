
Розроблений як частина Фази 3  deltascout\delta_analyzer\delta_analyzer_implementation_plan_v1_1.md  після отримання перших данних фази 1-2.5+ з документа  deltascout\research_material\reviews\reviews_2026-03-17_to_2026-03-22_final_compact_summary.md

1. Purpose

Коротко:

навіщо потрібна стартова Phase 3
що вона спирається на repeated Phase 2.5 outputs
чому саме зараз вона виправдана
2. Position in the roadmap

Чітко зафіксувати:

Phase 1 = foundation
Phase 2 = events_context
Phase 2.5 = review layer
Phase 3 = sequence-aware / transition-aware analysis
market-state, outcome layer, setup taxonomy сюди ще не входять
3. Evidence base from Phase 2.5

Стисла опора на факти:

accepted sparse
reject funnel dominant
головні класи: direction_mismatch, vwap_side
21.03 short-side rejects виглядають структурно сильнішими за accepted short 20.03
enriched fields і ret_* тепер уже доступні
4. Phase 3 mission

Описати місію вузько:

не “побудувати модель ринку”
а навчитися бачити локальні послідовності подій
зрозуміти, що відбувається до і після reject/accepted event
перевірити, чи є повторювані event-neighborhood patterns
5. In-scope questions

Тут перелік конкретних питань, наприклад:

що передує vwap_side reject?
що передує direction_mismatch reject?
чи є серії same-side rejects перед strong move?
чи є opposite-side conflict clusters перед reversal?
accepted PEAK частіше з’являється після quiet buildup чи після conflict sequence?
6. Out of scope

Дуже важливий розділ.
Прямо написати:

no full market-state layer
no full outcome layer
no setup taxonomy
no live logic changes
no threshold loosening for signal count
no claim of edge without evidence
7. Inputs

Що використовує стартова Phase 3:

events_context
accepted_event_context
reject_event_context
interesting_rejects
reject_reason_summary
enriched matched feed fields
ret_15m, ret_60m
8. Core design principle

Тут головна рамка:

Phase 3 працює поверх готових Phase 2/2.5 outputs
sequence layer не переписує попередні шари
sequence layer додає event-to-event context, а не нову сигналку
9. Initial outputs

Описати артефакти першої ітерації.

Я б заклав мінімум такі:

9.1 event_sequence_review_YYYY-MM-DD.csv

По одному рядку на event, з sequence fields.

9.2 sequence_summary_YYYY-MM-DD.csv

Агрегований summary по sequence classes за день.

9.3 sequence_review_summary_YYYY-MM-DD.md

Людинозчитуваний короткий summary.

10. Initial sequence fields

Тут найважливіший технічний блок.

Я б заклав стартові поля:

prev_event_ts
prev_event_type
prev_event_kind
prev_reject_reason
minutes_since_prev_event
same_kind_streak
opposite_kind_streak
recent_reject_count_15m
recent_reject_count_60m
recent_same_kind_count_15m
recent_opposite_kind_count_15m
recent_vwap_side_count_60m
recent_direction_mismatch_count_60m
recent_accepted_count_60m
sequence_pattern_label
але тільки дуже грубо, без “setup taxonomy”
11. First target classes

Тут описати, що стартова Phase 3 не аналізує все одразу.

Пріоритетні класи:

vwap_side
direction_mismatch

Другий пріоритет:

3of3_fail
12. Sequence hypotheses to test

Наприклад:

repeated vwap_side short rejects можуть передувати зрілішому downside continuation
direction_mismatch clusters можуть бути early reversal containers
accepted PEAK після conflict sequence може мати іншу якість, ніж isolated accepted PEAK
alternating long/short rejects можуть сигналити transition churn, а не trend continuation
13. Data contract

Чітко описати:

output лишається date-scoped
sequence logic може використовувати попередні події в межах lookback window
enriched feed fields уже вбудовані в event rows
output не повинен залежати від live runtime
14. Determinism rules

Обов’язково:

однаковий input → однаковий output
чіткий lookback window
чіткий порядок сортування по часу
no hidden randomness
no LLM-generated labels inside dataset build
15. Minimal implementation stages

Оце дуже важливо, щоб не роздути фазу.

Stage 3.1

Previous-event linkage + simple neighborhood counts

Stage 3.2

Repeated-pattern summaries for vwap_side and direction_mismatch

Stage 3.3

Daily sequence review summary

Stage 3.4

Evidence review before any widening of scope

16. Success criteria

Наприклад:

sequence outputs стабільно генеруються
можна пояснити, що відбувалося до ключових rejects
з’являються повторювані sequence motifs
Phase 3 дає нову інформацію понад plain events_context
є підстава для майбутнього Phase 4, але без стрибка туди завчасно
17. Failure criteria

Корисно теж зафіксувати:

якщо sequence layer лише дублює Phase 2.5
якщо все перетворюється на шум без повторюваних мотивів
якщо доводиться вигадувати labels post hoc
якщо немає реальної доданої цінності для edge search
18. Immediate next step

Один короткий operational блок:

спочатку реалізувати event_sequence_review v0.1
тільки для vwap_side і direction_mismatch
на вже накопичених batch data
без чіпання live logic