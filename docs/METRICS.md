# Metrics and evaluation contract

## Primary product metrics

- `capture_requested -> frame_ready`
- `frame_ready -> model_started`
- `model_started -> first_token`
- `model_started -> answer_complete`
- screenshot selection to first useful answer, p50 and p95
- warm and cold model readiness
- peak active memory, process-tree RSS, CPU, energy, and swap growth
- cancellation-to-idle latency

Record stage timings separately. A fast text decoder cannot hide a slow image
encoder, load, prompt evaluation, or UI queue.

## Answer quality

Every frozen item contains an image, question, allowed evidence, expected
facts, forbidden claims, and an abstention rule. Score:

- required-fact recall
- unsupported-claim rate
- root-cause accuracy when the cause is visible
- calibrated abstention when evidence is missing
- UI text/OCR accuracy for task-relevant strings
- instruction/next-step usefulness
- consistency across repeated deterministic decoding

Answers label statements as `visible`, `inferred`, or `unknown`. A plausible
diagnosis unsupported by the screenshot is a failure, not a bonus.

## UI grounding metrics

Before any action support, measure:

- target element identification accuracy
- correct element role/name/state
- bounding-box or element-index hit rate
- false actionable-target rate
- behaviour under scaling, Retina coordinates, overlapping windows, dark mode,
  small text, and changed layouts

## Later action metrics

- proposal correctness before policy
- policy allow/deny/confirm accuracy
- approval bypass count (must be zero)
- target resolution accuracy
- successful task completion
- unintended action count (must be zero at promotion)
- stop/interrupt latency
- stale-screenshot action count (must be zero)
- post-action verification and recovery correctness

## Frozen bake-off rules

Before acquiring a model or runtime, register:

- fixture manifest and hashes
- prompt and answer schema
- decoding parameters and output budget
- image resolution/token policy
- candidate revisions, quantization, licence, and artifact sizes
- cold/warm trial counts
- quality, latency, memory, CPU, energy, and swap ceilings
- promotion order and tie-break rule

The smallest passing candidate wins. Public benchmarks nominate candidates but
do not promote them.

## Evidence tiers

- **Deterministic:** fake adapters and synthetic fixtures; exact and repeatable.
- **Real local:** real capture/model on this Mac; hardware-specific evidence.
- **Hosted control:** optional remote comparison, separately scored and never
  required for the product.
- **Release:** reproduced from a clean install with permissions, packaging,
  privacy, and licence checks.
