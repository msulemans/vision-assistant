# Reciprocal learning curriculum

The goal is not merely to run a vision model. You should be able to explain the
pipeline, predict a failure, measure it, and teach someone else how the evidence
was produced.

Use this written path together with the dependency-free interactive field
manual at `learning/index.html` (or run
`python3.11 scripts/serve_learning_lab.py`). The site is updated from the same
canonical evidence and must never present a planned or simulated capability as
real.

## The loop

1. **Question** — state one falsifiable milestone question.
2. **Mental model** — draw pixels, text, control, and trust boundaries.
3. **Prediction** — write the expected result and likely failure.
4. **Small build** — change only the current milestone.
5. **Evidence** — deterministic check first, labelled real-local check second.
6. **Explain back** — describe what happened in simple words.
7. **Transfer** — change one condition and predict the new outcome.
8. **Record** — update `VISION_STATE.md`, including failures.

## Learning path

| Milestones | Concepts to teach | Practical proof |
|---|---|---|
| 001–003 | pixels/points, capture scope, image lifecycle, events, cancellation | trace a fake and user-approved capture |
| 004–006 | frozen evaluation, OCR, VLM image encoding, decoding, quantization, hallucination | compare models and explain one grounded answer |
| 007–009 | crops, OCR/accessibility provenance, visual memory, UI observability | diagnose a difficult screen without hidden retention |
| 010–012 | typed actions, policy, approvals, element grounding, stale observations | defeat unsafe proposals in a fake loop |
| 013–014 | supervised input, verification, recovery, stop controls | complete a disposable task with zero unintended actions |
| 015–017 | profiles, packaging, supply chain, privacy audit, teaching | reproduce and explain a clean offline install |

## Current lesson — Milestone 003

### A file path is not an image contract

Before a model sees an image, trusted code must prove that the container is the
format it claims to be, dimensions are bounded, checksums are valid, decoded
size cannot explode, and hidden metadata is removed. Milestone 003 accepts only
PNG so those guarantees remain understandable and dependency-free.

### Ephemeral means a tested lifecycle

"We do not save screenshots" is not a policy until a test proves the private
artifact exists only while needed and is deleted afterward. Retention is a
separate explicit option, never an accidental side effect.

The CLI must release its artifact even when writing the capture summary fails
(for example, a closed output pipe). A `finally` block preserves that cleanup
path, while `--retain` remains explicit. A valid PNG chunk checksum also does
not prove the compressed pixels are valid: decompression errors must become
the same recoverable `invalid_image` result as other image validation failures.

### Cancel, deny, and timeout are different

Escape means the user cancelled. Missing Screen Recording permission means the
platform denied capture. Waiting past the selection budget means timeout. The
first live attempt exposed that timeout and cancel were incorrectly merged;
the failure was preserved and the outcomes are now distinct.

### Pixels are not understanding

A screenshot is an array of pixels. A vision encoder turns regions into model
representations; a language model then predicts text. Neither step guarantees
that small terminal text was read correctly or that a diagnosis is supported.

### Visible evidence is not inference

"PostgreSQL connection refused on localhost:5432" may be visible. "The database
service is stopped" is an inference: common and useful, but not directly shown.
The assistant should label that difference and suggest a verification step.

### Local is a data boundary

Local means pixels, extracted text, prompts, model weights, answers, and traces
remain under local control. Running a local model while silently retaining every
screenshot would still violate the privacy goal.

### A model proposal is not permission

Seeing a button, deciding it is relevant, being allowed to click it, and
successfully clicking it are four different responsibilities. Trusted code and
the user own the last two.

## Teach-back prompts

- Why do we build a fake visual turn before downloading a model?
- Which part sees raw pixels, and how long are they retained?
- What is the difference between OCR accuracy and root-cause accuracy?
- Why can a fast token rate still produce a slow answer?
- Why is a coordinate click riskier than an Accessibility element click?
- What evidence would justify moving from a 4B model to a 9B model?
- What should happen when the screenshot does not show the cause?

## Milestone 003 explain-back

In simple words: an image is copied into a private temporary room, checked for
size and damage, cleaned of hidden notes, measured, and then removed. The same
room is used whether the image came from a file or the Mac selector. We still
need one deliberate live selection before calling this lesson complete.

## How the revised plan reaches a useful product

M006 is the first usable single-image assistant; M009 completes the read-only
workflow. Desktop actions are optional. Packaging does not depend on teaching
the computer to click. The learning site and evaluation evidence grow at every
milestone; M016 consolidates them rather than postponing them.

M004 separates development cases (used to improve a prompt) from held-out cases
(used to judge the frozen result). Repeatedly tuning against the held-out set
turns it into development data. Hand-authored correct, wrong, and abstaining
answers first prove the scorer works. The numerical targets in `METRICS.md`
are starting proposals to freeze before model output, not measured results.

