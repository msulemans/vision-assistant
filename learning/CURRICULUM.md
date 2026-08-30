# Reciprocal learning curriculum

The goal is not merely to run a vision model. You should be able to explain the
pipeline, predict a failure, measure it, and teach someone else how the evidence
was produced.

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

## Current lesson — Milestone 001

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

## Milestone 001 explain-back

In simple words: the first build is a safe pipe. It accepts only a screen the
user chose, keeps the image temporary, asks a local model a bounded question,
and shows which parts of the answer came from the screen versus an educated
guess. We will measure this before allowing the system to touch the mouse.
