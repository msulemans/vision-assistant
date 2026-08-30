# Architecture

## Read-only product path

```text
user selects source
      |
      v
CapturePort (file / region / window / display)
      |
      v
PrivacyBoundary ----> ephemeral artifact + redacted metadata
      |
      v
ImageNormalizer (orientation, colour, scale, image-token budget)
      |
      +----> optional deterministic OCR/accessibility evidence
      |
      v
VisionModelPort <---- question + bounded prompt
      |
      v
AnswerPolicy (visible evidence / inference / uncertainty)
      |
      v
UI + trace metrics (raw pixels excluded by default)
```

Trusted code owns capture scope, file handling, lifecycle, prompts, budgets,
timeouts, trace redaction, and stop reasons. The model supplies an untrusted
answer candidate.

## Later supervised action path

```text
observe screenshot + accessibility tree
      |
      v
model proposes ActionIntent
      |
      v
schema validation -> target resolution -> policy classification
      |
      +---- denied / ask user / preview target
      |
      v
explicit approval when required
      |
      v
bounded executor -> post-action observation -> outcome check
      |
      +---- stop / recover / request help
```

An `ActionIntent` is a typed proposal such as `click_element`, `type_text`,
`press_key`, or `scroll`. It is never arbitrary code. Element-addressed actions
are preferred. Coordinate actions require a fresh screenshot, display/scale
identity, a visible target overlay, and stricter confirmation.

## Ports

The stable contracts should include:

- `CapturePort`: returns pixels plus source/scope/timing metadata.
- `ArtifactStore`: ephemeral-by-default lifecycle and explicit retention.
- `ImageNormalizer`: deterministic image size/format/token-budget policy.
- `VisionModelPort`: image + question -> streamed answer candidate + timings.
- `EvidencePort`: optional OCR and Accessibility facts owned by trusted code.
- `AnswerPolicy`: labels evidence, inference, uncertainty, and abstention.
- `TraceSink`: versioned, redacted events and metrics.
- Later `ActionPolicy`, `TargetResolver`, and `ActionExecutor` ports.

## State machines

Read-only turn:

```text
IDLE -> SELECTING -> CAPTURING -> ANALYSING -> ANSWERING -> DONE
                    |             |             |
                    +-------------+-------------+-> CANCELLED / TIMED_OUT / FAILED
```

Later action turn:

```text
OBSERVING -> PROPOSING -> VALIDATING -> AWAITING_APPROVAL -> EXECUTING
    ^                                                   |
    +---------------- VERIFYING <-----------------------+
                         |
                         +-> DONE / BLOCKED / CANCELLED / FAILED
```

Terminal states are final. Cancellation must prevent later model, action, or
UI-success events from appearing.

## Privacy boundary

- Capture only after an explicit user gesture.
- Default to one file, region, or window rather than a whole display.
- Show what is about to be shared with the model.
- Keep pixels in memory or an ignored temporary path.
- Do not log raw images, OCR text, question content, window titles, usernames,
  filesystem paths, notifications, or model prompts by default.
- If evidence retention is enabled for a benchmark, use purpose-made fixtures
  or user-reviewed redacted captures with a manifest and deletion path.

## Runtime strategy

The public model contract is runtime-neutral. `llama.cpp` is the portable
candidate and uses a separate multimodal projector for supported models.
`mlx-vlm` is the Apple-specific performance treatment. Ollama is an optional
development adapter. Exact engine/model revisions, hashes, quantization,
licences, prompts, and image-token settings are frozen before comparison.

## UI strategy

Milestone 002 uses a dependency-free local browser UI backed by fake events.
It should show capture scope, image preview, question, streamed status, answer,
evidence/inference labels, latency waterfall, stop control, and whether the run
is deterministic or real. Native capture can later use ScreenCaptureKit without
replacing the event or model contracts.
