# M011 simulated action loop — all tasks done, zero host input (user run)

Run `m011-20260919-233401-317621` (user machine, pinned Qwen3.5-4B). Result
JSON copied beside this file as `2026-09-19-m011-simulated-loop.json`.

Command:

```bash
PYTHONPATH=src python -m vision_assistant.sim_cli
```

Stdout (one task shown; the other two are identical in shape with
`click_element` / `press_key`):

```
=== enable-sync: Turn on the Sync checkbox.
   0   observe {"revision": 0}
   1   propose {"count": 1}
   2  validate {"index": 0, "kind": "click_element", "parsed": true,
               "verdict": "needs_confirmation", ...}
   3   approve {"approved": true, "approved_by": "simulation", ...}
   4   execute {"applied": true, ...}
   5    verify {"passed": true}
   6      done {"reason": "verified", "steps": 1}
  -> DONE (verified, 1 steps)

summary: {"all_done": true, "tasks": {"enable-sync": {"status": "done", "steps": 1,
  "host_input_events": 0}, "type-search": {...}, "cancel-dialog": {...}}, "total_ms": 5358.0}
```

## Gate reading

- **Frozen tasks complete within budget**: all three (enable Sync, type
  "hello" into Search, close the dialog via Escape) finished in **1 of 12
  allowed steps**, verified against app state predicates — not model claims.
- **Zero host input events**: `host_input_events: 0` per task; a
  source-scan test proves the three M011 modules contain no execution
  capability. Execution mutated a Python object only.
- **Denial/cancel/approval/staleness are final**: proven by the 12
  deterministic loop tests (denied intent never executes; approver denial
  blocks; a changed revision refuses the stale intent; emergency stop and
  cancel end the loop).
- Model-proposed intents passed the M010 schema and policy exactly as
  designed (`needs_confirmation` → simulated approval inside the sandbox).

## The road to this run

Attempt 1 (`m011-20260919-233218-1b0550`) blocked all three tasks with
`no_proposal`: the model would not emit JSON through prompt scaffolding even
with a repair attempt — fail-closed worked (bounded retries, zero host
events). Fix (`d4ce92d`): schema-constrained decoding in the runtime
(`response_format.json_schema`; llama.cpp converts it to a grammar), used
first by the proposer with a prompt-only fallback, plus raw-answer recording
for diagnosis. The constrained decoder produced a valid intent array on the
first try of every step.
