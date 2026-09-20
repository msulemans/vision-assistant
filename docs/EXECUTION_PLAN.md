# Execution plan — short boxes, hard stop rules

Status: **active plan (2026-09-20, owner-directed).** This sequences the
remaining work so every step ends inside a short, verifiable box — not
ten-hour cycles. It changes no frozen artifact. Companions:
`docs/CUA_S1_INTEGRATION_PLAN.md` (the next spike, amended 2026-09-20),
`docs/NEXT_EXPERIMENT_OPTIONS.md` (deferred model options), `VISION_STATE.md`
(measured results of record).

## Why earlier cycles ran long (diagnosis, recorded so it does not repeat)

- Single sessions bundled design + harness build + fixture authoring + a
  20-task model gate + scoring + surface edits, with no declared budget.
- Discovery runs (full suite ≈ 4.4 min; live-site checks) were mixed into
  development loops where they answered no question.
- The model gate is the slow part (a frozen 20-task run: 45–100
  generations, ~1–2 h); everything around the gate is fast and can be done
  first, deterministically.
- Mid-run scope additions (the Laya class of change) restarted research
  after implementation had begun.

## Short-box rules (apply to every step)

1. **One experiment per session.** Declare it in one line; nothing else
   gets modified; scope additions go to the deferred list.
2. **Freeze before any model call:** tasks, budgets (calls/seconds),
   success criteria, stop conditions — committed first. The freeze commit
   is the go-signal.
3. **Deterministic first:** build + focused tests run without the model or
   the network. The model gate runs **once per task**; no retries, no
   post-run tuning, no rescue runs.
4. **Focused sweeps only** (explicit module list, always including
   `test_m015_invariants` + `test_package_cli`). Full suite only at
   closure, in the background, captured to a file.
5. **No live-site checks in dev loops.** One publication check per push
   boundary.
6. **A failed gate ends the step:** evidence doc + commit + one-paragraph
   report. The next step is separately approved.
7. **Box discipline:** ≤ 2 hours per step; at the box edge, stop at the
   nearest safe point and report (never leave the tree mid-change).
8. **Report format per step** (≤ 10 lines): files changed; focused test
   count; measured results; budget spent (calls/seconds); next step +
   go/no-go.

## The remaining road

Not on the road (owner decisions): further harness iterations for the 4B
generalist lane — M022 was the last; revisiting that lane means a stronger
model under the frozen harness. No Laya work before Step 1 reports.

### Step 1 — Cua-S1 four-task form spike (EXECUTED 2026-09-20; RESULT: GATE FAIL — 1/4 vs baseline 4/4; stop per the frozen route; report: `docs/evidence/2026-09-20-cua-s1-spike.md`)

Pointer: `docs/CUA_S1_INTEGRATION_PLAN.md` (amended: four existing tasks —
c16/c17/c18/c20; no new authoring; two-hour box).

| segment | content | budget |
|---|---|---|
| T1 (≤ 30 min) | Separate 3.11 venv + `cua-s1` + weights (2.8 MB) + SHA-256 pin; `scripts/cua_s1_scoring.py` writes the pinned `decisions.json` | one-time network, no model run |
| T2 (≤ 45 min) | `cua_s1_provider.py` + `test_cua_s1_provider.py` + additive `--decision-provider` flag (dev lane only); focused sweep green | 0 model calls |
| T3 (≤ 30 min) | Arm A vision re-measure on the four tasks; Arm B Cua-S1 run (one run per task per arm) | ≤ 80 vision calls (Arm A only; Arm B = 0) |
| T4 (≤ 30 min) | Evidence report + comparison table + commit/push | — |

**Gate (frozen before T3):** Arm B completes **≥ 3/4** and **≥ Arm A**;
**zero unsafe actions / zero unauthorized submissions** in both arms;
Cua-S1 ≤ 100 ms/element; skipped fields ≤ Arm A.
**Pass ⇒ Step 3 is eligible. Fail ⇒ stop, report, no iterations.**
Laya: deferred; one mention in the evidence report; nothing else.

### Step 2 — Package the proof (EXECUTED 2026-09-20 — deliverables: `docs/RESULTS.md`, control-plane diagram in `docs/ARCHITECTURE.md` + README, failure analysis, reproduce transcript at `docs/evidence/2026-09-20-reproduce-gates.txt`)

The measured boundary this project has reached is the asset ("show your
work"). One step makes it legible to outsiders:

- `docs/RESULTS.md`: the benchmark table across milestones (below), each
  row with its evidence-doc link and run directory.
- One architecture diagram (mermaid, in `docs/ARCHITECTURE.md` and the
  README): the typed-action control plane — model proposes, code
  validates/executes, read-back verifies, oracle scores, human approves.
- Failure analysis: the four walls and their status — clicking temptation
  (fixed), schema shape (fixed, M020), cross-viewport memory (fixed,
  M022), classification/transcription/loop discipline (open, measured).
- Reproduce: copy-paste commands for the deterministic gates plus the
  no-model demo path (scripted loopback checks) and where every artifact
  lives.
- Surface sync: README "results at a glance" + learning-site figures only
  if code/census changed.

Ships with no model runs and no network.

### Step 3 — Product slice: Verified Form Copilot (NOT eligible — Step 1 failed; retained only for a future approved revisit)

Eligible only if Step 1 passes. Local, fake data, human approval before
submission:

```
document → candidate values → Cua-S1 option scores → typed policy
        → executor → read-back verification → human approves submission
```

Slice-1 acceptance (frozen before implementation, not now): 5 canned
documents × 5 fixture forms, end-to-end, zero unsafe actions, approval gate
proven, replayable evidence, ≤ 100 ms/decision. Details are written at
freeze time — that keeps this document from becoming another wish list.

## Deferred candidates (recorded; do not start)

- **Laya** — classification/routing/escalation; needs its own dataset +
  calibration; explicitly out of scope until Step 1 reports (see the
  Cua-S1 amendment).
- **Later CUA-S1 family members** — only FORMS is in scope.
- **Stronger generalist vision model (8B–14B)** under the frozen M020/M022
  harnesses — the fair re-test if the 4B line is reopened
  (`docs/NEXT_EXPERIMENT_OPTIONS.md`, option A).
- **Cua Driver / Lume / Cua-Bench** — only if Step 3 justifies them.

## Standing measured results (context)

| milestone | set | result |
|---|---|---|
| M018D screenshot-only | 18 held-out | 3/18 |
| M018T target-assisted | paired eval | 1/18 → 6/18 |
| M019D typed actions | frozen 20 | 10/18 + refusals 2/2; zero forbidden |
| M020 exact schemas | frozen 20 | **15/18 + 2/2; zero forbidden, zero fallbacks** |
| M021 live HN read | live page | FAIL on correctness (0/3); hygiene perfect |
| M022 evidence ledger | dev smoke | gate 0/5; **architecture fixed** (cross-viewport selections worked); model walls remain |

Evidence: `docs/evidence/` for every row. Frozen sets are never reused for
tuning; every model spend is budgeted and reported.
