# M016 — evaluation and reciprocal learning field manual: build evidence and reference key

Date: 2026-09-20 (Australia/Sydney). Host: Apple M2 Max, macOS 27.0.
Commits: `0865fb3` (first build), `cb249e4` (component toggles + browser
verifications). Site: `http://127.0.0.1:4173/#manual` (served locally by
`scripts/serve_learning_lab.py`).

## What was built and verified

- Canonical real turn: `learning/data/canonical-turn.jsonl` (the M015
  smoke one-shot). Waterfall: total **1547.2 ms** — before-model 0.9 ms,
  model 1546.2 ms (**99.94%**), record 0.1 ms; first token 723.5 ms,
  complete 1528.5 ms.
- Failure catalog: 12 curated entries with component tags
  (capture/model/grounding/actions/runtime/packaging); every evidence path
  asserted to exist by tests.
- Model comparison: the selected Qwen3.5-4B (23/24, 3.792 GiB) beside the
  preserved losing run (11/24, first-token p95 7520 ms) and two unpinned
  candidates.
- 13 exact reproduction commands (per milestone, speed + model flags), the
  five teach-back tasks, and deterministic site data
  (`learning/eval_data.js` is the byte-compared golden of
  `evaluation_cli generate`).
- Browser-verified end-to-end: waterfall bars, comparison table, failure
  explorer live filter ("capture" → 1/12; component chip "capture" →
  3/12), teach-back checklists, copy buttons, and the quiz grader on both
  paths (wrong subset 3/5 → full set **5/5**).

## The five teach-back tasks — reference answers (answer key, not learner evidence)

The milestone gate is "a new learner can…"; the text below is the
reference key written from the project record so any learner (and the
closure review) can check depth. It is deliberately not presented as the
learner's demonstration.

1. **Trace a visual turn** — capture is explicit and least-scope; ingest
   normalizes and hashes the PNG privately; before-model is prompt
   assembly (plus OCR facts when enabled); the model stage measures first
   token (723 ms) and complete (1528 ms) separately; the trace keeps
   counts and labels, never screen text; the artifact is released by
   done. Honest limit: the waterfall says *nothing* about whether the
   answer is correct.
2. **Encoding vs generation** — a vision tower encodes the image into
   embeddings; the projector (mmproj) maps them into the language model's
   token space; the decoder generates text token-by-token with sampling —
   decoding, not retrieval. "The model sees the screen" fails because the
   decoder never receives pixels; image size costs tokens (the 4252 > 4096
   context incident is why `fit_for_model` exists).
3. **Diagnose one hallucination** — example f01: a dialog produced a
   causal "password problem" claim; cause: nothing separated visible facts
   from inference; fix: [visible]/[inferred]/[unknown] labels + abstention
   + unsupported-claim rate; removing the fix turns that rate (and
   forbidden-claim counts) red in the frozen gate; evidence:
   `docs/evidence/2026-09-19-user-v4-results.json`.
4. **Add a frozen fixture** — procedure executed as a worked example below:
   author the case in the category's table, regenerate with
   `corpus_cli --freeze`, re-verify (`deterministic=True`, gold and bad
   100%), and record the deliberate change. Hashes are allowed to change
   *because* the freeze is a recorded act; editing a frozen case without
   re-freezing is a measurement bug — the manifest no longer describes
   what runs.
5. **Why the model never owns an action** — it may only propose; strict
   schema rejects coordinates; policy disposes (budgets, scope, secrets);
   the plan binds to a stable element identity from a fresh read-only
   snapshot; the user confirms; a freshness re-check runs; exactly one
   writer artifact posts (AXPress / value write with read-back); a
   post-action observation verifies; `unapproved_actions` must stay 0;
   budgets, takeover detection, and typed blocked states bound the loop.

## Worked example — the fixture procedure, executed and reverted

Baseline: `corpus_cli --verify` → `deterministic=True`,
`gold_pass=120/120 bad_fail=120/120`, PASS.

Temporary patch (one new held-out dialog case, "BACKUP COMPLETE" /
"VERIFY THE ARCHIVE BEFORE DELETING ORIGINALS", generation range 15→16 for
the dialog category only):

```
$ corpus_cli --freeze
cases=121 dev=24 heldout=25 legacy=72

$ corpus_cli --verify
deterministic=True
gold_pass=121/121 bad_fail=121/121
PASS
```

Then `git restore src/vision_assistant/corpus.py` and a re-freeze restored
the 120-case baseline (verify: PASS, 120/120 both ways). The working tree
is clean; the generated artifacts under `runs/m004-corpus/` (git-ignored)
describe the baseline again.

## Gate status

Mechanical surfaces: complete and verified (tests + live browser).
Reference key and a fully executed fixture-procedure example: recorded
above. The human learner demonstration (a person completing the five
tasks) remains open; the field manual, the checklists, and the quiz are in
place for it, and this document records the depth expected.
