# Research baseline

Last reviewed: 2026-08-31.

This report nominates candidates and architecture boundaries. It does not claim
that a model or runtime works on this Mac until the frozen local bake-off is
recorded in `VISION_STATE.md`.

## Model candidates

Qwen3.5-4B is an Apache-2.0 image-text-to-text model and is the initial 4B
hypothesis. It is attractive because one small model can cover screen
understanding plus bounded reasoning, but its actual screenshot accuracy,
latency, memory, and quantized-runtime behaviour remain unmeasured here.

Gemma 3 4B is a second 4B-class image-text candidate. Its model card describes
896x896 image normalization and 256 tokens per image. Access/use is governed by
Gemma terms rather than Apache-2.0, so licence/redistribution fit is part of the
comparison, not an afterthought.

Qwen3-VL-4B-Instruct remains a specialist VLM alternative if the newer unified
candidate has runtime or screen-grounding problems. A locally present
`qwen3.5:9b-q4_K_M` Ollama manifest may become the <=9B quality control only
after vision capability and exact artifact identity are verified.

## Runtime candidates

`llama.cpp` provides multimodal support through `libmtmd`, with image encoding
handled by a model-specific multimodal projector. Its documentation explicitly
labels the multimodal sub-project/API as experimental and subject to breaking
changes, so the project must pin a revision and wrap it behind `VisionModelPort`.
The host already has Darwin arm64 build 10621 at commit `c1d0e7a00`; that is an
environment observation, not evidence that a chosen model works.

`mlx-vlm` is the Apple Silicon treatment. It supports local image-text
generation and is useful for measuring an Apple-optimized path, while the
product contracts remain portable. Ollama is a convenient existing local API
adapter but must not become the only supported architecture.

## Capture and computer use

Apple ScreenCaptureKit supports user-selectable displays, apps, and windows,
including a system content-sharing picker and single/window streaming paths.
The first permission request is explicit and may require restarting the host
app. The lab begins with file ingest and single-shot capture so capture failure,
normalization, and lifecycle can be tested before continuous streaming.

Core Graphics can post mouse/keyboard events, which is exactly why it is kept
out of the read-only phases. Later macOS computer use also needs Accessibility
permission. The action design prefers Accessibility element identities over raw
coordinates, requires a visible preview/approval boundary, and verifies the
screen again after every action.

The Qwen Code computer-use design is a useful contemporary reference: it
separates read-only inspection from action tools, warns that desktop control can
read the screen and drive input, uses macOS Screen Recording and Accessibility
permissions, and prefers element-addressed actions. This project will reproduce
those safety properties from its own typed contracts and frozen tests; it will
not download or depend on that driver during the current milestone.

## Why screenshot QA comes first

A wrong explanation is visible and reversible. A wrong click or typed secret
can have an external consequence. Building observation first also creates the
capture, state, evidence, latency, grounding, and evaluation machinery required
to judge whether an action proposal is safe enough to show a user.

## Open questions for the frozen bake-off

- Does 4B meet task-relevant small-text and terminal-error accuracy?
- Which image resolution/token budget preserves UI text without making latency
  unacceptable?
- Does OCR/accessibility augmentation outperform simply using a larger model?
- Is `llama.cpp` or `mlx-vlm` the better promoted runtime on this Mac after
  portability is included?
- Can answers reliably separate visible facts from inferred causes?
- What capture/answer latency feels interactive for a user-selected screenshot?
