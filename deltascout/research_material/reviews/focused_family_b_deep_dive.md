# Focused DeltaScout Forensic Deep Dive: Family B

## 1. Purpose

- Fact: this memo studies only Family B.
- Fact: it does not re-summarize the whole batch.
- Fact: source scope is limited to the currently available local review bundle under `deltascout/research_material/reviews`, plus the already present batch review memo, sequence context CSV, and raw-feed micro extract where available.

## 2. Operational definition of Family B

- Fact: a case qualifies for Family B when all of the following are true:
  - short-side reject;
  - `price_vs_vwap_side=below`;
  - structural placement is already aligned for short on the visible VWAP-side field;
  - deeper failure still occurs;
  - priority reject reason is `3of3_fail`.
- Fact: cases that fail on `vwap_side`, `direction_mismatch`, `vwap_distance`, or other reject reasons are not Family B core members even if they occur nearby.
- Fact: same-session neighboring rows are included only when they are short-side and clearly sit inside the same deeper-failure process or immediate comparison frame.
- Fact: accepted `PEAK_EMIT` shorts are used only as reference class.
- Interpretation: Family B is a post-alignment failure family, not a generic short reject family.

## 3. Family B universe

- Fact: the current local bundle shows five core Family B cases.

| Timestamp UTC | Reject reason | Bucket | Rule | Cluster form |
| --- | --- | --- | --- | --- |
| 2026-03-24 14:09:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | cluster-like |
| 2026-03-24 14:45:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | cluster-like |
| 2026-03-29 12:12:00 | `3of3_fail` | `possible_reversal_confirmation` | `IR_B1` | isolated in current bundle |
| 2026-03-29 12:30:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | isolated in current bundle |
| 2026-03-31 01:46:00 | `3of3_fail` | `unclear_but_constructive` | `IR_F1` | semi-isolated with nearby same-side conflict |

- Fact: same-session neighboring rows retained for interpretation are:
  - `2026-03-24 13:49:00` short `vwap_side`, above VWAP, immediately before the `14:09` and `14:45` below-VWAP `3of3_fail` pair;
  - `2026-03-31 01:09:00` short `direction_mismatch`, below VWAP, before `2026-03-31 01:46:00`;
  - `2026-03-29 19:22:00` short `direction_mismatch`, below VWAP, immediately before accepted reference `2026-03-29 19:23:00`.
- Unknown: the current selected-case sequence file does not include local same-session neighbors for the `2026-03-29 12:12` and `12:30` rejects, so their cluster form is less certain.

## 4. Subtype segmentation

- Interpretation: Family B is not one uniform family.
- Interpretation: the current evidence supports at least three candidate subtypes.

### Subtype 1: continuation-pressure post-alignment failures

- Fact: `2026-03-24 14:09:00`, `2026-03-24 14:45:00`, and `2026-03-29 12:30:00` all carry bucket `possible_continuation_pressure`.
- Interpretation: these look like aligned short structures that still fail deeper in the funnel during or after continuation pressure.

### Subtype 2: reversal-confirmation timing failures

- Fact: `2026-03-29 12:12:00` is below VWAP, short, `3of3_fail`, bucket `possible_reversal_confirmation`.
- Interpretation: this looks different from the continuation-pressure subtype because the bucket suggests confirmation timing rather than extension pressure.

### Subtype 3: unresolved grammar-mismatch / reservoir cases

- Fact: `2026-03-31 01:46:00` is below VWAP, short, `3of3_fail`, bucket `unclear_but_constructive`, rule `IR_F1`.
- Interpretation: this is likely a separate subtype because the visible metrics are extreme but the bucket is taxonomically unresolved.

## 5. Evidence review by subtype

### Subtype 1: continuation-pressure post-alignment failures

- Fact: repeated structure:
  - all are short;
  - all are below VWAP;
  - all fail on `3of3_fail`;
  - all include either `IR_C2` or a continuation-pressure label.
- Fact: what is already aligned:
  - VWAP-side placement is aligned for short;
  - medium-horizon cumulative delta is supportive for short in all three cases:
    - `2026-03-24 14:09`: `cum_delta_60m=-2169.326`, `cum_delta_180m=-1821.613`;
    - `2026-03-24 14:45`: `cum_delta_60m=-1334.064`, `cum_delta_180m=-2580.498`;
    - `2026-03-29 12:30`: `cum_delta_60m=-402.640`, `cum_delta_180m=-581.966`.
