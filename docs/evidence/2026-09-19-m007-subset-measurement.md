# M007 subset measurement — OCR augmentation flips the failed case (user run)

Recorded 2026-09-19 on the user's machine. Run id
`subset-m007-20260919-230302-95ea55`; config: qwen3.5-4b, ctx 4096, evidence =
vision-ocr-apple, zoom ×2, literal. Result JSON copied beside this file as
`2026-09-19-m007-subset-measurement.json`.

Command:

```bash
PYTHONPATH=src python -m vision_assistant.augment_cli
```

Stdout (verbatim):

```
building the frozen corpus in memory...
m004-dialog-14           base=FAIL ui=0.00  ->  ocr=PASS ui=1.00  (facts=2, 1108 ms)
m004-small_text-13       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1234 ms)
m004-small_text-14       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1283 ms)
m004-small_text-15       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1353 ms)

summary: {"baseline": {"abstain_correct": 4, "forbidden_claim_total": 0, "passes": 3, "required_fact_recall_mean": 1.0, "ui_string_match_mean": 0.75, "unsupported_claim_rate_mean": 0.0}, "cases": 4, "ocr": {"abstain_correct": 4, "forbidden_claim_total": 0, "passes": 4, "required_fact_recall_mean": 1.0, "ui_string_match_mean": 1.0, "unsupported_claim_rate_mean": 0.0}}
gate: {"baseline_passes": 3, "dialog14_baseline_pass": false, "dialog14_ocr_pass": true, "forbidden_claim_total": 0, "ocr_passes": 4, "small_text_regressions": [], "unsupported_rate_sum": {"baseline": 0.0, "ocr": 0.0}}
```

## Gate reading

- `m004-dialog-14` — the single v4 held-out failure — **flips FAIL → PASS**
  (`ui_string_match` 0.00 → 1.00) with two OCR facts. The frozen zoom-×2 →
  literal-OCR pipeline recovers `UNSAVED REPORT`, which the model had missed
  and 1× OCR had misread (`UNSEVED BEFOBT`).
- Guard set `m004-small_text-13..15`: PASS at `ui 1.00` in both conditions —
  no regression.
- Unsupported-claim rate 0.0 in both conditions; forbidden claims 0; abstention
  correct 4/4 in both.
- Augmented model calls 1108–1353 ms — well inside the M005 ceilings
  (first 5 s / complete 20 s). OCR collection time was not yet recorded in
  this run; the harness now records `timing_ms.ocr_collect` for the next run.

## Privacy notes

- OCR text entered the model prompt only; no trace or result file contains
  fact text (the result JSON holds model answers on synthetic fixtures).
- No new permissions (Vision OCR needs none), no persistent artifacts.

## Pending

- Full held-out guard run (`--heldout-all`, 48 model calls): held-out must
  stay ≥ 0.95 with unsupported 0 and forbidden 0 before M007 closes.
