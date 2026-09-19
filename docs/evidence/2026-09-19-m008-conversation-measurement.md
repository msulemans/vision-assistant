# M008 measurement — bounded conversation passes 6/6 (user run)

Recorded 2026-09-19 on the user's machine. Run id
`m008-20260919-231017-f40d4a`; config: qwen3.5-4b, ctx 4096, no OCR evidence.
Result JSON copied beside this file as
`2026-09-19-m008-conversation-measurement.json`.

Command:

```bash
PYTHONPATH=src python -m vision_assistant.conversation_cli
```

Stdout (verbatim):

```
building the frozen corpus in memory...
ref-dashboard-14       PASS  (all present)  follow=1143 ms  released=True
corr-dashboard-14      PASS  (corrected)  follow=1138 ms  released=True
ref-terminal-15        PASS  (all present)  follow=1422 ms  released=True
corr-terminal-15       PASS  (corrected)  follow=1573 ms  released=True
ref-small_text-13      PASS  (all present)  follow=1615 ms  released=True
corr-dialog-13         PASS  (corrected)  follow=1300 ms  released=True

summary: {"all_released": true, "correction_passes": 3, "correction_total": 3, "max_prompt_chars": 333, "prompt_bounded": true, "reference_passes": 3, "reference_total": 3, "tasks": 6}
```

## Gate reading

- **Reference 3/3**: follow-ups carried the earlier turn's fact
  (`87`+`charging`; signal `9`; `midnight`).
- **Correction 3/3**: each false premise (`12%`, `disk problem`, `session
  saved`) was contradicted with the true value.
- **Bounded**: longest composed prompt 333 characters (budget 4000; stale and
  turn limits enforced by typed errors, covered deterministically).
- **No cross-session content**: each task ran in a fresh session bound to one
  capture; history resets were exercised in `tests/test_conversation.py`.
- **No retained artifacts**: `all_released: true` — every session's reset
  deleted its private artifact.
- Follow-up model calls 1138–1615 ms, consistent with the M005/M007 records.

## Conclusion

The frozen M008 gate ("reference and correction tasks pass; no screenshot
crosses sessions; prompt growth and retained artifacts stay bounded") is
satisfied on the pinned configuration. M008 closes; next milestone is M009 —
usable capture and answer UI.
