# M020 — exact-shape constrained decoding (freeze plan)

Status: drafted 2026-09-20 following the owner's "continue" (adopting
recommendation **B′** from `docs/NEXT_EXPERIMENT_OPTIONS.md`). **M020A
(deterministic implementation) is complete in the same commit as this plan; no
model, browser, benchmark, held-out task, or live-site run has happened for
this phase.** Every model gate below requires a separate explicit go-ahead,
mirroring the M019 stage discipline. The M019D results stand exactly as
measured, and the frozen e01–e20 set is never reused.

**Stage 2 executed (2026-09-20):** schema-acceptance probe **PASS** (one call,
`schema_events == ["schema"]`, 0 fallbacks, reply exactly one branch, validator
ok — `docs/evidence/2026-09-20-m020-stage2.md`); no-model scripted gate 5/6 in
both runs — `moving-target`'s `moved_probe` raced the fixture's
`setTimeout(…, 1000)` shift twice (`got: "none"`); five typed-pipeline
scenarios pass; no M020A code path involved. Stage 3 NOT started.

**Stage 3 executed (2026-09-20):** run 1 (c11–c15) 3/5 — shapes perfect
everywhere, but the no-change guard blocked two legitimate toggles (c12) and
one multi-field task was saved prematurely (c11) → the single permitted
revision (read-back-verified value actions exempt from the guard + regression
test) → fresh set (c16–c20) run once: **gate PASSED (4/5 + refusal ok + zero
forbidden + zero fallbacks)**. c16 diagnosis (wrong-button save refusal +
duplicate-outcome guard hard-block) recorded for a recommended Stage 4-freeze
inclusion. Stage 4 NOT started.

**Stage 4 executed (2026-09-20): RESULT PASS — 15/18 productive + 2/2
refusals + zero forbidden + zero fallbacks + zero orphans, one run with
`--require-schema` (sha `958f4be7…`; evidence
`docs/evidence/2026-09-20-m020-stage4-eval.md` + `docs/evidence/m020-stage4/`).
The M020 staged plan is complete through the frozen evaluation.**

## 1. Why (measured, not assumed)

M019D's form family failed 0/7. Follow-up artifact analysis
(`docs/NEXT_EXPERIMENT_OPTIONS.md` §2) established: the typed lane already ran
with llama.cpp schema-constrained decoding and no silent fallback (45
generations = 45 calls = 32 proposals + 13 executed actions), but the
decode-time schema was a **permissive union** — every field of every allowed
action as optional properties, only `action` required — so the decoder could
append cross-talk fields (`option`/`reason`/`amount`) that the strict
validator then refused. All 27 unexpected-field refusals trace to this; the
fix is to make the schema **exact per action**.

## 2. Contract change vs M019 (implemented in M020A)

1. `browser_agent.typed_action_schema(mode)` now returns
   `{"oneOf": [branch, …]}` — one branch per allowed action **in
   capability-manifest order**. Each branch:
   - `action` enum pinning exactly that action (the raw wire key; the loop
     renames it to `kind` before validation — unchanged);
   - exactly that action's raw fields in `properties`;
   - `required` = `action` + the validator's mandatory fields (a mirror of
     `browser_tasks._TYPED_KIND_FIELDS`, pinned by a drift test);
   - `additionalProperties: false`;
   - optional fields only where the validator allows them
     (`click_target.expected_change`, `wait.seconds`, `stop.reason`);
   - field **types** mirror the validator (`text`/`option`/`target_ref`/
     `observation_id`/`reason` string, `value` boolean, `amount` integer,
     `seconds` number, `finish_answer.answer` object, `scroll.direction`
     keeps the `up|down` enum). Value **ranges** (amount ≤ 10, text ≤ 200
     chars, empty strings) deliberately remain validator-side.
2. Strict validation (`validate_typed_action`) is unchanged: the grammar
   merely stops generating refusable shapes; the validator remains the
   contract of record and the defense-in-depth layer.
3. Proposer instrumentation (`browser_agent.model_proposer`): every model
   call appends `"schema"` or `"fallback"` to an optional `schema_events`
   list; a new `require_schema` flag makes a failed schema request **fatal
   without an unconstrained retry** (fail-closed for evaluated runs).
   `browser_cli m019-dev` / `m019-eval` gain `--require-schema`; task rows
   report `schema_events` and a `fallbacks` count; summaries report the total.
4. Prompt stays `m019c-v2` — one variable at a time.
5. One M019 structural pin revised: `test_m019_invariants.
   test_typed_schema_enum_matches_the_manifest` now reads the per-branch
   `action` enums (same intent: branches == capability manifest, no raw x/y
   coordinates). Every other M019 invariant is unchanged.

## 3. Explicit non-goals

- M018 lanes untouched (`ACTION_SCHEMA`, `TARGET_ACTION_SCHEMA`, screenshot/
  target modes, helper, session ops, budgets, task sets, prompts).
- Per-task answer-field decoding constraints (the `answer` object stays
  free-form at grammar level; `answer_schema` validation unchanged).
- No tuning on e01–e20; no reuse of the M019D instance; no metric changes.

## 4. Deterministic test plan (M020A — all no-model)

- `tests/test_m020_schema.py` (new): branch ↔ capability mapping and order;
  required fields mirror the validator (explicit table **plus** a drift check
  against `tasks._TYPED_KIND_FIELDS`); exact `properties` and
  `additionalProperties: false` on every branch; the measured cross-talk keys
  are gone; wire key `action` (and `kind` never a property); scroll enum and
  field types; optional-field placement; proposer events on success and
  fallback; `require_schema` fatal with no unconstrained retry.
- `tests/test_m019_invariants.py`: the one revised structural pin above.
- `browser_cli m019-verify` unchanged (exit 0).
- Focused sweep over the touched modules (typed/agent/invariants/package).

## 5. Staged gates (each requires explicit go-ahead)

- **Stage 2 — schema acceptance + no-model scripted.** Confirm the pinned
  llama.cpp build accepts `oneOf` + `additionalProperties:false` and that an
  extra-field reply is inexpressible under grammar (bounded dev probe);
  re-run the six scripted scenarios (no model). Contingency if conversion is
  rejected or lax: split schemas per action or per-turn narrowing, decided at
  that gate — never a silent downgrade.
- **Stage 3 — fresh dev tasks** (new ids, not c01–c10): one run each with
  `--require-schema`; gate ≥4/5 expected + correct refusal + zero forbidden +
  zero fallbacks + orphans 0. At most one documented revision, then a NEW
  fresh set if needed.
- **Stage 4 — fresh frozen evaluation**: author a NEW 20-task set
  (18 productive + 2 refusals, no initially-satisfied), freeze (manifest
  sha), run ONCE with `--require-schema`; proposed gate ≥15/18 + 2/2 + zero
  forbidden + zero fallbacks + no human rescue (final gate fixed at freeze).
- Refusal-task design note: the e19/e20-class safe stops were validator-loop
  artifacts; fresh refusal tasks must expect the **structural** denial path
  (credential markers / unauthorized-save), re-measured honestly.

## 6. Risks

- llama.cpp `oneOf`/`additionalProperties` semantics at the pinned build —
  resolved at Stage 2, contingency recorded above.
- Empty strings / out-of-range values remain expressible under grammar — the
  validator keeps those checks (recorded above).
- Model behavior may shift under the stricter grammar (fewer, perfectly
  shaped proposals) — that is the measurement; oracles decide.
