"""Screenshot ↔ Accessibility alignment and target resolution (M012).

Given the read-only AX snapshot of a window and a screenshot of the same
window, this module maps element frames (global screen points) into image
pixel regions and resolves human-readable targets ("search field", "SYNC")
to a stable element identity plus state.

Design rules:
- Stable identities win: an explicit AX identifier match beats a label match,
  and labels are compared through normalized role-aware scoring.
- Fail closed: an absent target resolves ``not_found``; two equally good
  candidates resolve ``ambiguous``. The resolver never guesses, and callers
  must treat anything but ``found`` as "do not act".
- Coordinates locate elements in the image; they never address them.
- No input events exist anywhere in this module or its dependencies.

Nothing here runs automatically; it is read-only geometry and matching.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .ax_vision import AxElement

Frame = tuple[float, float, float, float]
Region = tuple[int, int, int, int]
Size = tuple[int, int]

ACCEPT_SCORE = 0.5
AMBIGUITY_MARGIN = 0.02

ROLE_ALIASES = {
    "button": "AXButton",
    "checkbox": "AXCheckBox",
    "link": "AXLink",
    "textfield": "AXTextField",
    "text": "AXStaticText",
    "statictext": "AXStaticText",
    "heading": "AXHeading",
    "radiobutton": "AXRadioButton",
    "popupbutton": "AXPopUpButton",
    "window": "AXWindow",
}

_FILLERS = {"the", "a", "an"}
_ROLE_NOUNS = {
    "field",
    "box",
    "button",
    "checkbox",
    "check",
    "toggle",
    "link",
    "label",
    "heading",
    "text",
}

_EXACT = 1.0
_TOKEN_SUBSET = 0.9
_SUBSTRING = 0.8
_CORE_COVERED = 0.75
_SUBSTRING_MIN_CHARS = 4

_FIELD_WEIGHTS = (("title", 1.0), ("identifier", 1.0), ("description", 0.95), ("value", 0.85))


def normalize(text: str) -> str:
    """Casefold and collapse punctuation/whitespace for comparisons."""
    cleaned = []
    for ch in text.casefold():
        cleaned.append(ch if ch.isalnum() else " ")
    return " ".join("".join(cleaned).split())


def _tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def score_label(query: str, label: str) -> float:
    """Score how well *label* answers a free-text *query*. Zero means no match.

    Query words must all be accounted for: words that are not present in the
    candidate must be generic role nouns ("field", "button", ...) or fillers.
    Extra candidate words are allowed — real UI labels are more specific than
    the target phrasing ("CANCEL CHANGES" for "cancel"). A substring match
    only counts at a word boundary and only for queries of at least four
    characters, so short queries can never match the middle of a word
    ("AC" must not match "Subtract").
    """
    query_norm = normalize(query)
    label_norm = normalize(label)
    if not query_norm or not label_norm:
        return 0.0
    if query_norm == label_norm:
        return _EXACT
    query_tokens = _tokens(query)
    label_tokens = _tokens(label)
    if query_tokens and query_tokens <= label_tokens:
        return _TOKEN_SUBSET
    if len(query_norm) >= _SUBSTRING_MIN_CHARS and f" {query_norm}" in f" {label_norm}":
        return _SUBSTRING
    core = query_tokens - _ROLE_NOUNS - _FILLERS
    if core and core <= label_tokens:
        return _CORE_COVERED
    return 0.0


@dataclass(frozen=True)
class TargetSpec:
    """What the user asked to find. `role` is a short alias or an AX role."""

    text: str
    role: str | None = None
    element_id: str | None = None


@dataclass(frozen=True)
class GroundedTarget:
    element: AxElement
    score: float
    reasons: tuple[str, ...]
    region: Region | None = None
    state: dict | None = None


@dataclass(frozen=True)
class GroundingResult:
    status: str  # "found" | "ambiguous" | "not_found"
    spec: TargetSpec
    chosen: GroundedTarget | None
    alternatives: tuple[GroundedTarget, ...]
    message: str


def element_state(element: AxElement) -> dict:
    """Trace-safe state summary; secure values are dropped defensively."""
    return {
        "enabled": element.enabled,
        "focused": element.focused,
        "value": None if element.secure else element.value,
    }


def effective_role(role: str) -> str:
    return ROLE_ALIASES.get(role.casefold(), role)


def _score_element(element: AxElement, spec: TargetSpec) -> tuple[float, tuple[str, ...]]:
    if spec.element_id is not None:
        if not element.identifier or normalize(element.identifier) != normalize(spec.element_id):
            return 0.0, ()
        if spec.role is not None and element.role != effective_role(spec.role):
            return 0.0, ()
        return _EXACT, ("identifier",)
    if spec.role is not None and element.role != effective_role(spec.role):
        return 0.0, ()
    best = 0.0
    reasons: list[str] = []
    for field_name, weight in _FIELD_WEIGHTS:
        if field_name == "value" and element.secure:
            continue
        label = getattr(element, field_name)
        if not isinstance(label, str) or not label:
            continue
        score = score_label(spec.text, label) * weight
        if score > best:
            best = score
            reasons = [field_name]
        elif score == best > 0.0:
            reasons.append(field_name)
    return best, tuple(reasons)


def resolve_target(elements: tuple[AxElement, ...], spec: TargetSpec) -> GroundingResult:
    """Resolve a target to one element identity, or fail closed."""
    scored: list[GroundedTarget] = []
    for element in elements:
        score, reasons = _score_element(element, spec)
        if score >= ACCEPT_SCORE:
            scored.append(GroundedTarget(element=element, score=score, reasons=reasons))
    if not scored:
        return GroundingResult(
            status="not_found",
            spec=spec,
            chosen=None,
            alternatives=(),
            message=f"no element matched target {spec.text!r} above {ACCEPT_SCORE}",
        )
    scored.sort(key=lambda target: (-target.score, target.element.depth, target.element.path))
    top = scored[0]
    if len(scored) > 1 and abs(top.score - scored[1].score) <= AMBIGUITY_MARGIN:
        runner_up = scored[1]
        return GroundingResult(
            status="ambiguous",
            spec=spec,
            chosen=None,
            alternatives=tuple(scored[:3]),
            message=(
                f"target {spec.text!r} matches both "
                f"{top.element.display_name!r} and {runner_up.element.display_name!r}; "
                "refusing to guess"
            ),
        )
    return GroundingResult(
        status="found",
        spec=spec,
        chosen=top,
        alternatives=tuple(scored[1:3]),
        message=f"resolved {spec.text!r} to {top.element.display_name!r} ({top.element.role})",
    )


def image_region_for_frame(
    frame: Frame,
    window_frame: Frame,
    image_size: Size,
    *,
    clip: bool = True,
) -> Region | None:
    """Map a screen-point frame into an image pixel region.

    Scale is derived from the image and window sizes, so Retina captures
    (2x) need no special handling. Returns ``None`` when the element has no
    overlap with the image (with ``clip=True``) or the inputs are degenerate.
    """
    fx, fy, fw, fh = frame
    wx, wy, ww, wh = window_frame
    iw, ih = image_size
    if ww <= 0 or wh <= 0 or iw <= 0 or ih <= 0 or fw <= 0 or fh <= 0:
        return None
    scale_x = iw / ww
    scale_y = ih / wh
    left = round((fx - wx) * scale_x)
    top = round((fy - wy) * scale_y)
    right = round((fx - wx + fw) * scale_x)
    bottom = round((fy - wy + fh) * scale_y)
    if right <= left:
        right = left + 1
    if bottom <= top:
        bottom = top + 1
    if clip:
        left = max(0, left)
        top = max(0, top)
        right = min(iw, right)
        bottom = min(ih, bottom)
        if right <= left or bottom <= top:
            return None
    return (left, top, right - left, bottom - top)


def capture_consistent(window_frame: Frame, image_size: Size, *, tolerance: float = 0.06) -> bool:
    """True when the image could plausibly be a screenshot of this window.

    Retina scales make x/y factors differ by a few percent at most; larger
    mismatches mean the image and the AX window do not belong together.
    """
    ww, wh = window_frame[2], window_frame[3]
    iw, ih = image_size
    if ww <= 0 or wh <= 0 or iw <= 0 or ih <= 0:
        return False
    scale_x = iw / ww
    scale_y = ih / wh
    largest = max(scale_x, scale_y)
    return abs(scale_x - scale_y) / largest <= tolerance


def ground_target(
    elements: tuple[AxElement, ...],
    window_frame: Frame,
    image_size: Size,
    spec: TargetSpec,
) -> GroundingResult:
    """Resolve *spec* and attach the image region + state to the chosen element."""
    result = resolve_target(elements, spec)
    if result.status != "found" or result.chosen is None:
        return result
    element = result.chosen.element
    region = image_region_for_frame(element.frame, window_frame, image_size) if element.frame else None
    enriched = replace(result.chosen, region=region, state=element_state(element))
    alternatives = tuple(
        replace(
            alternative,
            region=image_region_for_frame(alternative.element.frame, window_frame, image_size)
            if alternative.element.frame
            else None,
            state=element_state(alternative.element),
        )
        for alternative in result.alternatives
    )
    return replace(result, chosen=enriched, alternatives=alternatives)


def region_close(region: Region, other: Region, tolerance: int = 2) -> bool:
    """True when two regions agree on every edge within *tolerance* pixels."""
    return all(abs(a - b) <= tolerance for a, b in zip(region, other))
