"""Frozen M012 grounding gate harness (deterministic, no model, no permission).

Runs every frozen task against every frozen variant of the synthetic UI
states and checks:

- ``found`` expectations: exact expected element path, expected state value
  (when specified), and an image region within ±2 px of the independently
  computed expected rect.
- ``not_found`` / ``ambiguous`` expectations: the resolver must fail closed
  with no chosen element.

Writes a result JSON under ``runs/m012/`` (plus the rendered variant PNGs for
visual inspection). No Accessibility permission is needed: the snapshots are
synthetic, built from the same geometry that renders the images.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .ax_vision import AxElement
from .grounding import Region, ground_target, region_close
from .grounding_fixture import (
    FROZEN_TASKS,
    GroundingTask,
    GroundingVariant,
    all_variants,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "runs" / "m012"
REGION_TOLERANCE_PX = 2


@dataclass(frozen=True)
class GateRow:
    task_id: str
    variant: str
    expect: str
    status: str
    identity_ok: bool | None
    state_ok: bool | None
    region_ok: bool | None
    score: float | None
    passed: bool
    message: str


def expected_region(element: AxElement, variant: GroundingVariant) -> Region:
    """Straightforward point→pixel arithmetic, deliberately independent of
    `grounding.image_region_for_frame` so a mapping regression fails the gate."""
    assert element.frame is not None
    fx, fy, fw, fh = element.frame
    wx, wy, ww, wh = variant.window_frame
    iw, ih = variant.image_size
    scale_x = iw / ww
    scale_y = ih / wh
    return (
        round((fx - wx) * scale_x),
        round((fy - wy) * scale_y),
        round(fw * scale_x),
        round(fh * scale_y),
    )


def element_by_id(variant: GroundingVariant, element_id: str) -> AxElement:
    path = variant.id_to_path[element_id]
    for element in variant.elements:
        if element.path == path:
            return element
    raise KeyError(f"fixture element {element_id} not found in variant {variant.name}")


def evaluate_task(task: GroundingTask, variant: GroundingVariant) -> GateRow:
    result = ground_target(variant.elements, variant.window_frame, variant.image_size, task.spec)
    status_ok = result.status == task.expect
    identity_ok: bool | None = None
    state_ok: bool | None = None
    region_ok: bool | None = None
    score: float | None = None
    details: list[str] = []
    if task.expect == "found":
        if result.status == "found" and result.chosen is not None:
            chosen = result.chosen
            score = chosen.score
            identity_ok = chosen.element.path == variant.id_to_path[task.expected_id]
            state_ok = task.expected_value is None or (
                chosen.state is not None and chosen.state.get("value") == task.expected_value
            )
            expected = expected_region(element_by_id(variant, task.expected_id), variant)
            region_ok = chosen.region is not None and region_close(
                chosen.region, expected, REGION_TOLERANCE_PX
            )
            if not identity_ok:
                details.append(f"chosen {chosen.element.path} != expected {task.expected_id}")
            if not state_ok:
                details.append(f"state {chosen.state} missing expected value {task.expected_value!r}")
            if not region_ok:
                details.append(f"region {chosen.region} !~ expected {expected} (±{REGION_TOLERANCE_PX}px)")
        else:
            identity_ok = False
            state_ok = False
            region_ok = False
            details.append(f"status {result.status}: {result.message}")
    else:
        identity_ok = result.chosen is None
        state_ok = result.chosen is None
        region_ok = result.chosen is None
        if not status_ok:
            details.append(f"status {result.status} != {task.expect}: {result.message}")
        elif result.chosen is not None:
            details.append("resolver produced a chosen element despite failing closed")
    passed = status_ok and bool(identity_ok) and bool(state_ok) and bool(region_ok)
    message = "; ".join(details) if details else result.message
    return GateRow(
        task_id=task.task_id,
        variant=variant.name,
        expect=task.expect,
        status=result.status,
        identity_ok=identity_ok,
        state_ok=state_ok,
        region_ok=region_ok,
        score=score,
        passed=passed,
        message=message,
    )


def run_frozen_gate(
    *,
    tasks: tuple[GroundingTask, ...] | None = None,
    variants: tuple[GroundingVariant, ...] | None = None,
    out_dir: Path | None = None,
    write: bool = True,
    run_id: str | None = None,
) -> dict:
    task_list = FROZEN_TASKS if tasks is None else tuple(tasks)
    variant_list = all_variants() if variants is None else tuple(variants)
    rows = [evaluate_task(task, variant) for variant in variant_list for task in task_list]
    failures = [row for row in rows if not row.passed]
    variant_counts = {
        variant.name: {
            "checks": sum(1 for row in rows if row.variant == variant.name),
            "passed": sum(1 for row in rows if row.variant == variant.name and row.passed),
        }
        for variant in variant_list
    }
    summary = {
        "checks": len(rows),
        "passed": len(rows) - len(failures),
        "gate_pass": not failures,
        "failures": [asdict(row) for row in failures],
        "variants": variant_counts,
    }
    identifier = run_id or f"m012-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
    payload = {
        "run_id": identifier,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "rows": [asdict(row) for row in rows],
    }
    if write:
        directory = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        fixtures_dir = directory / "fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        for variant in variant_list:
            (fixtures_dir / f"{variant.name}.png").write_bytes(variant.image_png)
        (directory / f"grounding-{identifier}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return payload