- Fact: what still fails:
  - terminal reject reason remains `3of3_fail` in all three cases.
- Fact: raw-feed micro context is available for `2026-03-24 14:09`:
  - at `-5m`, close `70201.70` vs VWAP `70233.33`;
  - at event, close `70305.00` vs VWAP `70286.55`;
  - at `+5m`, close `69799.90` vs VWAP `69766.38`;
  - at `+15m`, close `69883.90` vs VWAP `69873.97`;
  - at `+30m`, close `69899.90` vs VWAP `69915.98`.
- Interpretation: `2026-03-24 14:09` behaves like a continuation move that was either late, already over-extended, or blocked by deeper sequencing.
- Interpretation: the `2026-03-24` pair is the clearest evidence that Family B can persist as a same-session deeper-failure process after VWAP alignment has already been achieved.
- Hypothesis: this subtype's likely deeper-failure mechanism is an unresolved combination of timing and exhaustion, not weak directional structure.
- Unknown: there is no `3of3_fail` decomposition to distinguish timing failure from hidden structural conflict.

### Subtype 2: reversal-confirmation timing failures

- Fact: `2026-03-29 12:12:00` is below VWAP and short, but metrics are materially weaker than the `2026-03-24` IR_C2 cases:
  - `cum_delta_60m=-69.065`;
  - `cum_delta_180m=-204.488`;
  - `ret_15m=-31.2`;
  - `ret_60m=11.2`.
- Fact: it is bucketed `possible_reversal_confirmation` under `IR_B1`.
- Interpretation: this looks less like a strong continuation-pressure paradox and more like a timing-sensitive confirmation attempt that never fully resolved.
- Unknown: no raw-feed micro extract or selected-case sequence neighborhood is available in the current bundle for this case.
- Hypothesis: this subtype is more likely a timing or sequence-confirmation miss than a true continuation setup-class lead.

### Subtype 3: unresolved grammar-mismatch / reservoir cases

- Fact: `2026-03-31 01:46:00` combines:
  - `price_vs_vwap_side=below`;
  - `cum_delta_60m=2578.497`;
  - `cum_delta_180m=3236.195`;
  - `ret_15m=199.8`;
  - `ret_60m=841.2`;
  - bucket `unclear_but_constructive`;
  - rule `IR_F1`;
  - terminal reject `3of3_fail`.
- Fact: nearby same-session short `2026-03-31 01:09:00` is also below VWAP, but fails on `direction_mismatch`.
- Fact: raw-feed micro for `2026-03-31 01:46:00` shows:
  - at `-5m`, close `68094.80` vs VWAP `68138.29`;
  - at event, close `67940.50` vs VWAP `67929.79`;
  - at `+5m`, close `67819.70` vs VWAP `67837.62`;
  - at `+15m`, close `67906.50` vs VWAP `67917.98`;
  - at `+30m`, close `67950.70` vs VWAP `67929.05`;
  - open interest rises from `89576.36` at `-5m` to `90177.81` at `+30m`.
- Interpretation: the visible structure does not read like immediate invalidation. It reads like a high-energy short process that stayed active after rejection.
- Interpretation: because the bucket remains `unclear_but_constructive`, this subtype is likely an unresolved grammar/taxonomy problem rather than a clean continuation or reversal-confirmation class.
- Hypothesis: this is the strongest current setup-discovery lead inside Family B because the visible metrics exceed accepted reference quality while the blocker is still opaque.

## 6. Strongest key cases

### 1. 2026-03-31 01:46:00

- Fact: reject reason `3of3_fail`; bucket `unclear_but_constructive`; rule `IR_F1`.
- Fact: structural strengths: below VWAP, strongest `cum_delta_60m`, strongest `cum_delta_180m`, strongest `ret_15m`, strongest `ret_60m` in Family B.
- Fact: visible blocker: only `3of3_fail` is exposed.
- Unknown: blocker status is deeper failure opaque from current files.
- Fact: sequence note: semi-isolated; nearby same-side reject at `01:09` (`direction_mismatch`, below VWAP); no later same-side accepted case in the available window.
- Interpretation: this is the most important Family B case because it is the clearest paradox against the accepted reference class.

