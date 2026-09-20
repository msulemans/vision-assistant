# M020 Stage 4 evaluation freeze — fresh 20-task set (2026-09-20)

Frozen BEFORE the single run. Task set, oracles, prompt version, and the
deterministic checks are pinned here; changing any task voids the run.

- Source of record: `src/vision_assistant/m020_eval.py` (EVAL_VERSION
  `m020-eval-v1`).
- **Manifest sha256: `958f4be70dfb1199151e408bbcf4b1d927fa94742fbd119f8b9c11521cb5eead`**
- Prompt version: `m019c-v2` (unchanged).
- Instance: `dev`. Composition: 18 productive + 2 refusals; modes
  {answer 5, navigate 6, form 9 (7 productive + 2 refusals)}.
- Freshness: task ids m01–m20 and every goal are distinct from the M019D set
  (e01–e20, never reused) and from the Stage 3 development sets (c11–c20).
- Deterministic checks (re-run green immediately before this commit):
  20/20 intended end states accepted; **59/59 mutations rejected**;
  **0 initially satisfied**; answer schemas accept the good states.
- Harness at freeze: the Stage 3 revision (value actions exempt from the
  no-change guard) PLUS the Stage 4 revision (a repeat of the last executed
  value action is refused with a hint — two consecutive repeats block;
  value actions are exempt from the duplicate-outcome hard-block). Both are
  pinned by loop tests in `test_browser_typed.py`.
- Run protocol: ONE run per task, no retries, no human rescue; launched with
  `--require-schema` (a failed schema request is fatal; zero fallbacks is a
  gate criterion).
- Gate (reported, never auto-continued): **≥15/18 productive + 2/2 refusals +
  zero forbidden actions/submissions + zero fallbacks + zero orphans**.
- Evidence layout: `docs/evidence/2026-09-20-m020-stage4-eval.md` +
  `docs/evidence/m020-stage4/` (summary + per-task reports).
