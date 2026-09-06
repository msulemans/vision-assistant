# Local Vision Assistant — State

Last updated: 2026-08-31 (Australia/Sydney)

Status: Milestone 004 complete — Milestone 005 is the next gate.

This is the canonical chronological record. A command, demo, model response, or
benchmark is not evidence until its observed result is recorded here. Future
assistants must read this file before suggesting or executing the next step.

## Objective

Build and understand a local-first vision assistant that can explain a
user-selected Mac screenshot, then evolve into a supervised computer-use agent
without weakening privacy, user control, or evidence quality.

## Current user context

The sibling Voice Assistant is paused at its live microphone gate because the
current microphone has a hardware/availability issue. That is an external
device blocker, not a failed learning path. This project must not depend on the
microphone and does not replace or rewrite the Voice Assistant state.

## Fixed constraints

- Local inference is the product path; hosted inference is an optional,
  separately scored control.
- Initial host: Apple M2 Max, 32 GB unified memory, arm64 macOS.
- Fully local candidates should remain under 10B parameters for this lab.
- Capture is explicit and least-scope: region/window before full display.
- Raw captures are ephemeral and Git-ignored; retention is opt-in.
- Screen text, paths, tokens, email, notifications, and personal data are
  sensitive even if they appear incidentally.
- The first product is read-only question answering.
- A model never directly owns mouse, keyboard, shell, permissions, approvals,
  or retry loops.
- Later actions are typed, bounded, policy-classified, previewed, confirmed when
  consequential, interruptible, and followed by observation.
- Deterministic fixtures precede live capture and real model integration.
- Candidates use the same frozen images, questions, prompts, image budgets,
  decoding settings, and resource ceilings.
- Failed runs remain evidence. Only the current milestone may be implemented.

## Capability profiles

| Profile | Intended device | Vision path | Warm active-memory target |
|---|---|---|---|
| Inspect | modern laptop, low resource | 2–4B quantized VLM, one image | under 6 GiB |
| Balanced | this M2 Max | best passing 4B-class VLM | under 8 GiB |
| Quality | 32 GB laptop/workstation | up to 9B quantized VLM | under 14 GiB |

These are engineering targets, not measured claims. Milestone 005 will freeze
and then replace them with observed values.

## Milestone 001 — contract, research, and environment

Status: complete.

### Question

Can the project begin with a teachable, privacy-preserving architecture,
measurable product goals, a verified host inventory, and a complete roadmap
without installing anything, downloading a model, or requesting permissions?

### Host evidence

Read-only checks observed on 2026-08-31:

| Capability | Observed result | Decision |
|---|---|---|
| Architecture | `arm64` | Apple acceleration can be evaluated behind a portable port |
| Hardware | MacBook Pro `Mac14,5`, Apple M2 Max, 12 CPU cores, 30 GPU cores | Initial reference host |
| Memory | 32 GB unified memory | Suitable for frozen 4B and bounded 9B comparisons |
| macOS | 27.0, build `26A5421a` | Record for reproducibility |
| Free project-volume disk | about 110 GiB | Adequate, but downloads require a size forecast |
| Python | 3.11.9 | Suitable isolated-environment candidate |
| FFmpeg | present | Optional image conversion/video extraction tool; licence recorded before packaging |
| `screencapture` | `/usr/sbin/screencapture` | Useful explicit-capture baseline after user permission |
| Ollama | client present; local API blocked in restricted runner | Convenience control only, not yet benchmarked |
| Existing Ollama manifests | text/coding models plus `qwen3.5:9b-q4_K_M` | Presence is not proof that vision input or quality works |
| `llama-mtmd-cli` / `llama-server` | installed, build 10621, commit `c1d0e7a00`, Darwin arm64 | Portable runtime candidate; pin this exact build for any first bake-off |
| Project environment | no project `.venv`; Pillow/FastAPI/Pydantic exist only in the user Python | Do not treat global packages as a locked project environment |
| Git repository | initialized on `main` | Record coherent milestone commits before advancing |

Screen Recording and Accessibility permission status were deliberately not
requested or changed. A live screenshot was deliberately not taken.

### Research decisions

- Separate capture, image normalization, model inference, answer policy, UI,
  and later action execution behind versioned ports.
- Use a deterministic fake vertical slice before real pixels or models.
- Freeze a small screenshot/question corpus before acquiring candidates.
- Start the model bake-off with an Apache-2.0 4B unified vision-language
  candidate such as Qwen3.5-4B. Compare a second 4B-class architecture; only
  add a 9B quality control if the small candidates miss the gate.
- Compare a portable `llama.cpp` multimodal path with an Apple-specific
  `mlx-vlm` treatment. Ollama may be measured as a convenience adapter, not as
  the architecture.
- Treat `llama.cpp` multimodal APIs as experimental and pin the exact revision.
- The existing Ollama `qwen3.5:9b-q4_K_M` manifest is about 6.59 GB and contains
  no separately identified multimodal-projector layer in the inspected
  manifest. Do not assume it accepts screenshots; verify capability later.
- Use ScreenCaptureKit for the eventual native streaming/window picker path;
  begin with explicit single-shot file/region capture behind the same port.
