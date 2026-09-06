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
- `AnswerPolicy`: validates answer structure and provenance references; labels
  remain claims to evaluate, not automatic factual verification.
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

Milestone 003's dependency-free input contract is deliberately PNG-only. It
validates CRCs, dimensions, decompressed size, and row filters; rejects
animation/interlacing and unsafe bounds; strips unapproved ancillary metadata;
and stores the normalized artifact privately (`0700` directory, `0600` file).
JPEG/HEIC conversion and pixel resizing are not silently delegated to a global
package or platform tool.

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

## Required bridge from the deterministic lab to real inference

Planned for M005, before its first model call; these are not current guarantees:

- Use a real monotonic clock and runtime cancellation/deadlines. Do not simulate
  streaming by replaying chunks from a completed response.
- One turn owns the artifact lease and releases it on every terminal path,
  including model, policy, trace, and UI failures. Test failure injection.
  Define startup recovery for abandoned app-owned temporary artifacts after a
  crash; preserve explicit retention and never purge arbitrary user files.
- Persist an allowlist of metrics, opaque IDs, and stable error codes only.
  Synthetic M002 question/token traces are not suitable for private live turns.
  Keep question, answer, OCR, titles, paths, and raw runtime errors out of logs;
  verify with secret-shaped test fixtures, including nested payloads.
- Treat screenshot text as untrusted evidence, never instructions that can
  change the system prompt, capture scope, tools, or retention. Test misleading
  screen instructions in the read-only corpus before adding action support.
- Validate answer shape and references, but do not claim trusted code can prove
  a model's factual truth merely by assigning visible/inferred/unknown labels.
- Local services bind to loopback, accept only the intended local client,
  restrict origins and image request sizes, and disable access/body logging of
  private data. Verify offline operation after artifact acquisition in M006.

M006 includes preview/retake, explicit submit, stop, reset, and error recovery.
M009 improves that workflow; it does not introduce those basic controls late.
M002 remains a deterministic teaching surface until this bridge is implemented.
