from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = REPO_ROOT / "models"

# Local bake-off candidates for the llama.cpp runtime. Sizes come from the HF
# repo listings; revisions/bytes are pinned and SHA-256 is filled in after a
# verified download.
CANDIDATES = {
    "qwen3.5-4b": {
        "candidate": "qwen3.5-4b",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "licence": "Apache-2.0",
        "family": "qwen",
        "params_b": 4.0,
        "files": [
            {"name": "Qwen3.5-4B-Q4_K_M.gguf", "role": "model", "bytes": 2_740_937_888, "sha256": "to-pin", "revision": "main"},
            {"name": "mmproj-F16.gguf", "role": "mmproj", "bytes": 672_423_616, "sha256": "to-pin", "revision": "main"},
        ],
    },
    "gemma-3-4b": {
        "candidate": "gemma-3-4b",
        "repo": "unsloth/gemma-3-4b-it-GGUF",
        "licence": "Gemma Terms of Use",
        "licence_url": "https://ai.google.dev/gemma/terms",
        "family": "gemma",
        "params_b": 4.0,
        "files": [
            {"name": "gemma-3-4b-it-Q4_K_M.gguf", "role": "model", "bytes": 2_489_894_016, "sha256": "to-pin", "revision": "main"},
            {"name": "mmproj-F16.gguf", "role": "mmproj", "bytes": 851_251_328, "sha256": "to-pin", "revision": "main"},
        ],
    },
    "qwen3-vl-8b": {
        "candidate": "qwen3-vl-8b",
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "licence": "Apache-2.0",
        "family": "qwen",
        "params_b": 8.0,
        "files": [
            {"name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf", "role": "model", "bytes": 5_027_784_800, "sha256": "to-pin", "revision": "main"},
            {"name": "mmproj-Qwen3VL-8B-Instruct-F16.gguf", "role": "mmproj", "bytes": 1_159_029_824, "sha256": "to-pin", "revision": "main"},
        ],
    },
}
DEFAULT_CANDIDATE = "qwen3.5-4b"

# Backwards-compatible aliases for the first (Qwen) candidate.
CANDIDATE = CANDIDATES[DEFAULT_CANDIDATE]
MODELS_DIR = MODELS_ROOT / DEFAULT_CANDIDATE


def _resolve_url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}?download=true"


def source_url(repo: str) -> str:
    """Displayable source URL for the licences manifest (no download params)."""
    return f"https://huggingface.co/{repo}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(candidate: dict, target_dir: Path) -> Path:
    """Download one candidate's GGUF + projector with resume, then record SHA-256."""
    target_dir.mkdir(parents=True, exist_ok=True)
    pinned_files: list[dict] = []
    for entry in candidate["files"]:
        dest = target_dir / entry["name"]
        if dest.exists() and dest.stat().st_size == entry["bytes"]:
            print(f"present: {dest.name} ({entry['bytes']} bytes)")
        else:
            print(f"downloading: {dest.name} ...")
            subprocess.run(
                ["curl", "-L", "--fail", "--retry", "3", "-C", "-", "-o", str(dest), _resolve_url(candidate["repo"], entry["name"])],
                check=True,
            )
        actual = dest.stat().st_size
        if actual != entry["bytes"]:
            raise RuntimeError(f"{dest.name}: size {actual} != expected {entry['bytes']}")
        sha = _sha256_file(dest)
        print(f"  sha256={sha}")
        pinned_files.append({**entry, "sha256": sha})
    pin = {**candidate, "files": pinned_files}
    pin_path = target_dir / "pin.json"
    pin_path.write_text(json.dumps(pin, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return pin_path


def check(target_dir: Path) -> int:
    """Verify local files are present, the right size, and match the pin hash."""
    pin_path = target_dir / "pin.json"
    if not pin_path.exists():
        print(f"no pin at {pin_path}; run --download first")
        return 1
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    ok = True
    for entry in pin["files"]:
        path = target_dir / entry["name"]
        present = path.exists() and path.stat().st_size == entry["bytes"]
        sha_ok = present and _sha256_file(path) == entry["sha256"]
        print(f"{entry['name']}: present={present} sha_ok={sha_ok}")
        ok = ok and present and sha_ok
    print("OK" if ok else "MISMATCH")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire and pin local VLM candidates for the M005 bake-off")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("plan", help="print every candidate pin definition")
    for name, help_text in (("download", "download + pin one candidate"), ("check", "verify downloaded files")):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--candidate", choices=sorted(CANDIDATES), default=DEFAULT_CANDIDATE)
        child.add_argument("--dir", type=Path, default=None, help="target directory (default models/<candidate>)")
    args = parser.parse_args(argv)

    if args.cmd == "plan":
        print(json.dumps(CANDIDATES, ensure_ascii=False, sort_keys=True))
        return 0
    if args.cmd in ("download", "check"):
        candidate = CANDIDATES[args.candidate]
        target_dir = args.dir or (MODELS_ROOT / args.candidate)
        if args.cmd == "download":
            pin_path = download(candidate, target_dir)
            print(f"pin={pin_path}")
            return 0
        return check(target_dir)
    parser.error("choose plan|download|check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
