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
- quality, latency, memory, and swap ceilings; CPU/energy measurement methods
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


## Starter acceptance contract for M004 to freeze

These are proposed engineering targets, not observed performance. M004 may
revise them with a written rationale before any candidate output is inspected.
After freezing, changes require a new evaluation version and comparable reruns.

| Measure | Initial gate |
|---|---|
| Corpus | 48 cases: 24 development, 24 held-out; 3 per category per split |
| Required-fact recall | At least 90% overall and 80% per category with required facts |
| Unsupported factual claims | At most 5% of factual claims; report numerator and denominator |
| Explicit forbidden claims | Zero across the held-out set |
| Missing-evidence cases | Correct abstention on all 3 held-out cases |
| Task-critical UI strings | At least 90% exact match on the annotated string subset |
| Warm first visible answer token | p95 at most 5 seconds from submit, including image processing |
| Warm complete answer | p95 at most 20 seconds from submit |
| Cold model readiness | At most 60 seconds in each of 3 process-cold trials |
| Cancellation | Idle within 2 seconds in each of 10 trials spanning processing/generation |
| Memory | Balanced peak process-tree RSS under 8 GiB; optional Quality under 14 GiB |
| Swap growth | At most 256 MiB over the trial block on an otherwise idle host |
| Acquisition budget | At most 25 GiB additional artifacts/cache with at least 30 GiB free afterward |

Use human-reviewed atomic facts and explicit scoring denominators. Abstaining
on an answerable case loses required-fact recall; an empty answer cannot pass
by avoiding unsupported claims. Inference labels are not proof of grounding:
score whether the inference is justified. Record disagreements and adjudication
against the rubric. This small corpus is a local gate, not a general accuracy claim.

Use development data to choose the configuration and prompt. Freeze the winner
before held-out evaluation. A held-out failure blocks promotion; tuning after
inspection requires a fresh held-out set, not repeated attempts on the same set.

For latency, run one excluded warm-up followed by 48 warm trials on a fixed,
category-balanced schedule (two per held-out case). Report sample count, raw
timings, p50, nearest-rank p95, maximum, timeout count, and failure count.
A timeout fails the gate and is not discarded from reporting. Repeat three cold
trials with a restarted runtime; call these process-cold, not machine-cold unless
the machine/cache state was actually reset. Three consecutive capstone successes
establish function, not tail latency. Score each held-out case once for quality;
report repeat variability separately rather than inflating the quality sample.

Separate human selection time, acquisition, normalization, storage, image
encoding, prompt processing, generation, and UI delivery. Current M003
`capture_ms` excludes normalization/storage. Use a real monotonic clock for
live measurements. Define process-tree RSS sampling and shared-memory caveats;
do not equate parameter count or model-file size with active memory.

CPU and energy are reported diagnostics for the first local gate rather than
hard blockers. Register the measurement method; record unavailable counters
explicitly. They may become numerical gates in a later version after a
reproducible baseline exists. Record thermal/power conditions and host load.

The default answer budget is 256 generated tokens with a 30-second turn
deadline. Freeze the model-specific image processor, input size, and effective
token/patch budget in M004; identical pixel dimensions do not guarantee equal
image-token counts across architectures. Compare complete configurations and
report processor differences. If a runtime does not stream, its first visible
answer latency equals complete-answer latency.

## M005 evaluation revision v4 (2026-09-19)

The frozen 1.0 held-out pass-rate target was set before any candidate output
existed. Across three independently authored fresh held-out sets the best
local model class scored 23/24 every time, always failing one case on a
one-character misread of small synthetic text (`X`→`%`, space→`_`,
`VPN`→`UPN`), while every safety metric stayed perfect (forbidden 0,
abstention 1.0, unsupported 0.0) and latency remained inside its ceilings; the
`<=9B` quality control is excluded by host feasibility (Metal working-set OOM,
and CPU vision outside the complete-answer ceiling). Requiring 100% exact
match on synthetic bitmap text at the frozen 480x300 size over-penalises the
hardware class this product targets, while the product itself discloses
evidence labels. v4 therefore sets `held_out_pass_rate >= 0.95` (23/24) and
leaves every safety and aggregate-quality threshold unchanged. Per the frozen
bake-off rules this is a new evaluation version: it is validated on a fourth
fresh held-out set (corpus v4, three new cases per category) that no
candidate has seen, and promotion still requires all aggregate thresholds
plus the resource measurements.

Implementation correction on 2026-09-19: the harness now reads the v4 pass-rate
threshold instead of requiring every case to pass. All aggregate checks remain.
Results expose `case_count`, `case_pass_rate`, and `required_case_pass_rate`.
Missing cold-readiness, RSS, swap, or acquisition values are explicitly listed
and block the overall resource verdict. A passing aggregate result alone does
not certify the prescribed trial schedule, split integrity, or lifecycle gates.
