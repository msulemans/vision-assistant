"""M012 grounding CLI: frozen gate + read-only live Accessibility grounding.

Flags:
  --verify                     run the frozen deterministic grounding gate
  --check                      report the Accessibility trust state (no prompt)
  --request-permission         explicit opt-in: show what macOS will ask, then
                               trigger the system prompt exactly once
  --dump                       read-only AX snapshot of one application
  --ground --target TEXT       resolve a target in a real window (read-only),
                               optionally capturing the window screenshot and
                               cross-checking the region with Vision OCR

No input events are posted anywhere: the helper reads attributes, and the only
system calls here are `screencapture` (read) and the OCR helper (read).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .ax_vision import AxUnavailable, AxVisionAdapter
from .grounding import (
    TargetSpec,
    capture_consistent,
    ground_target,
    normalize,
)
from .grounding_eval import DEFAULT_OUT_DIR, run_frozen_gate
from .pixels import crop_png, decode_png, zoom_png

REPO_ROOT = Path(__file__).resolve().parents[2]
TMP_DIR = REPO_ROOT / "runs" / "m012-tmp"


def _print(line: str) -> None:
    print(line, flush=True)


def _adapter() -> AxVisionAdapter:
    return AxVisionAdapter()


def _describe_ax_error(error: AxUnavailable) -> None:
    _print(f"accessibility unavailable: {error.reason} — {error.detail or error}")
    if error.reason == "permission":
        _print("this is the honest denial path: nothing is read and nothing else changes")
        _print("to opt in: vision_assistant.grounding_cli --request-permission")


def cmd_verify() -> int:
    payload = run_frozen_gate()
    summary = payload["summary"]
    _print("M012 frozen grounding gate (deterministic; no model, no permission)")
    _print(f"  variants: {', '.join(summary['variants'])}")
    for row in payload["rows"]:
        state = "PASS" if row["passed"] else "FAIL"
        region = "region ok" if row["region_ok"] else f"region {row['region_ok']}"
        _print(
            f"  [{state}] {row['variant']:<10} {row['task_id']:<28} "
            f"{row['status']:<10} identity={row['identity_ok']} state={row['state_ok']} {region}"
        )
    _print(f"  checks: {summary['checks']}  passed: {summary['passed']}  gate_pass: {summary['gate_pass']}")
    result_path = DEFAULT_OUT_DIR / f"grounding-{payload['run_id']}.json"
    _print(f"  results: {result_path.relative_to(REPO_ROOT)}")
    _print(f"  fixtures: {(DEFAULT_OUT_DIR / 'fixtures').relative_to(REPO_ROOT)}/<variant>.png")
    return 0 if summary["gate_pass"] else 1


def cmd_check() -> int:
    status = _adapter().check()
    if status["trusted"]:
        _print("accessibility trust: granted (read-only helper can run)")
    else:
        _print("accessibility trust: not granted")
        _print("nothing is read until you opt in; --request-permission starts the explicit flow")
    return 0


def cmd_request_permission() -> int:
    _print("macOS will ask to grant Accessibility to the terminal app that runs")
    _print("this command (the helper is its child). The grant is opt-in and can be")
    _print("revoked in System Settings > Privacy & Security > Accessibility.")
    _print("This tool reads element names, roles, and frames only; it never clicks,")
    _print("types, or changes focus.")
    result = _adapter().request_permission()
    if result["trusted"]:
        _print("accessibility trust: granted")
        return 0
    _print("accessibility trust: still not granted (or the prompt is pending)")
    _print("open System Settings > Privacy & Security > Accessibility to review")
    return 1


def _window_lines(snapshot, json_mode: bool, max_depth: int) -> int:
    if json_mode:
        _print(json.dumps(AxVisionAdapter.snapshot_to_dict(snapshot), indent=2))
        return 0
    _print(f"app: {snapshot.app} (pid {snapshot.pid})")
    if not snapshot.windows:
        _print("no windows reported")
        return 1
    for index, window in enumerate(snapshot.windows):
        marker = " (focused)" if window.focused else ""
        frame = tuple(round(value, 1) for value in window.frame) if window.frame else None
        _print(f"window[{index}] {window.title or '(untitled)'}{marker} frame={frame} cg={window.cg_window_id}")
        shown = 0
        for element in window.elements:
            if element.depth > max_depth:
                continue
            shown += 1
            if shown <= 40:
                label = element.display_name.replace("\n", " ")[:48]
                identifier = f" id={element.identifier}" if element.identifier else ""
                frame_text = (
                    tuple(round(value, 1) for value in element.frame) if element.frame else None
                )
                _print(f"  {'  ' * element.depth}{element.role:<18} {label:<50}{identifier} {frame_text}")
        if shown > 40:
            _print(f"  ... ({shown - 40} more elements; use --json for the full tree)")
    return 0


def _select_window_target(args: argparse.Namespace) -> tuple[int | None, str | None, bool] | None:
    provided = [args.pid is not None, args.app is not None, args.frontmost]
    if sum(1 for item in provided if item) > 1:
        _print("choose one of --pid, --app, --frontmost")
        return None
    frontmost = args.frontmost or (args.pid is None and args.app is None)
    return args.pid, args.app, frontmost


def cmd_dump(args: argparse.Namespace) -> int:
    target = _select_window_target(args)
    if target is None:
        return 2
    pid, app_name, frontmost = target
    adapter = _adapter()
    try:
        snapshot = adapter.snapshot(
            pid=pid,
            app_name=app_name,
            frontmost=frontmost,
            max_depth=args.max_depth,
        )
    except AxUnavailable as error:
        _describe_ax_error(error)
        return 2 if error.reason == "permission" else 1
    return _window_lines(snapshot, args.json, args.max_depth)


def _capture_window(cg_window_id: int, workdir: Path) -> tuple[bytes, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".png", dir=workdir)
    path = Path(name)
    handle_file = None
    try:
        import os

        handle_file = os.fdopen(handle, "wb")
        handle_file.close()
        handle_file = None
        result = subprocess.run(
            ["screencapture", "-o", "-x", "-l", str(cg_window_id), str(path)],
            capture_output=True,
            timeout=20,
        )
        if result.returncode != 0 or not path.is_file():
            detail = result.stderr.decode("utf-8", "replace").strip()[-200:]
            raise AxUnavailable("helper", f"screencapture failed: {detail or result.returncode}")
        return path.read_bytes(), path
    finally:
        if handle_file is not None:
            handle_file.close()


def _target_matches_fact(target: str, fact_text: str) -> bool:
    target_tokens = set(normalize(target).split())
    fact_tokens = set(normalize(fact_text).split())
    return bool(target_tokens) and target_tokens <= fact_tokens


def cmd_ground(args: argparse.Namespace) -> int:
    target = _select_window_target(args)
    if target is None:
        return 2
    pid, app_name, frontmost = target
    adapter = _adapter()
    try:
        snapshot = adapter.snapshot(pid=pid, app_name=app_name, frontmost=frontmost)
    except AxUnavailable as error:
        _describe_ax_error(error)
        return 2 if error.reason == "permission" else 1
    window = next((w for w in snapshot.windows if w.focused), None) or (
        snapshot.windows[0] if snapshot.windows else None
    )
    if window is None or window.frame is None:
        _print("no window with geometry to ground against")
        return 1

    temp_capture: Path | None = None
    image_bytes: bytes | None = None
    if args.image is not None:
        image_bytes = Path(args.image).read_bytes()
    elif args.capture:
        if window.cg_window_id is None:
            _print("this window has no CG window id on screen; pass --image instead")
            return 1
        try:
            image_bytes, temp_capture = _capture_window(window.cg_window_id, TMP_DIR)
        except AxUnavailable as error:
            _describe_ax_error(error)
            return 1
    else:
        _print("pass --image FILE (a screenshot of just this window) or --capture")
        return 2

    pixels = decode_png(image_bytes)
    image_size = (pixels.width, pixels.height)
    scales = (image_size[0] / window.frame[2], image_size[1] / window.frame[3])
    _print(
        f"window frame {tuple(round(v, 1) for v in window.frame)} -> image {image_size[0]}x{image_size[1]} "
        f"(scales {scales[0]:.3f} x {scales[1]:.3f})"
    )
    if not capture_consistent(window.frame, image_size):
        _print("capture mismatch: the image aspect does not match this window; refusing to ground")
        _print("use --capture (exact window screenshot without shadow) or pass the correct --pid")
        if temp_capture is not None:
            temp_capture.unlink(missing_ok=True)
        return 3

    spec = TargetSpec(args.target, role=args.role, element_id=args.element_id)
    result = ground_target(window.elements, window.frame, image_size, spec)
    _print(f"target: {spec.text!r} (role={spec.role or 'any'} id={spec.element_id or 'any'})")
    _print(f"status: {result.status}")
    if result.chosen is not None:
        chosen = result.chosen
        element = chosen.element
        _print(
            f"identity: {element.role} {element.display_name!r}"
            + (f" identifier={element.identifier}" if element.identifier else "")
            + f" path={element.path} score={chosen.score:.2f} reasons={','.join(chosen.reasons)}"
        )
        _print(f"state: {chosen.state}")
        _print(f"region: {chosen.region} (image pixels)")
        for alternative in result.alternatives:
            _print(f"runner-up: {alternative.element.role} {alternative.element.display_name!r} score={alternative.score:.2f}")
    else:
        _print(result.message)
        for alternative in result.alternatives:
            _print(f"candidate: {alternative.element.role} {alternative.element.display_name!r} score={alternative.score:.2f}")

    crop_bytes: bytes | None = None
    region_size: tuple[int, int] | None = None
    if result.chosen is not None and result.chosen.region is not None:
        x, y, width, height = result.chosen.region
        region_size = (width, height)
        crop_bytes = crop_png(image_bytes, x=x, y=y, width=width, height=height)
        if args.crop_out is not None:
            out_path = Path(args.crop_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(crop_bytes)
            _print(f"crop written: {out_path}")

    if args.ocr_check:
        if crop_bytes is None:
            _print("ocr cross-check: skipped (nothing grounded to crop)")
        else:
            from .ocr_vision import OcrUnavailable, VisionOcrAdapter

            ocr_input = crop_bytes
            note = ""
            if region_size is not None and min(region_size) < 96:
                ocr_input = zoom_png(crop_bytes, factor=2)  # M007 finding: tiny crops need 2x
                note = " (crop zoomed x2)"
            try:
                report = VisionOcrAdapter().collect(ocr_input)
            except OcrUnavailable as error:
                _print(f"ocr cross-check: unavailable — {error}")
            else:
                matched = [fact for fact in report.facts if _target_matches_fact(args.target, fact.text)]
                _print(
                    f"ocr cross-check: {len(report.facts)} line(s) read{note}; "
                    + (f"matched {matched[0].text!r}" if matched else "no line matched the target text")
                )

    if temp_capture is not None:
        temp_capture.unlink(missing_ok=True)
    return 0 if result.status == "found" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vision_assistant.grounding_cli")
    parser.add_argument("--verify", action="store_true", help="run the frozen deterministic gate")
    parser.add_argument("--check", action="store_true", help="report AX trust state (no prompt)")
    parser.add_argument("--request-permission", action="store_true", help="explicit opt-in prompt")
    parser.add_argument("--dump", action="store_true", help="read-only AX snapshot")
    parser.add_argument("--ground", action="store_true", help="resolve a target in a real window")
    parser.add_argument("--target", type=str, default=None)
    parser.add_argument("--role", type=str, default=None)
    parser.add_argument("--element-id", type=str, default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument(
        "--app",
        type=str,
        default=None,
        help="select a running application by name (more reliable than --frontmost)",
    )
    parser.add_argument(
        "--frontmost",
        action="store_true",
        help="use the frontmost application (default when neither --pid nor --app is given)",
    )
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--crop-out", type=Path, default=None)
    parser.add_argument("--ocr-check", action="store_true")
    args = parser.parse_args(argv)

    selected = [args.verify, args.check, args.request_permission, args.dump, args.ground]
    if sum(1 for flag in selected if flag) != 1:
        parser.print_usage(sys.stderr)
        _print("choose exactly one of --verify, --check, --request-permission, --dump, --ground")
        return 2
    if args.verify:
        return cmd_verify()
    if args.check:
        return cmd_check()
    if args.request_permission:
        return cmd_request_permission()
    if args.dump:
        return cmd_dump(args)
    if args.target is None:
        _print("--ground requires --target TEXT")
        return 2
    return cmd_ground(args)


if __name__ == "__main__":
    raise SystemExit(main())
