# Next experiment after M019D — options memo

Status: **DRAFT for owner review** (written autonomously 2026-09-20 while the
owner was away). Nothing in this document has been approved, started, or
executed. The M019D results stand exactly as measured, and the frozen
evaluation set (e01–e20, manifest sha `9d09438d…`) is never reused for
development.

The plan of record (`docs/M019_TASK_TYPED_AGENT_PLAN.md`) says: *"The next
experiment is a separately approved model comparison, not further prompt
iteration (not started)."* This memo re-examines that choice against evidence
found in the frozen run's own artifacts, and lays out the options. It changes
nothing; it proposes what a next freeze could contain.

## 1. Where things stand

| stage | set | result |
|---|---|---|
| M018D screenshot-only | 18 held-out | 3/18 |
| M018T target-assisted | paired eval | 1/18 → 6/18 |
| M019 typed (M019D) | frozen 20 | **10/18** productive; refusals 2/2; zero forbidden |

(Different sets — context, not a controlled comparison. On top of these, the
M018E live pilot was executed and closed as a failed run.)

Everything failed closed; the form family failed 0/7. The open question moved
from safety (structurally enforced and repeatedly demonstrated) to *why output
that was often semantically correct was still being refused*.

## 2. Sharpened diagnosis — from the frozen artifacts, no new runs

Reading the M019D run's own task reports and `server.log` established three
facts that were not previously connected:

1. **The typed lane already used schema-constrained decoding.** Every typed
   model call passed `json_schema=browser_agent.typed_action_schema(mode)`
   (`browser_cli.py:883-885`), which the adapter sends as
   `response_format: {"type": "json_object", "schema": …}`
   (`runtime_llamaserver.py:229-230`). M019D was **not** a free-form decoding
   run.
2. **No silent fallback occurred.** `model_proposer` (`browser_agent.py:155`)
   falls back to unconstrained decoding on any exception; request accounting
   on the frozen run rules that out for M019D: `server.log` generations
   (`launch_slot`) = **45** = sum of loop calls = 32 `proposal` + 13 executed
   `action` steps across the 20 task reports. One generation per call, no
   retries.
3. **The schema that constrained those 45 generations is a permissive union.**
   `typed_action_schema(mode)` (`browser_agent.py:188-213`) lists **every
   field of every allowed action** as an *optional* property (`text`,
   `option`, `value`, `direction`, `amount`, `seconds`, `answer`, `reason`, …)
   and requires only `action`. `additionalProperties` is left unspecified
   (JSON-Schema default allows extras). Either way, the decoder was free to
   append any same-mode field to any action.

The frozen refusals are exactly what that predicts. Across all 45 generations,
every refusal is validator-level (no proposal ever failed as invalid JSON —
the grammar was shaping output), and the taxonomy is two families:

- **27 shape refusals** (`unexpected field …`): **21** = all 7 form tasks × 3
  steps (`option` on `fill_field`; `reason` on `select_option` /
  `set_toggle` / `fill_field`; `amount` on `fill_field`), plus **6** = the two
  refusal tasks (e19/e20, 3 each — their safe stop was validator-driven, as
  the evidence doc already annotates);
- **5 type refusals** (`points` / `comments` must be integer) — all in the
  answer family (e01, e02, e03, e05), **all self-corrected**; those tasks
  finished.

So: the 4B model's *core* values were usually right; the harness let
neighbouring reply shapes survive decoding, then its strict contract refused
every polluted proposal, so nothing executed. The measured wall is **a schema
that permits the pollution**, not free-form decoding — which makes the
highest-value next change almost certainly harness-side and cheap.

## 3. Options

### B′ — exact-shape harness phase (recommended M020 candidate)

One sentence: make the constrained-decoding schema *exact per action* so
cross-talk fields are not expressible, then re-measure on fresh tasks.

Sketch (for the eventual freeze doc — nothing here is executed):

1. `typed_action_schema(mode)` becomes per-action branches (`oneOf`); each
   branch has only that action's fields, `additionalProperties: false`, and
   `required` mirroring the validator's contract (e.g. `target_ref` +
   `observation_id` for mutating typed actions).
2. Strict validation stays unchanged as defense-in-depth — it remains the
   contract of record; the grammar merely stops generating refusable shapes.
3. Instrument the proposer: record per call whether the schema request
   succeeded or the unconstrained fallback was used. In evaluation mode a
   silent downgrade must be impossible (counted, ideally fatal).
4. Prompt: keep `m019c-v2` for the first measurement (one variable at a
   time), or a single documented revision if required. Decision at freeze.