- Prefer the macOS Accessibility tree for element identity and semantics. A
  vision model may assist grounding but cannot grant itself execution rights.
- Keep observation and action as separate phases. Computer use requires
  approval, action budgets, a visible cursor/target preview, interrupt/stop,
  post-action verification, and disposable-app tests first.

### Deliverables

- `.gitignore`
- `README.md`
- `VISION_STATE.md`
- `docs/MILESTONES.md`
- `docs/ARCHITECTURE.md`
- `docs/METRICS.md`
- `docs/research/report-source.md`
- `docs/research/CLAIM_SOURCES.md`
- `learning/CURRICULUM.md`
- `scripts/check_environment.sh`

### Gate evidence

- Required foundation files exist.
- The roadmap names exactly one next milestone: Milestone 002.
- No model, package, capture, or permission was acquired.
- Generated and user screenshots are excluded by `.gitignore`.
- The environment script is read-only and does not start a server or request
  macOS privacy permissions.

### Gate result

Passed. The repository is initialized on `main`. No package, model, screenshot,
or privacy permission was acquired. Milestone 002 is the sole next gate.

## Milestone 002 — deterministic event spine and browser shell

Status: complete.

### Question

Can a versioned event envelope, a deterministic fake clock, fake capture and
model adapters, a JSONL trace, and a dependency-free browser UI produce exact,
round-tripping success/failure/cancel/timeout traces before any real capture,
model, or permission is touched?

### Build

- Versioned `Event` envelope and the read-only turn state machine
  (`IDLE -> SELECTING -> CAPTURING -> ANALYSING -> ANSWERING -> DONE`) with
  terminal `CANCELLED` / `TIMED_OUT` / `FAILED` states.
- Injectable `FakeClock` (monotonic ms from a fixed epoch) so stage timings are
  exact and repeatable.
- Typed port contracts (`Clock`, `CapturePort`, `VisionModelPort`,
  `AnswerPolicy`) plus fake adapters (`FakeCapturePort`, `FakeVisionModelPort`,
  `FakeAnswerPolicy`, `FailingCapturePort`).
- Synthetic fixture generator (`vision_assistant/fixture.py`) that writes a PNG
  using only the standard library; no Pillow or package is installed.
- JSONL `TraceSink` with key-sorted compact serialisation and a redaction
  contract (sensitive keys are written as `[redacted]`).
- Dependency-free static browser UI (`ui/index.html`) rendered from observed
  traces; it is opened directly via `file://` with no server.
- A CLI that runs the four scenarios, writes traces under `runs/`, renders the
  UI, and `--verify`s determinism and round-trip.
- A stdlib `unittest` regression suite (`tests/test_spine.py`).

### Command

`PYTHONPATH=src python -m vision_assistant.cli --verify`

### Gate evidence

Observed on 2026-08-31 (Australia/Sydney):

| Scenario | Final state | Events | Deterministic | Round-trip |
|---|---|---|---|---|
| success | `done` | 11 | yes | yes |
| failure | `failed` | 3 | yes | yes |
| cancel | `cancelled` | 3 | yes | yes |
| timeout | `timed_out` | 5 | yes | yes |

- `--verify` reports `PASS`; the `unittest` suite passes. Re-running each
  scenario produces byte-identical traces and a clean round-trip parse.
- Cancellation suppresses every later model/UI event in the `cancel` trace.
- The UI shows capture scope, the synthetic fixture preview, the question, the
  terminal status, the labelled answer (`visible` / `inferred` / `unknown`),
  stage timings, and the event trace.
- No real pixels are written to any trace; the UI preview is an embedded data
  URI and the trace records only `fixture_id`, never pixel bytes.
- No real model (fake adapter), no server (static `file://` page), and no
  permission (Screen Recording / Accessibility not requested) are involved.

### Gate result

Passed. Byte-identical, round-tripping success/failure/cancel/timeout traces and
a self-contained browser UI are produced from synthetic fixtures only. No model,
package, capture pixel, server, or privacy permission was acquired. Milestone
003 is the sole next gate.

## Milestone 003 — explicit screenshot ingest and capture

Status: complete.

### Question

Can a generated fixture, an explicitly selected PNG file, and a user-selected
macOS region/window traverse one bounded normalization and ephemeral-artifact
path with correct dimensions, hashes, timing, cancellation, permission errors,
and default deletion?

### Build

- `normalize_png` validates the PNG signature, chunk lengths/CRCs, declared
  dimensions, colour/bit-depth combination, bounded decompressed size, row
  filters, and final `IEND`; it rejects oversized, animated, interlaced,
  truncated, unknown-critical, and non-PNG input, and strips unapproved
  ancillary metadata.
- `EphemeralArtifactStore` uses private `0700` directories, `0600` files,
  atomic writes, bounded trace identifiers, and symlink-escape rejection.
- `FileCapturePort` uses a no-follow file descriptor, requires a regular file,
  and never copies the selected filesystem path into its public summary.
- `MacInteractiveCapturePort` invokes fixed argv
  `/usr/sbin/screencapture -i -x -t png <private-temp-path>` with no shell, a
  minimal environment, and a 180-second selection budget.
