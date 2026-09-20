# Cua-S1 integration plan — optional specialist form-decision provider

Status: **plan-only (2026-09-20). Nothing installed, nothing downloaded, no
model runs, no code changes beyond this document.** Inspection sources:
the official model page (`cua-ai/cua-s1-forms`), the dataset page
(`cua-ai/cua-s1-forms`), `libs/cua-s1/MODEL_CARD.md`, and
`libs/cua-s1/python/src/cua_s1/planner.py` + `pyproject.toml` in the
trycua/cua repository.

## What Cua-S1 is (inspected facts)

- **A one-pass option scorer, not a generator.** A byte-level transformer
  encoder (2 layers, width 128, 4 heads) with an option-attention head:
  **706,048 parameters, 2.8 MB checkpoint** (safetensors + a JSON sidecar
  carrying the config and a SHA-256 tensor signature; the loader rejects
  pickle files by design). It never generates text and never chooses
  coordinates.
- **Input contract** (per interface element): a context string —
  `TASK fill the form from the document, then submit\nFORM <title>\n
  ELEMENT <role> "<label>" value="<current>"` (byte-truncated to 224) — plus
  a list of options: one `fill <label>: <value>` per document entity, then
  the fixed actions `check`, `click`, `skip` (options byte-truncated to 96).
- **Output contract:** one probability per option; downstream code takes
  the argmax, maps `fill` back to the entity by index, and orders execution
  (fills → checks → at most one submit click) — **plain code owns ordering
  and execution**.
- **Planner boundary (cua_s1/planner.py):** a `PlanningBackend` protocol
  (`plan(form_title, elements, entities) -> decisions`) with a validating
  `Planner` (unique element identities, no foreign/duplicate decisions,
  actions ⊆ {fill, check, click, skip}, finite probabilities, fill needs a
  valid entity index, every actionable element decided); `order_decisions`
  enforces a confidence threshold and **at most one recognized submit
  click, only when `allow_submit` is explicitly true**; `run_form` is
  **plan-by-default** — mutation requires explicit `execute`/`submit`
  flags — re-observes after every mutation, refuses checkbox toggles when
  the checked state is unknown, skips already-checked boxes, verifies the
  checked postcondition, and requires the driver to *confirm* every action
  effect.
- **Training evidence (as published):** 10k synthetic episodes with
  forced confuser pairs (email vs street, phone vs emergency contact);
  form-signature-disjoint splits; synthetic test 99.95%; a 196-decision
  real demo (3 forms + 3 PDFs) at 100%; shuffled-context control 37%;
  hosted Jev comparison 99.7% vs 83.6%. The model card states plainly:
  research profile, small real eval, English-centric, chooses only among
  already-extracted `Label: value` entities, cannot invent values, and its
  output must never be treated as proof of success.
- **Packaging:** package `cua-s1` (pre-alpha, MIT code; weights MIT per the
  model page), **Python ≥3.11,<3.14**, dependencies `numpy`, `safetensors`,
  `torch>=2.2,<3`. **This repository's product venv is Python 3.9.6 — the
  scorer cannot live in it.** A pyenv 3.11.9 interpreter already exists on
  this machine.

## Why it fits here (measured convergence)

This project's arc measured exactly the gap Cua-S1 fills: the generalist
screenshot agent was unreliable (M018D 3/18), target assistance helped
(6/18), typed actions helped again (M019D 10/18), exact action schemas
reached 15/18 with zero safety failures (M020), the live read task failed
only on cross-screen synthesis (M021), and the M022 smoke showed the
remaining 4B walls are **fine-grained classification, transcription, and
loop discipline** — while its evidence architecture worked. Cua-S1 makes
**one narrow decision extremely well** (which option for one element) and
leaves ordering, execution, verification, and approval to ordinary code —
which is precisely the control plane this repo already proves: typed
actions, allowlisted capabilities, read-back verification, refusal
handling, evidence/replay, independent scoring, approval before submission.

## Proposed integration architecture (additive only)

**Adopted from Cua: the scorer only.** cua-driver, Lume VMs, Cua-Bench, and
the MCP server are explicitly out of scope — this repository's executor
(fixture browser helper, typed session ops, read-back) stays authoritative.

```
trusted document values + distractors   (per task, built from the frozen spec)
        │
        ▼
candidate options:  fill <label>: <value> … + [check, click, skip]
        │
        ▼
Cua-S1 scorer  (separate 3.11+ environment, safetensors + SHA-256 sidecar)
        │  one probability per option
        ▼
src/vision_assistant/cua_s1_provider.py   (stdlib-only, audited)
   maps argmax → EXISTING typed actions + fail-closed rules
        │
        ▼
existing validate_typed_action → policy (authorized saves) →
session op with read-back → oracle (verify_typed_task)  — UNCHANGED
```

### Interfaces (exact)

- **`scripts/cua_s1_scoring.py`** (scratch, not bundled, audit-exempt):
  loads the checkpoint via `cua_s1.model.load_checkpoint` (validates
  format + SHA-256 before use), builds contexts/options for a task's field
  set, writes `decisions.json` (`{task, element, options, probabilities,
  argmax}`) using only the repository's synthetic data. Because the fixture
  layouts are deterministic, scoring once per field set is exact — the
  five-task experiment consumes a pinned `decisions.json`; live scoring is
  a later step.