5. Deterministic tests: schema exactness per mode/action; fallback recording;
   prompt↔schema consistency; the frozen M019 invariant suite must still pass
   unchanged.
6. Staged gates mirroring M019: deterministic verify (no model) → scripted
   scenarios (no model) → fresh dev tasks with the model (≥4/5 + correct
   refusal + zero forbidden) → freeze a **new** 20-task evaluation (18 + 2,
   no initially-satisfied) → exactly one run.

Expected effect: converts the form family if the diagnosis is right (core
values were already correct). It also removes the e19/e20-class *passive*
safety (their stop was a refusal-loop artifact); safety must then rest on the
structural credential/submission denials — which exist and are tested — and
the refusal outcomes must be re-measured honestly on the fresh set.

Risks / unknowns: llama.cpp semantics for `oneOf` + `additionalProperties:
false` at the pinned build (0.3.0 build 10621); empty-string values remain
expressible under grammar (validator keeps min-length checks); the model may
still pick wrong targets or miss values — measured by the oracle, never
assumed.

Cost: no model download; ~1 focused implementation day + one dev run + one
frozen eval run.

### A — model comparison (the plan's named step; second priority)

Same harness, one same-family larger model (8B–14B class, Q4_K_M + matching
mmproj). This Mac: 32 GB RAM / ~60 GB free disk (sufficient; expect a ~5–9 GB
download). Answers: does exact-shape compliance and task success scale with
capacity. Rationale for ordering: run it **after** B′ so capacity is compared
under a shape-clean harness; otherwise the comparison mostly re-measures shape
noise. Needs its own pin + freeze; M019D remains the 4B reference.

### C — stop here

Defensible. The lab has honest measured boundaries (3/18 → 6/18 → 10/18, all
failures closed, evidence for every claim). Stopping loses only the
newly-opened shape-emission question.

## 4. Recommendation

1. Freeze **B′** as the next phase. Its deterministic half (schema exactness +
   fallback recording + tests) exercises without the model; its model half
   runs on fresh tasks against a fresh freeze.
2. Then, separately approved, **A** on top of B′.
3. Never tune on the M019D frozen set; never auto-continue past a gate; not a
   prompt-iteration exercise (that budget was spent at M019C).

## 5. Execution ledger of this memo

Done, all without model / browser / live runs and without touching any frozen
evidence: read the M019D task reports + `server.log`; reconciled request
accounting (45/45/45); classified every refusal in the run (27 shape / 5
type); verified the pinned runtime's constrained-decoding support
(`llama-server` 0.3.0 build 10621 with `--grammar`, `--json-schema`; the
adapter already sends a per-request schema); ran a full-suite regression
check.

Not done (deliberately): no model, benchmark, held-out task, dev task, or
live-site run; no edits to M018/M019 evidence, scores, prompts, benchmarks, or
product code.

## 6. First commands of the proposed phase (for the future freeze only — NOT executed)

```sh
# after implementation of the exact-shape schema + proposer instrumentation,
# the unchanged M019 deterministic gates must still pass:
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m019-verify
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m019-scripted   # no model
# then (only after a committed freeze): fresh dev tasks with the pinned model,
# then one frozen run on the new set — exact commands defined in that freeze doc.
```

## 7. Postscript — full-suite regression (added after the memo's first commit)

The full-suite discovery run performed for this memo found **4 failing tests,
all one root cause**: the frozen M015 offline audit flagged
`browser_agent._path_only` (a bare scheme separator in its source) — present
since the M018C commit `af926da` and never caught, because the audit modules
were not part of any focused sweep.

Fixed behavior-preservingly: the helper now strips the **explicit loopback
prefixes** (the only absolute URLs the loopback-only browser can produce);
non-loopback absolute URLs pass through unchanged instead of being silently
masked; parity for the loopback domain is pinned by a new test
(`test_browser_agent.test_path_only_normalizes_loopback_urls`).

Full discovery afterwards: **555 tests, 258.8s — OK, 0 failures, 0 errors**
(the first complete green discovery run of the M019 tree).

The published test-count figures were also stale by one stage: the real
census is **555 = 545 product + 10 learning** (the site and its pin previously
said "544 = 538 + 6"); corrected on the landing chip, the learning page, and
the site pin.

Lesson recorded: closure sweeps must include the audit modules
(`test_m015_invariants`, `test_package_cli`) — the focused-sweep pattern let a
frozen-invariant break sit unnoticed for half a day.