### 2. 2026-03-24 14:09:00

- Fact: reject reason `3of3_fail`; bucket `possible_continuation_pressure`; rule `IR_C2`.
- Fact: structural strengths: below VWAP; very negative `cum_delta_60m` and `cum_delta_180m`; raw micro shows strong post-reject downside continuation at `+5m`.
- Fact: visible blocker: only `3of3_fail` is exposed.
- Interpretation: blocker status is visible blocker but other hidden blockers possible.
- Fact: sequence note: cluster-like; preceded by `2026-03-24 13:49:00` short `vwap_side` above VWAP; followed by `2026-03-24 14:45:00` short `3of3_fail` below VWAP.
- Interpretation: this case matters because it shows Family B forming as a post-alignment stage inside a same-session short failure process.

### 3. 2026-03-24 14:45:00

- Fact: reject reason `3of3_fail`; bucket `possible_continuation_pressure`; rule `IR_C2`.
- Fact: structural strengths: below VWAP; still strongly negative `cum_delta_60m` and `cum_delta_180m`.
- Fact: visible blocker: only `3of3_fail` is exposed.
- Interpretation: blocker status is visible blocker but other hidden blockers possible.
- Fact: sequence note: cluster-like; appears as later same-side stronger reject inside the `2026-03-24` process.
- Interpretation: this case matters because it suggests the deeper failure can persist after the first aligned short reject rather than resolving immediately.

### 4. 2026-03-29 12:30:00

- Fact: reject reason `3of3_fail`; bucket `possible_continuation_pressure`; rule `IR_C2`.
- Fact: structural strengths: below VWAP; supportive medium-horizon short pressure; `ret_15m=13.3`.
- Fact: visible blocker: only `3of3_fail` is exposed.
- Interpretation: blocker status is visible blocker but other hidden blockers possible.
- Unknown: sequence note is isolated in current files; no selected-case sequence window is available here.
- Interpretation: this case matters because it extends the continuation-pressure subtype beyond the `2026-03-24` cluster.

### 5. 2026-03-29 12:12:00

- Fact: reject reason `3of3_fail`; bucket `possible_reversal_confirmation`; rule `IR_B1`.
- Fact: structural strengths: below VWAP; mildly supportive `cum_delta_60m` and `cum_delta_180m` for short.
- Fact: visible blocker: only `3of3_fail` is exposed.
- Interpretation: blocker status is visible blocker but other hidden blockers possible.
- Unknown: sequence note is isolated in current files; no selected-case sequence window is available here.
- Interpretation: this case matters because it is the clearest evidence that Family B includes a second, weaker reversal-confirmation subtype instead of only continuation-pressure failures.

## 7. Accepted reference comparison

- Fact: accepted short reference cases in the local bundle are `2026-03-20 00:40:00` and `2026-03-29 19:23:00`.
- Fact: what accepted references show:
  - short `PEAK_EMIT` can pass the funnel with `price_vs_vwap_side=below`;
  - accepted status does not imply a strong outcome edge, because both accepted cases in the broader review closed `SL`.
- Fact: what accepted references do not prove:
  - they do not prove accepted shorts are structurally superior to all Family B rejects;
  - they do not prove Family B rejects are invalid setups;
  - they do not reveal the hidden internal pass/fail logic behind `3of3_fail`.
- Fact: `2026-03-31 01:46:00` looks stronger than accepted `2026-03-29 19:23:00` on specific visible metrics:
  - stronger `cum_delta_60m`: `2578.497` vs `68.985`;
  - stronger `cum_delta_180m`: `3236.195` vs `-802.882`;
  - stronger `ret_15m`: `199.8` vs `8.6`;
  - stronger `ret_60m`: `841.2` vs `52.8`.
- Fact: `2026-03-31 01:46:00` is not stronger on every dimension:
  - weaker dimension is acceptance itself, because the accepted case actually passed the funnel;
  - ambiguous dimensions include hidden gate-stack state, entry cleanliness, and timing.
- Fact: `2026-03-24 14:09:00` looks stronger than accepted `2026-03-29 19:23:00` on medium-horizon short pressure:
  - more negative `cum_delta_60m`: `-2169.326` vs `68.985`;
  - more negative `cum_delta_180m`: `-1821.613` vs `-802.882`.
