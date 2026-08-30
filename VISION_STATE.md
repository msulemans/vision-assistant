# Local Vision Assistant — State

Last updated: 2026-08-31 (Australia/Sydney)

Status: Milestone 001 complete — Milestone 002 is the sole next gate.

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

## Next gate — Milestone 002

Build a versioned event envelope, fake clock, fake capture/model adapters,
cancel/timeout behavior, JSONL trace, and static browser UI. The only images are
synthetic fixtures generated by trusted code. No model, capture permission,
Accessibility permission, or action execution is allowed.