M005 tests a small number of complete model/runtime configurations in sequence.
A difficult tiny-text case may expose an image-resolution problem rather than
a need for a larger model. Diagnose on development cases, then version and rerun
any changed evaluation. A fake clock cannot measure real latency, and a model's
“visible” label cannot prove its claim true. Real inference needs real timing,
private metrics, cancellation, and cleanup on every terminal path.

Teach back: Why are three successful demos insufficient to estimate p95?
What evidence would distinguish a decoder failure from insufficient image detail?
Why should the read-only product be valuable even if actions are never added?

## M005 lesson — a failed verdict can be a harness defect

The v4 contract allowed 23/24, but the harness still required 24/24. Correcting
that mismatch changes the aggregate quality verdict without hiding the one
failed UI-string case. Quality passing also does not mean evidence is complete:
missing cold-readiness or acquisition measurements must remain pending, not
silently count as passing. The original user-reported results are preserved.

Teach back: How would you test 23/24 versus 22/24 while ensuring forbidden
claims still fail? Why is a 24-case run insufficient proof of 48 warm trials?

## M005 outcome — selected configuration

Qwen3.5-4B (Q4_K_M, llama.cpp, thinking off, context 4096) is the selected
Phase-1 configuration: 23/24 on the frozen v4 held-out (0.95 pass-rate gate),
all safety metrics perfect, RSS 3.792 GiB, swap 0, acquisition 6.29 GiB.
Cold-readiness and cancellation certification trials remain open for
packaging. The next milestone was M006 — one-shot local Vision Assistant
(complete; see below).

## M006 outcome — the one-shot assistant

`assistant_cli` previews (normalize, hash, report), then asks one question and
prints a labelled answer with real timings; the JSONL trace records
preview/model_started/answer/done, and the private artifact is deleted on exit
(retain is explicit). Live demo: first token 651–659 ms, complete
1130–1145 ms, quotes verbatim, unknowns honest, artifact released. The stop
check ran twice (Ctrl+C during model load): clean cancel — one JSON line,
`cancelled` trace, artifact purged, exit 130, no orphaned server. That check
found and fixed a real bug: a startup interrupt used to crash with a traceback
and leak the artifact; regression tests now protect every stage. Next
milestone was M007 — evidence augmentation (complete; see below).

## M007 outcome — evidence augmentation closes the last failure

Augmentation was frozen before output was inspected: the difficult subset was
`m004-dialog-14` (the only held-out failure) plus `m004-small_text-13..15` as
an exact-text guard. Local OCR (macOS Vision, compiled from
`tools/vision_ocr.swift`; no package, no permission) misread the block-font
title at 1× ("UNSEVED BEFOBT"); zooming ×2 first (pure-stdlib `pixels.py`)
read `UNSAVED REPORT` at confidence 1.0 — ×4 regressed. Measured on the
pinned model: baseline reproduced v4 exactly (23/24, ui 0.9583) and
OCR-augmented prompts scored 24/24 — flipping the last failure — with
unsupported 0, forbidden 0, no guard regressions, and 1.25–1.49 s per
augmented call. Facts enter the model prompt only; traces record counts and
kinds, never text. Next milestone was M008 — multi-turn conversation
(complete; see below).

## M008 outcome — bounded multi-turn conversation

One session binds one capture (identity = trace id + content sha256); a new
capture never inherits history. Hard bounds: 12 turns, 4000-character
transcript budget (oldest dropped first, marked when omitted), 15-minute stale
warning; reset releases the artifact and closes the session; asking after
reset and exceeding the limit are typed errors. Measured on the pinned model:
6/6 frozen tasks passed — three reference questions (the follow-up must carry
a fact from the earlier turn) and three corrections (a false premise must be
contradicted with the true value) — every artifact released and prompts
bounded (max 333 characters). Follow-ups answered in 1.1–1.6 s. Next
milestone was M009 — usable capture and answer UI (complete; see below).

## M009 outcome — the usable local UI

A loopback-only stdlib server owns the trusted side and serves a
dependency-free page: pick a PNG, drag to redact a region before sending,
ask, and keep bounded follow-ups on one capture; stop shuts the model down
and releases everything; reset releases between sessions; failures appear as
typed banners with recovery hints. All five frozen read-only capstones passed
live on the pinned model (one-shot on real screenshots; reference and
correction follow-ups ~1.3 s; stop with no orphaned process; corrupt-file
recovery; empty artifact root after the privacy cycle). Two real bugs found
by the run were fixed: large captures overflowed the model context (a bounded
model view now downscales above 3M pixels for the model call only) and stop
during model load now aborts promptly. Next milestone: M010 — typed action
intents and policy (no execution).
