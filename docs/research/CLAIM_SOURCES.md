# Claim source ledger

Reviewed 2026-08-31. Sources nominate hypotheses only; local promotion requires
frozen project evidence.

| ID | Claim used in the plan | Primary source |
|---|---|---|
| R-001 | Qwen3.5-4B accepts image and text input and is Apache-2.0 | https://huggingface.co/Qwen/Qwen3.5-4B |
| R-002 | Qwen3-VL-4B-Instruct is an official 4B vision-language candidate | https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct |
| R-003 | Gemma 3 4B accepts images; its card states 896x896 normalization, 256 image tokens, and Gemma terms | https://huggingface.co/google/gemma-3-4b-it |
| R-004 | llama.cpp multimodal inference uses `libmtmd` and a model-specific projector; the API is experimental | https://github.com/ggml-org/llama.cpp/blob/master/tools/mtmd/README.md |
| R-005 | llama.cpp CLI/server expose image input and multimodal projector controls | https://github.com/ggml-org/llama.cpp/blob/master/tools/cli/README.md |
| R-006 | mlx-vlm supports local image-text generation and multiple VLM families | https://github.com/Blaizzy/mlx-vlm/blob/main/docs/usage.md |
| R-007 | ScreenCaptureKit supports scoped display/app/window capture and prompts for Screen Recording permission | https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos |
| R-008 | ScreenCaptureKit provides fine-grained filters and a system content-sharing picker | https://developer.apple.com/documentation/screencapturekit |
| R-009 | Core Graphics exposes low-level event posting, motivating a separate action boundary | https://developer.apple.com/documentation/coregraphics/cgevent |
| R-010 | A current computer-use reference separates read-only/action tools, requires macOS permissions, and prefers element targets | https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/computer-use.md |