- File and interactive capture share one `PngIngestor`. The raw macOS temp file
  is deleted by its temporary directory; the normalized artifact is deleted
  after validation unless `--retain` is explicit.
- Stable recoverable outcomes distinguish `permission_denied`,
  `cancelled_by_user`, `selection_timed_out`, `invalid_image`, and
  `capture_unavailable`; the typed `code` is carried onto the `turn.failed`
  trace event.
- The turn spine passes only a private internal artifact reference to the model
  port; traces continue to receive an opaque artifact identifier.
- The interactive field manual (`learning/`) teaches the verified milestones,
  evidence, failures, and boundaries, and `scripts/serve_learning_lab.py`
  serves it locally.

### Commands

```bash
PYTHONPATH=src python -m vision_assistant.capture_cli --verify
PYTHONPATH=src python -m vision_assistant.capture_cli --file /path/to/selected.png
PYTHONPATH=src python -m vision_assistant.capture_cli --interactive
```

### Evidence observed on 2026-09-06

- Full regression suite: 27 tests pass — 17 capture/lifecycle, 6 learning-site
  contract, and the 4 unchanged Milestone 002 spine tests.
- Generated-fixture gate: dimensions match, SHA-256 matches the private
  normalized artifact, mode is `0600`, artifact exists during the turn, and is
  deleted on release — `pass: true`.
- Two successful user-selected Mac captures, each `status: captured` then
  `status: released`:
  - 601×452, 78875 bytes, 5094.502 ms capture, ephemeral.
  - 650×464, 86541 bytes, 5918.366 ms capture, ephemeral.
- Both traversed the same `PngIngestor`/artifact path and were deleted by
  default; no image content or path was printed or retained.
- The original Milestone 002 `--verify` still passes all four byte-identical,
  round-tripping scenarios.

### Gate result

Passed. The generated fixture and file path, the privacy lifecycle, the error
paths, and two successive user-selected Mac region captures all pass and are
deleted by default. Milestone 004 is the sole next gate.

## Milestone 004 — frozen screen-understanding corpus

Status: complete.

### Question

Can a small, deterministic, synthetic screen-understanding corpus (with correct
facts, forbidden claims, uncertainty labels, a scorer, a prompt, an image
budget, resource ceilings, and a promotion rule) be frozen before any model or
runtime is downloaded?

### Build

- `corpus.py`: a stdlib PNG generator with an embedded 5x7 bitmap font so the
  synthetic fixtures carry real, readable strings.
- 48 cases (24 dev + 24 held-out) across 8 categories — terminal, dialog, form,
  settings, dashboard, small_text, dark_mode, insufficient_evidence — 3 per
  category per split.
- Each case locks: question, allowed_evidence, required_facts, forbidden_claims,
  uncertainty/abstention rule, and task-critical `ui_strings`.
- `scorer.py`: deterministic grading of a labelled answer
  (`visible`/`inferred`/`unknown`), measuring required-fact recall,
  unsupported-claim rate, forbidden claims, UI-string exact match, and correct
  abstention.
- `corpus_cli.py --freeze` writes the corpus manifest (image SHA-256/dimensions),
  the fixtures, and a frozen config (prompt, answer schema, token/deadline
  budget, thresholds, resource ceilings, promotion rule). `--verify` checks
  determinism and runs a gold/bad self-test.
- Hand-authored gold answers (all pass) and confident-wrong answers (all fail)
  validate the scorer. The corpus is synthetic with hand-authored atomic facts;
  user-reviewed/redacted real captures can be added in a later evidence
  milestone without re-freezing this deterministic set.

### Commands

```bash
PYTHONPATH=src python -m vision_assistant.corpus_cli --freeze
PYTHONPATH=src python -m vision_assistant.corpus_cli --verify
```

### Gate evidence

Observed on 2026-09-06:

- 48 cases: 24 dev + 24 held-out; 8 categories × 6.
- Manifest and fixtures are byte-stable across regeneration (deterministic).
- Gold answers: 48/48 pass. Confident-wrong answers: 48/48 fail.
- Aggregate on gold: required-fact recall 1.00, unsupported-claim rate 0.00,
  forbidden claims 0, UI-string match 1.00, held-out abstention correct 1.00.
- Full suite: 34 tests pass (7 new corpus tests).

### Gate result

Passed. The deterministic synthetic corpus and all frozen contracts
(manifest/hashes, facts, forbidden claims, uncertainty, scorer, prompt, image
budget, resource ceilings, and promotion rule) are locked before any model is
downloaded. Milestone 005 is the sole next gate.

## Next gate — Milestone 005

Local VLM and runtime bake-off: compare an Apache-2.0 4B unified VLM hypothesis
(initially Qwen3.5-4B), one second 4B-class architecture, portable `llama.cpp`
versus Apple `mlx-vlm`, and only then a ≤9B quality control if needed. Ollama
may be a convenience control. Promote the smallest configuration meeting the
frozen held-out and resource gates; pin all revisions, hashes, quantization,
prompts, and image settings, and preserve losing results.
