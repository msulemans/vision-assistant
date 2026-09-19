"""M015 profile registry: measured and planned configurations, stated honestly.

Profiles are data only. "Measured" entries carry values observed on the
frozen bake-off runs (M005) on the M2 Max reference host; "planned" entries
are clearly marked unmeasured. The default profile is the M005 selection.

The image budget is the shipped empirical value (pixels.MODEL_IMAGE_MAX_PIXELS)
for every measured profile — no untested reductions are claimed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pixels import MODEL_IMAGE_MAX_PIXELS

DEFAULT_PROFILE = "balanced"

M005_MEASURED = {
    "host": "Apple M2 Max (reference host)",
    "rss_gib": 3.792,
    "swap_gib": 0.0,
    "first_p95_ms": 839,
    "complete_p95_ms": 1389,
    "held_out_pass": "23/24 (≥ 0.95 gate)",
    "measured_on": "2026-09-19",
}


@dataclass(frozen=True)
class Profile:
    name: str
    title: str
    description: str
    model_candidate: str | None
    ctx_size: int
    enable_thinking: bool
    image_max_pixels: int
    memory_target_gib: float
    status: str  # "measured" | "planned"
    measured: dict
    notes: str


PROFILES: tuple[Profile, ...] = (
    Profile(
        name="inspect",
        title="Inspect",
        description="Modern laptop, low resource; one image per turn, read-only.",
        model_candidate="qwen3.5-4b",
        ctx_size=4096,
        enable_thinking=False,
        image_max_pixels=MODEL_IMAGE_MAX_PIXELS,
        memory_target_gib=6.0,
        status="measured",
        measured=M005_MEASURED,
        notes=(
            "Same pinned candidate as balanced; its measured RSS fits the "
            "6 GiB target. Measured on the M2 Max reference host — "
            "low-resource-device certification has not been performed."
        ),
    ),
    Profile(
        name="balanced",
        title="Balanced",
        description="This M2 Max; best measured 4B-class candidate.",
        model_candidate="qwen3.5-4b",
        ctx_size=4096,
        enable_thinking=False,
        image_max_pixels=MODEL_IMAGE_MAX_PIXELS,
        memory_target_gib=8.0,
        status="measured",
        measured=M005_MEASURED,
        notes="M005 Phase-1 selection; the default profile.",
    ),
    Profile(
        name="quality",
        title="Quality",
        description="32 GB laptop/workstation; up to 9B quantized.",
        model_candidate=None,
        ctx_size=4096,
        enable_thinking=False,
        image_max_pixels=MODEL_IMAGE_MAX_PIXELS,
        memory_target_gib=14.0,
        status="planned",
        measured={},
        notes=(
            "Requires a ≤9B bake-off that has not been run; no candidate is "
            "pinned and no resource claim is made."
        ),
    ),
)


def get_profile(name: str) -> Profile:
    for profile in PROFILES:
        if profile.name == name:
            return profile
    raise ValueError(f"unknown profile {name!r}; choose from {[p.name for p in PROFILES]}")


def default_profile() -> Profile:
    return get_profile(DEFAULT_PROFILE)


def profile_summaries() -> list[dict]:
    """Serializable summaries for manifests and forecasts."""
    return [
        {
            "name": profile.name,
            "title": profile.title,
            "status": profile.status,
            "model_candidate": profile.model_candidate,
            "ctx_size": profile.ctx_size,
            "enable_thinking": profile.enable_thinking,
            "image_max_pixels": profile.image_max_pixels,
            "memory_target_gib": profile.memory_target_gib,
            "measured": profile.measured,
            "notes": profile.notes,
        }
        for profile in PROFILES
    ]
