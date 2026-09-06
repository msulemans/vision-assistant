from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models" / "qwen3.5-4b"

# The frozen Qwen3.5-4B llama.cpp candidate. Sizes come from the HF repo listing;
# revisions/bytes are pinned and SHA-256 is filled in after a verified download.
CANDIDATE = {
    "candidate": "qwen3.5-4b",
    "repo": "unsloth/Qwen3.5-4B-GGUF",
    "licence": "Apache-2.0",
    "params_b": 4.0,
    "files": [
        {"name": "Qwen3.5-4B-Q4_K_M.gguf", "role": "model", "bytes": 2_740_937_888, "sha256": "to-pin", "revision": "main"},
        {"name": "mmproj-F16.gguf", "role": "mmproj", "bytes": 672_423_616, "sha256": "to-pin", "revision": "main"},
    ],
}


def _resolve_url(filename: str) -> str:
    return f"https://huggingface.co/{CANDIDATE['repo']}/resolve/main/{filename}?download=true"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(target_dir: Path) -> Path:
    """Download the pinned GGUF + projector with resume, then record SHA-256."""
    target_dir.mkdir(parents=True, exist_ok=True)
    pinned_files: list[dict] = []
    for entry in CANDIDATE["files"]:
        dest = target_dir / entry["name"]
        if dest.exists() and dest.stat().st_size == entry["bytes"]:
            print(f"present: {dest.name} ({entry['bytes']} bytes)")
        else:
            print(f"downloading: {dest.name} ...")
            subprocess.run(
                ["curl", "-L", "--fail", "--retry", "3", "-C", "-", "-o", str(dest), _resolve_url(entry["name"])],
                check=True,
            )
        actual = dest.stat().st_size
        if actual != entry["bytes"]:
            raise RuntimeError(f"{dest.name}: size {actual} != expected {entry['bytes']}")
        sha = _sha256_file(dest)
        print(f"  sha256={sha}")
        pinned_files.append({**entry, "sha256": sha})
    pin = {**CANDIDATE, "files": pinned_files}
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
    parser = argparse.ArgumentParser(description="Acquire and pin the Qwen3.5-4B llama.cpp candidate")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("plan", help="print the pin definition")
    download_parser = sub.add_parser("download", help="download + pin")
    download_parser.add_argument("--dir", type=Path, default=MODELS_DIR)
    check_parser = sub.add_parser("check", help="verify downloaded files")
    check_parser.add_argument("--dir", type=Path, default=MODELS_DIR)
    args = parser.parse_args(argv)

    if args.cmd == "plan":
        print(json.dumps(CANDIDATE, ensure_ascii=False, sort_keys=True))
        return 0
    if args.cmd == "download":
        pin_path = download(args.dir)
        print(f"pin={pin_path}")
        return 0
    if args.cmd == "check":
        return check(args.dir)
    parser.error("choose plan|download|check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
