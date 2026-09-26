# V1 versus V2 — boundary examples, not rebuilt snapshots

No raw source feed was available. These examples show verified V1 execution facts and proposed V2 time boundaries only. No V2 price/flow/OI/zone values are claimed, and these examples do not satisfy the pre-call requirement for three rebuilt V2 examples. No outcome fields were used.

## EX_EN_1789351940

- V1 market cutoff: `2026-09-14T02:13:00+00:00`.
- Required V2 cutoff / PEAK: `2026-09-14T02:12:00+00:00`.
- Actual Executor-observed fill remains `2026-09-14T02:13:54.228142+00:00`; entry remains `77309.91` USDC/BTC.
- Initial SL/TP1/TP2 remain `76419.63` / `78021.01` / `78821.7`.
- Signal-to-fill delay: `114.228142` seconds.

| Segment | First minute | Last minute | Rows |
| --- | --- | --- | ---: |
| 240–1440m | 2026-09-13T02:13:00+00:00 | 2026-09-13T22:12:00+00:00 | 1200 |
| 60–240m | 2026-09-13T22:13:00+00:00 | 2026-09-14T01:12:00+00:00 | 180 |
| 15–60m | 2026-09-14T01:13:00+00:00 | 2026-09-14T01:57:00+00:00 | 45 |
| 5–15m | 2026-09-14T01:58:00+00:00 | 2026-09-14T02:07:00+00:00 | 10 |
| 0–5m | 2026-09-14T02:08:00+00:00 | 2026-09-14T02:12:00+00:00 | 5 |

V1 publishes nine overlapping horizons, a long zone list and classifiers. V2 is specified to publish this five-segment chronological sequence, compact location/backdrop, four separately typed nearest zones and directional target geometry. Actual numerical market comparison is blocked until matching source rows are supplied.

## EX_EN_1788166698

- V1 market cutoff: `2026-08-31T08:59:00+00:00`.
- Required V2 cutoff / PEAK: `2026-08-31T08:58:00+00:00`.
- Actual Executor-observed fill remains `2026-08-31T08:59:28.724320+00:00`; entry remains `78463.85` USDC/BTC.
- Initial SL/TP1/TP2 remain `77850.73` / `79076.96` / `79690.08`.
- Signal-to-fill delay: `88.72432` seconds.

| Segment | First minute | Last minute | Rows |
| --- | --- | --- | ---: |
| 240–1440m | 2026-08-30T08:59:00+00:00 | 2026-08-31T04:58:00+00:00 | 1200 |
| 60–240m | 2026-08-31T04:59:00+00:00 | 2026-08-31T07:58:00+00:00 | 180 |
| 15–60m | 2026-08-31T07:59:00+00:00 | 2026-08-31T08:43:00+00:00 | 45 |
| 5–15m | 2026-08-31T08:44:00+00:00 | 2026-08-31T08:53:00+00:00 | 10 |
| 0–5m | 2026-08-31T08:54:00+00:00 | 2026-08-31T08:58:00+00:00 | 5 |

V1 publishes nine overlapping horizons, a long zone list and classifiers. V2 is specified to publish this five-segment chronological sequence, compact location/backdrop, four separately typed nearest zones and directional target geometry. Actual numerical market comparison is blocked until matching source rows are supplied.

## EX_EN_1782306796

- V1 market cutoff: `2026-06-24T13:13:00+00:00`.
- Required V2 cutoff / PEAK: `2026-06-24T13:13:00+00:00`.
- Actual Executor-observed fill remains `2026-06-24T13:13:34.281648+00:00`; entry remains `61961.66` USDC/BTC.
- Initial SL/TP1/TP2 remain `63173.33` / `60749.98` / `59538.31`.
- Signal-to-fill delay: `34.281648` seconds.

| Segment | First minute | Last minute | Rows |
| --- | --- | --- | ---: |
| 240–1440m | 2026-06-23T13:14:00+00:00 | 2026-06-24T09:13:00+00:00 | 1200 |
| 60–240m | 2026-06-24T09:14:00+00:00 | 2026-06-24T12:13:00+00:00 | 180 |
| 15–60m | 2026-06-24T12:14:00+00:00 | 2026-06-24T12:58:00+00:00 | 45 |
| 5–15m | 2026-06-24T12:59:00+00:00 | 2026-06-24T13:08:00+00:00 | 10 |
| 0–5m | 2026-06-24T13:09:00+00:00 | 2026-06-24T13:13:00+00:00 | 5 |

V1 publishes nine overlapping horizons, a long zone list and classifiers. V2 is specified to publish this five-segment chronological sequence, compact location/backdrop, four separately typed nearest zones and directional target geometry. Actual numerical market comparison is blocked until matching source rows are supplied.