- Fact: `2026-03-24 14:09:00` is weaker or ambiguous on other visible metrics:
  - weaker `ret_60m`: `-462.9` vs `52.8`;
  - ambiguous because the case may have been late or over-extended even though the immediate post-reject move continued down.
- Interpretation: accepted references show survival through the funnel, not an upper bound on structural quality.
- Unknown: the current files cannot tell whether acceptance favored better structure, narrower timing, or some hidden grammar requirement.

## 8. Strongest paradoxes inside Family B

- Fact: paradox 1 compares `2026-03-31 01:46:00` vs accepted `2026-03-29 19:23:00`.
- Fact: paradox metrics:
  - both are short and below VWAP;
  - the reject is stronger on both cumulative-delta windows and both forward-return windows.
- Unknown: the missing discriminator behind `3of3_fail`.

- Fact: paradox 2 compares `2026-03-24 14:09:00` with its own same-session process.
- Fact: paradox metrics:
  - `2026-03-24 13:49:00` fails on `vwap_side` while still above VWAP;
  - `2026-03-24 14:09:00` and `14:45:00` achieve below-VWAP alignment but still fail deeper.
- Interpretation: below-VWAP short alignment alone is not enough; the failure moved deeper rather than disappearing.
- Unknown: whether the deeper failure is timing, exhaustion, or hidden sequence conflict.

- Fact: paradox 3 is micro-level on `2026-03-24 14:09:00`.
- Fact: raw micro suggests post-reject continuation rather than immediate invalidation:
  - event close `70305.00`;
  - `+5m` close `69799.90`.
- Interpretation: the case may have been late rather than weak.
- Unknown: the files do not show whether the funnel intentionally avoids that late-entry profile.

- Fact: paradox 4 is subtype-level inside Family B itself.
- Fact: `2026-03-29 12:12:00` and `2026-03-31 01:46:00` both belong to Family B but have very different metric shapes and bucket labels.
- Interpretation: Family B is not one single structural failure mode.
- Unknown: whether these subtypes share one hidden gate failure or multiple different hidden failures that collapse into the same terminal `3of3_fail`.

## 9. Hard research verdict

- Interpretation: Family B is multiple subtypes, not one coherent family.
- Interpretation: the strongest current setup-discovery lead is the unresolved `IR_F1` / `unclear_but_constructive` subtype represented most clearly by `2026-03-31 01:46:00`.
- Interpretation: the most operational secondary subtype is continuation-pressure post-alignment failure, especially the `2026-03-24 14:09` to `14:45` cluster.
- Interpretation: the most ambiguous subtype is reversal-confirmation timing failure, represented by `2026-03-29 12:12:00`, because its metrics are weaker and local sequence/micro evidence is missing.
- Interpretation: the most likely deeper-failure mechanism right now is an unresolved combination:
  - timing;
  - sequence conflict;
  - exhaustion;
  - grammar mismatch.
- Fact: pure directional weakness is not the best explanation for the strongest Family B cases because visible placement and several directional metrics are already aligned.

## 10. Minimal next request

- Fact: artifact 1 wanted: per-case `3of3_fail` sub-check breakdown for `2026-03-24 14:09:00`, `2026-03-24 14:45:00`, and `2026-03-31 01:46:00`.
- Fact: why it matters: it would separate timing/sequence failure from hidden grammar or structure failure.
- Fact: ambiguity resolved: whether the Family B subtypes are sharing one deeper blocker or several different blockers.

- Fact: artifact 2 wanted: selected-case raw-feed micro extract for `2026-03-29 12:12:00` and `2026-03-29 12:30:00`.
- Fact: why it matters: those two midday Family B cases currently lack minute-level before/after tape context.
- Fact: ambiguity resolved: whether the midday subtype behaves like reversal-confirmation timing failure, continuation, or immediate invalidation.

- Fact: artifact 3 wanted: selected-case sequence context centered on `2026-03-29 12:12:00` and `2026-03-29 12:30:00`.
- Fact: why it matters: current bundle does not show whether those rows sit inside a same-session deeper-failure cluster.
- Fact: ambiguity resolved: whether the `2026-03-29` midday Family B members are isolated events or part of a multi-step short-side failure process.
