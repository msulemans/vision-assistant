"""M010 typed action intents and consequence policy — proposals only.

The model can propose actions as strict JSON objects; trusted code validates
them against an exact schema and a consequence policy, then renders a preview
for the user. There is deliberately no executor anywhere in this module or
milestone: it cannot post input events, run commands, or control the Mac.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

MAX_INTENTS_PER_TASK = 12
MAX_TYPE_CHARS = 200
MAX_SCROLL_STEPS = 10
MAX_LABEL_CHARS = 120
MAX_SUMMARY_CHARS = 280

KINDS = ("observe", "click_element", "type_text", "press_key", "scroll", "cancel", "finish")
READ_ONLY_KINDS = ("observe", "cancel", "finish")
MUTATING_KINDS = ("click_element", "type_text", "press_key", "scroll")

ALLOWED_KEYS = frozenset(
    {
        "return",
        "tab",
        "escape",
        "space",
        "up",
        "down",
        "left",
        "right",
        "page_up",
        "page_down",
        "home",
        "end",
        "delete",
        "backspace",
    }
)
DIRECTIONS = ("up", "down", "left", "right")
SECRET_TERMS = ("password", "passcode", "secret", "token", "pin", "cvv", "card number", "ssn")

_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_COORDINATE_KEYS = frozenset({"x", "y", "px", "py", "screen_x", "screen_y", "coordinate", "coordinates"})

_ALLOWED_KEYS_BY_KIND = {
    "observe": frozenset({"kind", "window_id"}),
    "click_element": frozenset({"kind", "window_id", "element_id", "role", "name"}),
    "type_text": frozenset({"kind", "window_id", "text", "field", "element_id"}),
    "press_key": frozenset({"kind", "window_id", "key"}),
    "scroll": frozenset({"kind", "window_id", "direction", "steps"}),
    "cancel": frozenset({"kind"}),
    "finish": frozenset({"kind", "summary"}),
}


class IntentSchemaError(ValueError):
    """The proposed payload is not a valid intent."""


@dataclass(frozen=True)
class ActionIntent:
    kind: str
    params: Mapping

    def describe(self) -> str:
        if self.kind == "observe":
            return "observe: take a fresh screenshot of the same window"
        if self.kind == "click_element":
            target = self.params.get("name") or self.params["element_id"]
            return f"click_element: click \u201c{target}\u201d"
        if self.kind == "type_text":
            field = self.params.get("field") or "the focused field"
            return f"type_text: type {len(self.params['text'])} characters into \u201c{field}\u201d"
        if self.kind == "press_key":
            return f"press_key: press {self.params['key']}"
        if self.kind == "scroll":
            return f"scroll: scroll {self.params['direction']} by {self.params['steps']}"
        if self.kind == "cancel":
            return "cancel: stop the current task"
        return f"finish: {self.params['summary']}"


def _identifier(payload: Mapping, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise IntentSchemaError(f"field {key!r} must be a compact identifier")
    return value


def _label(payload: Mapping, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IntentSchemaError(f"field {key!r} must be a non-empty string")
    if len(value) > MAX_LABEL_CHARS:
        raise IntentSchemaError(f"field {key!r} exceeds {MAX_LABEL_CHARS} characters")
    return value


def parse_intent(payload: object) -> ActionIntent:
    """Strict parse of one model-proposed intent. Unknown anything is rejected."""
    if not isinstance(payload, Mapping):
        raise IntentSchemaError("an intent must be a JSON object")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise IntentSchemaError(f"unknown intent kind {kind!r}")
    coordinates = set(payload) & _COORDINATE_KEYS
    if coordinates:
        raise IntentSchemaError(
            f"raw coordinates {sorted(coordinates)} are not accepted; use element addressing"
        )
    unknown = set(payload) - _ALLOWED_KEYS_BY_KIND[kind]
    if unknown:
        raise IntentSchemaError(f"unexpected fields {sorted(unknown)} for {kind!r}")

    window_id = _identifier(payload, "window_id")
    params: dict = {"window_id": window_id}

    if kind == "observe":
        pass
    elif kind == "click_element":
        element_id = _identifier(payload, "element_id")
        if element_id is None:
            raise IntentSchemaError("click_element requires an element_id")
        params["element_id"] = element_id
        params["role"] = _label(payload, "role")
        params["name"] = _label(payload, "name")
    elif kind == "type_text":
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise IntentSchemaError("type_text requires non-empty text")
        if len(text) > MAX_TYPE_CHARS:
            raise IntentSchemaError(f"text exceeds {MAX_TYPE_CHARS} characters")
        if any(ord(char) < 32 for char in text):
            raise IntentSchemaError("text must not contain control characters")
        params["text"] = text
        params["field"] = _label(payload, "field")
        params["element_id"] = _identifier(payload, "element_id")
    elif kind == "press_key":
        key = payload.get("key")
        if key not in ALLOWED_KEYS:
            raise IntentSchemaError(f"key {key!r} is not on the allowlist")
        params["key"] = key
    elif kind == "scroll":
        direction = payload.get("direction")
        if direction not in DIRECTIONS:
            raise IntentSchemaError(f"direction must be one of {DIRECTIONS}")
        steps = payload.get("steps")
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise IntentSchemaError("steps must be an integer")
        if not 1 <= steps <= MAX_SCROLL_STEPS:
            raise IntentSchemaError(f"steps must be between 1 and {MAX_SCROLL_STEPS}")
        params["direction"] = direction
        params["steps"] = steps
    elif kind == "cancel":
        pass
    elif kind == "finish":
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise IntentSchemaError("finish requires a summary")
        if len(summary) > MAX_SUMMARY_CHARS:
            raise IntentSchemaError(f"summary exceeds {MAX_SUMMARY_CHARS} characters")
        params["summary"] = summary

    return ActionIntent(kind=kind, params=params)


@dataclass(frozen=True)
class PolicyDecision:
    verdict: str  # "preview_only" | "needs_confirmation" | "denied"
    reasons: tuple[str, ...] = ()


class ActionPolicy:
    """Consequence policy for proposed intents.

    Nothing executes in M010; verdicts describe what would be required once
    execution exists (M011+). Denials are final.
    """

    def __init__(
        self,
        *,
        max_intents: int = MAX_INTENTS_PER_TASK,
        scope_window_id: str | None = None,
    ) -> None:
        self.max_intents = max_intents
        self.scope_window_id = scope_window_id

    def review(self, intent: ActionIntent, *, intent_count: int) -> PolicyDecision:
        if intent_count >= self.max_intents:
            return PolicyDecision("denied", ("task intent budget exceeded",))
        window_id = intent.params.get("window_id")
        if (
            self.scope_window_id is not None
            and window_id is not None
            and window_id != self.scope_window_id
        ):
            return PolicyDecision("denied", ("target window is outside the captured scope",))
        if intent.kind in READ_ONLY_KINDS:
            return PolicyDecision("preview_only", ("read-only or terminal intent",))
        if intent.kind == "type_text":
            target = " ".join(
                part for part in (intent.params.get("field"), intent.params.get("element_id")) if part
            ).lower()
            if any(term in target for term in SECRET_TERMS):
                return PolicyDecision("denied", ("secret-entry targets are never typed",))
        return PolicyDecision(
            "needs_confirmation",
            ("mutating intent", "would require explicit approval once execution exists"),
        )


def render_preview(intent: ActionIntent, decision: PolicyDecision) -> str:
    badge = {
        "preview_only": "PREVIEW \u00b7 no approval needed",
        "needs_confirmation": "PROPOSAL \u00b7 explicit approval required (not executable in this milestone)",
        "denied": "DENIED",
    }[decision.verdict]
    reasons = f" \u2014 {'; '.join(decision.reasons)}" if decision.reasons else ""
    return f"{badge}: {intent.describe()}{reasons}"
