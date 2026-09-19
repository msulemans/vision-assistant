# M007 held-out measurement — 24/24 with OCR evidence (user run)

Recorded 2026-09-19 on the user's machine. Run id
`subset-m007-20260919-230357-585e6a`; config: qwen3.5-4b, ctx 4096, evidence =
vision-ocr-apple, zoom ×2, literal. Result JSON copied beside this file as
`2026-09-19-m007-heldout-measurement.json`.

Command:

```bash
PYTHONPATH=src python -m vision_assistant.augment_cli --heldout-all
```

Stdout (verbatim):

```
building the frozen corpus in memory...
m004-terminal-13         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1420 ms)
m004-terminal-14         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1378 ms)
m004-terminal-15         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1434 ms)
m004-dialog-13           base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1339 ms)
m004-dialog-14           base=FAIL ui=0.00  ->  ocr=PASS ui=1.00  (facts=2, 1248 ms)
m004-dialog-15           base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1283 ms)
m004-form-13             base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=5, 1272 ms)
m004-form-14             base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=5, 1302 ms)
m004-form-15             base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=5, 1398 ms)
m004-settings-13         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=4, 1374 ms)
m004-settings-14         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=4, 1451 ms)
m004-settings-15         base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=4, 1421 ms)
m004-dashboard-13        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1308 ms)
m004-dashboard-14        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1314 ms)
m004-dashboard-15        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=3, 1319 ms)
m004-small_text-13       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1429 ms)
m004-small_text-14       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1491 ms)
m004-small_text-15       base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1467 ms)
m004-dark_mode-13        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1348 ms)
m004-dark_mode-14        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1364 ms)
m004-dark_mode-15        base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1310 ms)
m004-insufficient_evidence-13 base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1302 ms)
m004-insufficient_evidence-14 base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1425 ms)
m004-insufficient_evidence-15 base=PASS ui=1.00  ->  ocr=PASS ui=1.00  (facts=2, 1334 ms)

summary: {"baseline": {"abstain_correct": 24, "forbidden_claim_total": 0, "passes": 23, "required_fact_recall_mean": 1.0, "ui_string_match_mean": 0.9583, "unsupported_claim_rate_mean": 0.0}, "cases": 24, "ocr": {"abstain_correct": 24, "forbidden_claim_total": 0, "passes": 24, "required_fact_recall_mean": 1.0, "ui_string_match_mean": 1.0, "unsupported_claim_rate_mean": 0.0}}
gate: {"baseline_passes": 23, "dialog14_baseline_pass": false, "dialog14_ocr_pass": true, "forbidden_claim_total": 0, "ocr_passes": 24, "small_text_regressions": [], "unsupported_rate_sum": {"baseline": 0.0, "ocr": 0.0}}
```

## Gate reading

- Baseline reproduced v4 exactly (23/24, ui 0.9583, recall 1.0, unsupported 0,
  forbidden 0, abstain 24/24) — deterministic decoding holds.
- OCR-augmented prompts scored **24/24**: `m004-dialog-14` flips to PASS and
  nothing regresses (`small_text_regressions: []`).
- Unsupported 0.0 and forbidden 0 in both conditions; abstention correct
  24/24 in both.
- Augmented model calls 1248–1491 ms — inside the M005 ceilings (first 5 s /
  complete 20 s).
- Facts entered the model prompt only; traces and result files keep counts,
  never OCR text.

## Conclusion

The frozen M007 gate ("augmentation improves the predeclared difficult subset
without increasing unsupported claims, privacy scope, or latency beyond
ceilings") is satisfied on the pinned configuration. M007 closes; next
milestone is M008 — multi-turn visual conversation.
