# Results — measured boundaries, failure analysis, and how to reproduce

Status: **active (2026-09-20).** Every number below is a measured result of a
frozen run on this machine. Evaluation sets are frozen before measurement,
never reused for tuning, and every failed run is preserved. Companion
documents: `VISION_STATE.md` (canonical chronological record),
`docs/MILESTONES.md`, `docs/METRICS.md`, `docs/ARCHITECTURE.md`,
`docs/EXECUTION_PLAN.md` (stop rules for new experiments).

## The browser-use arc (M018–M023)

The first arc (M001–M017, complete) built and packaged a private, local
screenshot-understanding assistant. The second arc extends the lab into
supervised computer use on a loopback browser fixture — one frozen
milestone at a time:

| milestone | what it tested | set | measured result | evidence |
|---|---|---|---|---|
| M018A | fixture + oracle foundation | 50 tasks | manifest deterministic; every positive passes; mutations and adversarial probes rejected | `docs/evidence/2026-09-20-m018a-manifest-oracles.md` |
| M018D | screenshot-only agent | 18 held-out | 3/18 | `docs/evidence/2026-09-20-m018d-benchmark.md` |
| M018T | + visible target list (paired) | 18-task paired eval | baseline 1/18 → treatment 6/18 | `docs/evidence/2026-09-20-m018t-eval.md` |
| M019D | typed actions, permissive schema | frozen 20 | 10/18 productive; refusals 2/2; zero forbidden | `docs/evidence/2026-09-20-m019d-eval.md` |
| M020 | exact per-action schemas | frozen 20 | **15/18 + refusals 2/2; zero forbidden; zero fallbacks** | `docs/evidence/2026-09-20-m020-stage4-eval.md` |
| M021 | live Hacker News read (answer mode) | live page | answer incorrect (0/3); run hygiene perfect (7 calls, zero forbidden / fallbacks / orphans) | `docs/evidence/2026-09-20-m021-hn-transfer.md` |
| M022 | multi-viewport evidence ledger | 5-task dev smoke | gate 0/5; **evidence architecture fixed** (selections span viewports); model-side walls remain | `docs/evidence/2026-09-20-m022-dev-smoke.md` |
| M023 | Cua-S1 specialist decision provider | 4 dev form tasks | specialist **1/4** vs vision **4/4** ⇒ GATE FAIL; stopped per freeze | `docs/evidence/2026-09-20-cua-s1-spike.md` |

These are different sets measured at different stages — the table is an arc,
not one controlled comparison. Within M018T and M023 the comparison is
paired on identical tasks.

## What is fixed, and what is still open (failure analysis)

Every class below was observed in a frozen run and preserved in the
evidence; "fixed" means a later frozen run demonstrated the countermeasure
working under the same or stricter conditions.

**Fixed (with the frozen run that shows it):**

- **Click temptation** (M018E): a live pilot clicked uselessly because
  clicking was available. The read-only M021 lane emits zero interaction
  attempts on the same class of pages (7 calls, 0 forbidden).
- **Schema-shape pollution** (M019D): 27 refusals came from neighbouring
  reply fields surviving decoding. Exact per-action `oneOf` schemas with
  `additionalProperties: false` (M020) made the pollution inexpressible:
  zero shape refusals in the frozen run; forms 5/7; total 15/18.
- **Cross-viewport evidence loss** (M021): the model answered from the last
  screenshot while the correct facts sat in earlier frames. The M022
  trusted ledger produced final selections whose evidence spans multiple
  observations (obs-2/3/5 and obs-1/3), with dedup and conflict rejection
  firing live.
- **Stale/duplicate action churn** (M019–M020): repeated value actions are
  now refused with hints instead of hard-blocking, and read-back-verified
  value actions no longer arm the no-change guard — c16, the last miss of
  the M020 Stage-3 run, passes on re-measure (M023 Arm A: 4/4).
- **Structural containment** (every run): raw clicks and typing at large,
  credential controls, and unauthorized submits are not expressible in the
  typed action set or the validator. Zero unauthorized actions in every
  frozen run; the one historical submission attempt (M018T `t20`) predates
  the typed lane and is recorded.

**Open (model-side walls, honestly measured):**

- **Classification under decoys** (M022): confusable stories marked
  primary (computer-science-adjacent and biology decoys).
- **Loop discipline** (M022): repeated legal `no_candidates` stalled three
  tasks to the call budget instead of advancing viewports.
- **Transcription precision** (M022): titles keep their "(domain)"
  suffixes.
- **Live cross-screen synthesis** (M021): reading a live page's top stories
  correctly remains unsolved for the pinned 4B model.
- **Specialist vocabulary transfer** (M023): Cua-S1-FORMS skips elements
  whose labels sit outside its trained vocabularies and picked a confuser
  value at 57 % — with the pipeline proven faithful (top-1 0.9704 on 744
  fresh synthetic rows vs published 0.9994), so the limitation is the
  checkpoint's distribution, not the integration.

## Reproduce the deterministic gates (no model, no network)

Last verified 2026-09-20 — full transcript:
`docs/evidence/2026-09-20-reproduce-gates.txt`.

```bash
# M018A gate: fixture build, manifest, oracles, adversarial probes
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli verify

# M019 deterministic checks + six scripted typed scenarios (no model)
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m019-verify
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m019-scripted

# M020 / M022 freeze checks and the multi-viewport scripted loopback check
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m020-eval --check-only
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m022-hn --scripted-check

# the full test suite: 674 = 664 product + 10 learning
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

The model-gated runs — one run per task, frozen budgets, `--require-schema`
— are documented with their exact commands in each evidence document. The
live Hacker News lanes (`m021-hn`, `m022-hn`) additionally require an
explicit go-ahead and a single opted-in live host.

The optional Cua-S1 path (separate Python 3.11 environment):

```bash
.venv-cua-s1/bin/python scripts/cua_s1_validate.py --episodes 30   # pipeline fidelity
.venv-cua-s1/bin/python scripts/cua_s1_scoring.py                 # pinned decisions
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m019-dev \
    --ids c16,c17,c18,c20 --decision-provider cua-s1
```

## Pins and artifacts

- Model: Qwen3.5-4B Q4_K_M + mmproj under `models/qwen3.5-4b/` (local pin).
- Optional specialist: `docs/evidence/cua-s1-spike/pin.json` (weights and
  decisions SHA-256s; the pickle checkpoint was intentionally never
  downloaded — the loader rejects pickle by design).
- Runs and screenshots live under `runs/` (Git-ignored); every committed
  claim links to `docs/evidence/`; `VISION_STATE.md` records each executed
  run in chronological order.

## The rules that keep these numbers honest

- **Freeze first:** tasks, budgets, success criteria, and stop conditions
  are committed before any model call.
- **One run per task; no retries; no tuning on a measured set; failed runs
  are recorded, not rescued.**
- **Every step ends** with a commit, an evidence document, and a short
  report — governed by the short-box rules in `docs/EXECUTION_PLAN.md`.