- **`src/vision_assistant/cua_s1_provider.py`** (stdlib-only, scanned by
  the frozen M015 audit): consumes an injected `scorer` callable (or the
  pinned decisions file) and implements:
  - context/option construction exactly as the published contract;
  - mapping: `fill` → `fill_field` (text roles) or `select_option` (select
    roles; the entity value must equal a visible option, else fail-closed
    skip); `check` → `set_toggle(value=True)` (never False; already-on ⇒
    skip); `click` → **`save_form` only when the target is in the task's
    `authorized_saves`** (never arbitrary clicks; unauthorized ⇒ refusal
    path, exactly as the vision lane); `skip` → no action;
  - ordering: text fills → selects → toggles → the one authorized save;
  - confidence threshold (default 0.5, as in `order_decisions`), bounded
    actions only, one decision per element, duplicate/foreign decisions
    rejected — the planner.py validation rules restated locally.
- **`tests/test_cua_s1_provider.py`**: deterministic with a fake scorer —
  mapping table, ordering, fail-closed cases (unknown role, credential
  label, unauthorized save click, below-threshold), protocol validation.
- **`scripts/cua_s1_decisions.py`** run with the separate venv produces
  `models/cua-s1-forms/decisions.js`-style pinned artifacts (name TBD in
  the implementation step) + the SHA pin.

### Wire-in (one flag, dev lane only)

- `browser_cli m019-dev` gains `--decision-provider {vision,cua-s1}`
  (default `vision`). With `cua-s1`, `_m019_run_task` constructs a
  provider-backed proposer (`CuaS1TypedProposer`) instead of the vision
  proposer: each loop call reads the CURRENT observation's targets (via
  `session.targets()`), advances the field plan, and returns one typed
  action JSON — through the **same** loop, validation, refusals, read-back,
  and oracle. **Zero changes to `browser_agent.py`, `browser_tasks.py`
  validation, session ops, policies, or oracles.**
- **Frozen lanes stay frozen:** `m019-eval`, `m020-eval`, `m021-hn`,
  `m022-*` are untouched; the eval sets are never used for this comparison.

## The experiment (five existing form tasks — the only approved scope)

Available dev form tasks in the repo today: **c16** (settings-toggles:
toggles + save), **c17** (prefs-sequential: fill + select + save), **c18**
(draft-fills: input + textarea + save), **c20** (checkout-refusal: form-mode
refusal/safe-stop). One fresh dev task (**c21**: one select + one toggle +
authorized save) is authored + deterministically frozen first, in the same
style as the M022 dev set, to make five.

- **Arm A (baseline, re-measured once):** current vision 4B proposer on
  the five tasks with the current frozen harness — ≤ 5 runs × ≤ 20 calls
  ≤ **100 model calls** + one model load.
- **Arm B (treatment):** `--decision-provider cua-s1` on the same five
  tasks, one run each — **zero vision-model calls**; one Cua-S1 forward
  pass per element (CPU, milliseconds, 2.8 MB).
- One run per task per arm; no tuning between arms; identical fixtures,
  budgets (≤20 calls / ≤180 s), and oracles.
- **Metrics:** task completion (oracle), incorrect values (validator
  refusals + `read_back_failed` + oracle mismatch), skipped fields,
  per-decision latency and end-to-end time, unsafe actions (must be zero in
  both arms), schema fallbacks (zero), orphans (zero).
- **Measurable success criteria (proceed/no-proceed):** treatment completes
  **≥ 4/5** and **≥ baseline**, with **zero unsafe actions** and **zero
  unauthorized submissions** in both arms; Cua-S1 decision latency
  **≤ 100 ms/element** on CPU; skipped-fields ≤ baseline. Met ⇒ proceed to
  the "Verified Form Copilot" vertical slice (document → extract →
  decide → verify → approve); not met ⇒ stop and report, no iterations on
  the five-task set.

## Dependencies and isolation

- New **separate venv** (Python 3.11.9 via the existing pyenv), installing
  `cua-s1` from the trycua repo + its deps (torch, safetensors, numpy) and
  `huggingface_hub` for the one-time weight download. The product venv and
  the stdlib-only `src/` invariant are untouched.
- Weights pinned under `models/cua-s1-forms/` with the JSON sidecar's
  SHA-256 tensor signature verified at load; recorded in the usual pin
  file. No network at run time.
- Licence: code MIT; weights MIT (model page); the model card notes future
  checkpoints may carry separate terms — re-check before any distribution.

## Rollback boundaries

Everything is additive. Rollback = delete `scripts/cua_s1_*.py`,
`src/vision_assistant/cua_s1_provider.py`,
`tests/test_cua_s1_provider.py`, the `models/cua-s1-forms` directory, the
separate venv, the `--decision-provider` flag (+ the new c21 dev task) —
returning the repository to the exact pre-integration state. No frozen
file, schema, policy, executor, or oracle is modified; no persistent state
exists outside `runs/` and the pinnable model directory.

## Non-goals / risks (from the model card, taken literally)

- Not a general computer-use agent; no unsupervised production use; not for
  high-impact decisions; apparent completion is never treated as proof (the
  repo's oracle + read-back remain the authority; human approval stays
  before any submission).
- Only chooses among candidates extracted from a document — our experiment
  builds those candidates from trusted spec data plus distractors and
  confuser pairs, so it cannot invent values.
- Small published real-world eval (196 decisions) — this is a research
  prototype comparison, not a certification.

## Stop point

Nothing beyond this document was done. Any installation, download, code, or
model run requires an explicit go-ahead.
