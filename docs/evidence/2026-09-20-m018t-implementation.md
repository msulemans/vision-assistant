# M018T implementation — deterministic gates green; scripted smoke blocked by locked console

Date: 2026-09-20 (Australia/Sydney). Stage: M018T (target-assisted observation
treatment), implementation phase per `docs/M018T_TARGET_ASSISTED_PLAN.md`.
**Model runs performed under this treatment: ZERO.** The M018A–D record and its
frozen benchmark remain untouched; the baseline manifest sha is still
`df630b21…` (pinned by a new regression test).

## What was built (plan §10, exactly)

- `src/vision_assistant/browser_targets.py` (**new**, pure/inert): frozen
  constants (MAX_TARGETS 40, LABEL_CAP 80, MIN_VISIBLE 2.0, MOVE_EPS 2.0),
  7-role allowlist, `TargetEntry`, `sanitize_label`, `valid_target_id`,
  `validate_target_action` (raw `click` rejected in target mode; membership
  check against the current list), the CSS→screenshot→model display-chain box
  math, `rect_changed` mirror of the helper's moved rule, the frozen
  `m018t-v1` prompt builder, and the five refusal hints.
- `tools/browser_window.swift`: `targets` command (frozen extraction script
  compiled in — never sent over the protocol; visible rendered surface only)
  and `click_target` command (id resolution + live re-validation: stale /
  hidden / disabled / moved >2 CSS px / offscreen; click at the fresh centre
  through the single shared in-app NSEvent synthesis path). Compiles clean
  (`swiftc -O`).
- `src/vision_assistant/browser_session.py`: `TargetList`, `targets()`,
  `click_target()` with fail-closed prechecks (nothing is written to the
  helper on refusal); `click_target` added to the budgeted `ACTION_COMMANDS`.
- `src/vision_assistant/browser_agent.py`: additive `mode="screenshot"|
  "target"` routing (prompt, schema, execution); the baseline path is
  unchanged and pinned by the previous tests; new prompts use
  `PROMPT_VERSION="m018t-v1"` and the five new refusal hints.
- `src/vision_assistant/browser_cli.py`: `task --mode target` (runs under
  `runs/m018t-*`, summary stage `M018T`) and the new scripted
  `target-smoke` subcommand (no model).
- Tests: `tests/test_browser_targets.py` (21) and
  `tests/test_browser_target_agent.py` (12) new; `test_browser_session.py`
  +7 (fake-helper target protocol, no-send guarantees, budget);
  `test_m018_invariants.py` +2 (extraction-script privacy scan — banned
  tokens; five refusal codes in the helper) plus the deliberate
  `ACTION_COMMANDS` tuple update; `test_browser_tasks.py` +1 (baseline
  manifest sha pin).

## Deterministic gates (all green)

- M018T sweep (targets + target-agent + session + agent + invariants +
  tasks + fixture-server): **113 tests, OK**.
- Full suite discovery: **450 tests = 444 product + 6 learning**.
- `swiftc -O tools/browser_window.swift` — clean compile.
- Baseline manifest sha256 `df630b21d9a0330214bb5cf01e0892ad82f589e5cb4206e81ff38af54f43d510`
  unchanged (pin test).

## Scripted live target-smoke — attempted twice, blocked on environment

Both attempts (`2026-09-20-m018t-smoke-attempt{1,2}-locked-console.json`) ran
while **the console was locked** (user away; `ioreg` → `IOConsoleLocked`).
Results are consistent across attempts:

- **Deterministic layers passed:** launch; navigate; snapshot; target
  extraction (19/19 targets on `/news/`, document order, clipped boxes);
  adapter-side stale refusal after a new snapshot (`refused_target_stale`,
  nothing sent to the helper); zero orphan processes; temporary snapshot
  directory cleaned.
- **WebKit interactive layers did not process:** `click_target` on the
  rank-3 story link did not navigate (URL stayed `/news/`), and on the search
  page a field click did not set focus in time for typing
  (`refused_focus`). The `/layout/` shifted-target demo was not observable
  (fresh rects equal → not refused).
- **Isolation probes (scratch, not committed):** (a) a raw click at the
  **exact M018B known-good point (900,445)** — which navigated to
  `/story/d03/` when the user was present — no longer navigates, verified
  with a 3.3 s wait; both click paths (raw and `click_target`) fail
  identically at the same CSS point. (b) Mouse event *delivery* is not dead:
  one probe click did focus a text input. (c) Page timers fire (a
  `setTimeout`-inserted link appeared on `/slow/`), but the `/layout/`
  CSS transition did not tick under the locked display.

**Interpretation (recorded honestly):** this is an environment condition,
not an M018T regression — the identical click sequence over the identical
protocol was green in the M018B session when the console was unlocked, and
no M018T code runs on the raw-click replay path other than the shared
synthesis helper (behavior-identical refactor, verified by the replay
failing for the OLD path too). Live interactive verification requires an
unlocked console.

## Status and next step

- Implementation complete; deterministic gates green; **the scripted live
  target-smoke must be re-run on an unlocked console (review checkpoint 2)
  before ANY model run.**
- The five smoke model runs (02/11/41/43/45) remain **not performed**;
  nothing in this document claims a capability result.

> Update later the same day: the smoke was re-run on an unlocked console —
> scripted smoke PASS; the five-task model batches measured 3/5 → 4/5
> (initial → one recorded revision), separately labelled. See
> `docs/evidence/2026-09-20-m018t-smoke.md`.

## Reproduction

```
PYTHONPATH=src .venv/bin/python -m unittest tests.test_browser_targets \
  tests.test_browser_target_agent tests.test_browser_session tests.test_browser_agent \
  tests.test_m018_invariants tests.test_browser_tasks tests.test_fixture_server
swiftc -O tools/browser_window.swift -o runs/m018-tools/browser_window
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli target-smoke   # needs an unlocked console
```
