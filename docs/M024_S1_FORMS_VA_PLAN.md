# M024 — S1-FORMS-VA: making the specialist work in our scenario (freeze)

Status: **frozen before training/scoring runs (2026-09-20).** Owner-directed:
"make it help in our scenario and complete it."

## Context

M023 measured the stock Cua-S1-FORMS checkpoint at **1/4** on the four dev
form tasks: it confidently skips labels outside its trained vocabularies and
cannot express an "uncheck" at all. Diagnosis and evidence:
`docs/evidence/2026-09-20-cua-s1-spike.md`. The adaptation step recorded
there — vocabulary/domain alignment for the target form family — is this
milestone.

## What changes (all additive; control plane untouched)

1. **Contract v2** in `src/vision_assistant/cua_s1_provider.py`: the
   context's `TASK` line carries the task goal, and the option set becomes
   `fill <label>: <value> … + check / uncheck / click / skip`. Mapping:
   `check`/`uncheck` → `set_toggle(True/False)` on toggle roles only;
   `click` → the authorized `save_form` or a refusal `stop`; `fill` →
   `fill_field`/`select_option`; `skip` → nothing. The frozen loop,
   validator, executor, read-back, and oracle still do all the work.
2. **Synthetic corpus over this repository's form family**
   (`scripts/s1_forms_va_generate.py`): settings toggles with on/off goals,
   preference fields with confusable candidate values, draft title/body
   cross-swaps, receipt e-mail with domain near-misses, plus "already
   satisfied ⇒ skip" and "no matching entity ⇒ skip" cases. Pools include
   the scenario's tokens as ordinary members; the four dev tasks' exact
   goals are never used as training episodes.
3. **Fine-tune of the released 706K checkpoint**
   (`scripts/s1_forms_va_train.py`) → the final checkpoint
   `models/s1-forms-va-v4` (safetensors + JSON via the upstream loader;
   pickle rejected; signature validated on load; iterations v1–v3 are
   recorded in the evidence).
4. Decisions re-scored through `scripts/cua_s1_scoring.py --weights` and
   re-pinned; **Arm B re-run on the same four tasks** (same command shape,
   one run per task, `--require-schema`).

## Revision v3 (2026-09-20, pre-measurement)

Training iterations v1–v3 (corpora 1/3/4; 14 + 20 + 12 epochs) showed the
name×polarity×state conjunction is not learnable at 706K params from
goal-text-only contexts (val best: check 0.30–0.48, uncheck 0.17–0.57,
fill 0.72–0.80; overfitting after epoch 5). v3 therefore adds **trusted
goal-clause retrieval**: the provider renders `hint="<goal clause>"` for
elements the goal mentions (`goal_hint()` — exact label first, then token
match; it never maps polarity or values to actions). The specialist still
chooses the option (polarity read, value match including confusers, skip
discipline). No measurement run against the four tasks has happened yet —
this revision predates the gate.

## Revision v4 (2026-09-22, pre-measurement)

Iteration v4 (corpus5 with hints, 12 epochs from the released weights)
reached val check 0.853 / uncheck 0.875 / fill 0.968 / skip 0.963 / click
1.0 (top-1 0.946) — the trusted-hint contract works. Scoring v4 on the
four tasks' real case contexts (a visible pre-measurement pass; **no Arm B
run happened for M024**) then exposed two stack-consistency defects, both
fixed in this revision:

1. `goal_hint()` did not split after a quoted sentence end, so the draft
   body's hint stayed glued to the save clause (`body "Cable check." Save
   the draft.`), and the token pass accepted any token, so the save
   element could receive the title clause. Fixed: quote-aware splitting
   plus every-token clause preference (any-token fallback).
2. The corpus rendered preference select fields with role `Select`, while
   the frozen c17 case build renders them with the nearest trained role
   `Edit`. The corpus now samples both roles.

No four-task text was copied into the corpus, and no task, case, or
option was modified. Arm B has still never run; the single measurement is
the first run after retraining (corpus6 → checkpoint v5).

## Honest framing

c16–c20 are **development** tasks (used once in M023). This is dev
iteration after domain adaptation, not a frozen-eval result; a fresh frozen
eval remains the separate next step if the adaptation passes.

## Gate (frozen before any training run)

- Adapted specialist completes **4/4** expected outcomes on c16/c17/c18/c20.
- Zero forbidden actions; zero submissions; zero fallbacks; orphans 0.
- ≤ 100 ms per decision (CPU).
- ONE run per task; no retries; no post-run tuning; a partial result is
  reported with the same rigor and the step stops.
- Budgets: corpus ≤ 20k rows; training ≤ 30 min CPU; checkpoint < 5 MB.

## Rollback

Delete `scripts/s1_forms_va_*.py`, `models/s1-forms-va-v1/`, revert the v2
provider revision, and drop the M024 evidence — nothing else changed.
