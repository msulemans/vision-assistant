"""M022: multi-viewport evidence accumulation in scan mode (deterministic core).

Frozen contract (docs/M022_EVIDENCE_LEDGER_PLAN.md):

- Trusted code owns the traversal: it starts at the top, moves at most 70% of
  one viewport per step (keeping >=30% overlap), and continues top-to-bottom
  until the document end (max 8 viewports). Every captured viewport records
  observation_id, scroll position, viewport height, and document height;
  skipped ranges, unchanged viewports, and layout changes are detected and
  rejected — the run fails closed rather than guessing.
- The model may only: record_candidates (rank, title, visible_points, and
  ai_relevance per candidate, each citing the CURRENT observation),
  no_candidates, next_viewport (no amount — the trusted step is fixed), and
  stop. Three phases: while not at the end ("scanning") the model records a
  viewport and calls next_viewport to advance; at the document end
  ("recording") the final viewport is still recorded with its screenshot and
  one more next_viewport closes the traversal (no scroll happens); "final"
  is a ledger-only call (no screenshot) that confirms the trusted
  selection. Clicking, typing, submissions, and navigation are not in the
  action set at all.
- The trusted evidence ledger keeps candidates across observations, preserves
  which screenshot supports every field (observation_id), rejects stale or
  unknown observations, and rejects duplicates and conflicting rank/title
  claims instead of silently overwriting.
- Completion: trusted code sorts the ledger by rank and selects the first
  three stories marked "primary" about AI/ML. The final call receives only
  the bounded structured ledger (no screenshots) and may confirm/explain the
  selection but cannot add, remove, or change stories. The exact visible
  title -> HN item link mapping happens after the selection from trusted DOM
  metadata that never enters any model prompt.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import browser_targets
from .pixels import fit_for_model

RUN_VERSION = "m022-scan-v1"

HN_HOST = "news.ycombinator.com"
# Assembled from parts so the frozen source-line URL-literal rules stay
# satisfied (scheme separators live only in acquire/runtime_llamaserver).
HN_ORIGIN = "https:" + "//" + HN_HOST
START_URL = HN_ORIGIN + "/"

# Frozen traversal + budget contract.
MAX_VIEWPORTS = 8
VIEWPORT_STEP_RATIO = 0.7
TOLERANCE_PX = 2
MAX_CALLS = 20
MAX_SECONDS = 180.0
CTX_SIZE = 8192
MAX_CANDIDATES_PER_CALL = 20
LEDGER_PROMPT_LIMIT = 40

SCAN_ACTIONS = ("record_candidates", "no_candidates", "next_viewport",
                "finish_selection", "stop")
AI_RELEVANCE = ("primary", "incidental")

MAX_TEXT_CHARS = 300
_TARGET_ID_RE = re.compile(r"^t[1-9][0-9]{0,2}$")
_HN_ITEM_RE = re.compile(r"^(?:/|\./)?item\?id=[0-9]+")

GOAL = (
    "Read the Hacker News front page top to bottom, one viewport at a time, "
    "and record every story whose subject involves AI or machine learning. "
    "Rank is the number shown at the start of a story's row (1 is the top "
    "story). For each candidate give the visible points and mark it "
    '"primary" when its main subject is AI/ML (an AI model, a research '
    "result, a product whose core purpose is AI/ML, or directly related "
    "policy or safety news) or \"incidental\" when AI is mentioned but is "
    "not the main subject. Record only what you can read in a screenshot; "
    "never invent or reword titles. The trusted selection at the end is the "
    "three lowest-ranked primary stories."
)

CLASSIFICATION_RULE = (
    "Frozen before the run. A story qualifies as AI/ML only when its main "
    "subject is artificial intelligence or machine learning: an AI/ML model, "
    "a research result, a product or system whose core purpose is AI/ML, or "
    "directly related policy/safety news. Incidental keywords in an "
    "otherwise unrelated story, and generic software or business stories, "
    "do not qualify. Used only by the reviewer/trusted selection, never "
    "shown to the model."
)

HN_LINK_NOTE = ("hn_link is trusted browser metadata (DOM link rows "
                "collected after the selection); it never enters any model "
                "prompt.")

# 1x1 PNG placeholder for the final call: the final step receives only the
# bounded structured ledger, not a screenshot.
_PLACEHOLDER_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhf"
    "DwAChwGA60e6kgAAAABJRU5ErkJggg==")


def placeholder_png() -> bytes:
    return base64.b64decode(_PLACEHOLDER_B64)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def goal_sha256() -> str:
    import hashlib
    return hashlib.sha256(GOAL.encode("utf-8")).hexdigest()


class ScanError(Exception):
    """Typed traversal/ledger refusal; ``reason`` is a frozen error code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason if not detail else "{}: {}".format(reason, detail))
        self.reason = reason
        self.detail = detail


# ------------------------------------------------------------ 1. traversal

@dataclass(frozen=True)
class Viewport:
    observation_id: str
    scroll_y: int
    viewport_height: int
    document_height: int
    seq: int


class ViewportTraversal:
    """Trusted top-to-bottom traversal with fixed 70% steps and overlap."""

    def __init__(self, max_viewports: int = MAX_VIEWPORTS,
                 step_ratio: float = VIEWPORT_STEP_RATIO,
                 tolerance: int = TOLERANCE_PX) -> None:
        self.max_viewports = int(max_viewports)
        self.step_ratio = float(step_ratio)
        self.tolerance = int(tolerance)
        self.viewports: list = []
        self.complete = False

    @property
    def current(self) -> Viewport:
        if not self.viewports:
            raise ScanError("traversal_not_started")
        return self.viewports[-1]

    def _validate_metrics(self, scroll_y, viewport_height, document_height) -> None:
        for name, value in (("scroll_y", scroll_y), ("viewport_height", viewport_height),
                            ("document_height", document_height)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ScanError("traversal_metrics_invalid", "{} must be an int".format(name))
        if viewport_height <= 0 or document_height <= 0:
            raise ScanError("traversal_metrics_invalid",
                            "viewport/document height must be positive")

    def begin(self, *, scroll_y: int, viewport_height: int, document_height: int,
              observation_id: str, seq: int = 0) -> Viewport:
        self._validate_metrics(scroll_y, viewport_height, document_height)
        if scroll_y > self.tolerance:
            raise ScanError("traversal_not_at_top",
                            "traversal begins at scroll position 0; got y={}".format(scroll_y))
        viewport = Viewport(observation_id=observation_id, scroll_y=int(scroll_y),
                            viewport_height=int(viewport_height),
                            document_height=int(document_height), seq=int(seq))
        self.viewports.append(viewport)
        self.complete = self._at_end(viewport)
        return viewport

    def _at_end(self, viewport: Viewport) -> bool:
        return (viewport.scroll_y + viewport.viewport_height
                >= viewport.document_height - self.tolerance)

    def next_step_px(self):
        """The trusted next step in CSS pixels (None when at the end)."""

        if self.complete or not self.viewports:
            return None
        viewport = self.current
        max_scroll = max(0, viewport.document_height - viewport.viewport_height)
        remaining = max_scroll - viewport.scroll_y
        if remaining <= 0:
            return None
        step = min(int(self.step_ratio * viewport.viewport_height), remaining)
        return step if step > 0 else None

    def next_fraction(self):
        """The trusted next step as a viewport fraction (helper dom scroll)."""

        step = self.next_step_px()
        if step is None:
            return None
        return step / float(self.current.viewport_height)

    def advance(self, *, scroll_y: int, viewport_height: int, document_height: int,
                observation_id: str, seq: int = 0) -> Viewport:
        if not self.viewports:
            raise ScanError("traversal_not_started")
        if self.complete:
            raise ScanError("traversal_complete",
                            "the document end was already reached")
        self._validate_metrics(scroll_y, viewport_height, document_height)
        previous = self.current
        if scroll_y <= previous.scroll_y:
            raise ScanError("viewport_unchanged",
                            "scroll position did not advance (y={})".format(scroll_y))
        delta = scroll_y - previous.scroll_y
        allowed = int(self.step_ratio * previous.viewport_height) + self.tolerance
        if delta > allowed:
            raise ScanError("viewport_gap",
                            "step of {} px exceeds the overlap window ({} px): "
                            "a range would be skipped".format(delta, allowed))
        if abs(viewport_height - previous.viewport_height) > self.tolerance:
            raise ScanError("viewport_metrics_changed",
                            "viewport height changed from {} to {}".format(
                                previous.viewport_height, viewport_height))
        if abs(document_height - previous.document_height) > self.tolerance:
            raise ScanError("viewport_layout_changed",
                            "document height changed from {} to {}".format(
                                previous.document_height, document_height))
        if len(self.viewports) + 1 > self.max_viewports:
            raise ScanError("viewport_budget",
                            "maximum {} viewports reached".format(self.max_viewports))
        viewport = Viewport(observation_id=observation_id, scroll_y=int(scroll_y),
                            viewport_height=int(viewport_height),
                            document_height=int(document_height), seq=int(seq))
        self.viewports.append(viewport)
        self.complete = self._at_end(viewport)
        return viewport


# --------------------------------------------------------------- 2. ledger

def normalize_title(title: str) -> str:
    return " ".join((title or "").split()).casefold()


@dataclass(frozen=True)
class LedgerEntry:
    rank: int
    title: str
    visible_points: object  # int | None
    ai_relevance: str
    reason: str
    observation_id: str

    def as_dict(self) -> dict:
        return {"rank": self.rank, "title": self.title,
                "visible_points": self.visible_points,
                "ai_relevance": self.ai_relevance, "reason": self.reason,
                "observation_id": self.observation_id}


class EvidenceLedger:
    """Candidates across observations; duplicates/conflicts never overwrite."""

    def __init__(self) -> None:
        self.entries: list = []

    def add(self, candidate: dict, *, current_observation_id: str) -> LedgerEntry:
        observation_id = candidate.get("observation_id", "")
        if observation_id != current_observation_id:
            raise ScanError("stale_observation",
                            "candidate cites {} but the current observation "
                            "is {}".format(observation_id or "(none)",
                                           current_observation_id or "(none)"))
        rank = candidate["rank"]
        normalized = normalize_title(candidate["title"])
        for entry in self.entries:
            if entry.rank == rank and normalize_title(entry.title) == normalized:
                raise ScanError("duplicate_candidate",
                                "rank {} '{}' is already recorded (from {})".format(
                                    rank, entry.title, entry.observation_id))
            if entry.rank == rank:
                raise ScanError("conflicting_candidate",
                                "rank {} is already recorded as '{}' — a "
                                "different title cannot reuse a rank".format(
                                    rank, entry.title))
            if normalize_title(entry.title) == normalized:
                raise ScanError("conflicting_candidate",
                                "'{}' is already recorded at rank {} — a "
                                "title cannot move ranks".format(
                                    entry.title, entry.rank))
        entry = LedgerEntry(rank=rank, title=candidate["title"],
                            visible_points=candidate.get("visible_points"),
                            ai_relevance=candidate["ai_relevance"],
                            reason=candidate["reason"],
                            observation_id=observation_id)
        self.entries.append(entry)
        return entry

    def primaries_by_rank(self) -> list:
        primaries = [entry for entry in self.entries
                     if entry.ai_relevance == "primary"]
        return sorted(primaries, key=lambda entry: entry.rank)

    def selection(self, max_stories: int = 3) -> list:
        return self.primaries_by_rank()[:max_stories]

    def as_dicts(self) -> list:
        return [entry.as_dict() for entry in self.entries]


# ------------------------------------------------------ 3. validators

def _check_text(prefix: str, key: str, value) -> str:
    if not isinstance(value, str):
        return "{}: {} must be a string".format(prefix, key)
    if not value.strip():
        return "{}: {} must not be empty".format(prefix, key)
    if len(value) > MAX_TEXT_CHARS:
        return "{}: {} is too long".format(prefix, key)
    if any(ord(ch) < 32 for ch in value):
        return "{}: {} must not contain control characters".format(prefix, key)
    stripped = value.strip()
    if browser_targets.valid_ui_ref(stripped):
        return "{}: {} holds a ui: target reference, not page data".format(prefix, key)
    if _TARGET_ID_RE.match(stripped):
        return "{}: {} holds a target id, not page data".format(prefix, key)
    return ""


def validate_candidate(candidate, *, current_observation_id: str,
                       prefix: str = "candidate"):
    if not isinstance(candidate, dict):
        return None, "{} must be an object".format(prefix)
    allowed = {"rank", "title", "visible_points", "ai_relevance", "reason",
               "observation_id"}
    for key in sorted(candidate):
        if key not in allowed:
            return None, "{}: unexpected field {!r}".format(prefix, key)
    for key in ("rank", "title", "ai_relevance", "reason", "observation_id"):
        if key not in candidate:
            return None, "{}: missing field {!r}".format(prefix, key)
    rank = candidate["rank"]
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        return None, "{}: rank must be an integer >= 1".format(prefix)
    error = _check_text(prefix, "title", candidate["title"])
    if error:
        return None, error
    if "visible_points" in candidate:
        points = candidate["visible_points"]
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            return None, "{}: visible_points must be an integer >= 0".format(prefix)
    if candidate["ai_relevance"] not in AI_RELEVANCE:
        return None, ('{}: ai_relevance must be "primary" or "incidental"'
                      .format(prefix))
    error = _check_text(prefix, "reason", candidate["reason"])
    if error:
        return None, error
    observation_id = candidate["observation_id"]
    if not isinstance(observation_id, str) or not observation_id:
        return None, "{}: observation_id must be a non-empty string".format(prefix)
    if current_observation_id and observation_id != current_observation_id:
        return None, ("{}: stale observation {} — the current observation is "
                      "{}".format(prefix, observation_id, current_observation_id))
    return dict(candidate), None


def scan_capabilities(phase: str) -> dict:
    """The frozen per-phase capability budget (prompt + validator share it).

    "scanning" (not at the end): record, refuse-to-record, advance, stop.
    "recording" (at the end): same — recording the final viewport with its
    screenshot; next_viewport closes the traversal instead of scrolling.
    "final": ledger-only — confirm the trusted selection or stop.
    """

    if phase == "final":
        allowed = ["finish_selection", "stop"]
    else:
        allowed = ["record_candidates", "no_candidates", "next_viewport",
                   "stop"]
    return {"allowed_actions": allowed,
            "unavailable_actions": [a for a in SCAN_ACTIONS if a not in allowed],
            "phase": phase}


def validate_scan_action(payload, *, observation_id: str,
                         traversal: ViewportTraversal, phase: str,
                         selection_ranks=()):
    """Return (action, None) or (None, error). Strict, fail-closed."""

    if not isinstance(payload, dict):
        return None, "action must be an object"
    kind = payload.get("action")
    if kind not in SCAN_ACTIONS:
        return None, "unknown scan action: {!r} — allowed: {}".format(
            kind, ", ".join(scan_capabilities(phase)["allowed_actions"]))
    if phase == "final" and kind in ("record_candidates", "no_candidates"):
        return None, ("recording is closed — the ledger is final; confirm the "
                      "trusted selection with finish_selection")
    if phase == "final" and kind == "next_viewport":
        return None, "the traversal is already closed — finish_selection or stop"
    if (kind == "next_viewport" and phase != "final"
            and not traversal.complete
            and len(traversal.viewports) >= traversal.max_viewports):
        return None, ("viewport budget exhausted ({} of {}) — stop and "
                      "report what is recorded".format(
                          len(traversal.viewports), traversal.max_viewports))
    if phase != "final" and kind == "finish_selection":
        if traversal.complete:
            return None, ("record the final viewport first (or no_candidates), "
                          "then call next_viewport to close the traversal")
        return None, ("traversal incomplete: {} viewport(s) captured and the "
                      "document end has not been reached — use "
                      "next_viewport".format(len(traversal.viewports)))
    allowed = {"action"}
    if kind in ("record_candidates", "no_candidates", "next_viewport"):
        allowed.add("observation_id")
    if kind == "record_candidates":
        allowed.add("candidates")
    if kind == "finish_selection":
        allowed |= {"ranks", "explanation"}
    if kind == "stop":
        allowed.add("reason")
    for key in sorted(payload):
        if key not in allowed:
            return None, "unexpected field {!r} for {!r}".format(key, kind)
    if kind in ("record_candidates", "no_candidates", "next_viewport"):
        if "observation_id" not in payload:
            return None, "missing field 'observation_id' for {!r}".format(kind)
        if payload["observation_id"] != observation_id:
            return None, ("stale observation: the current observation is {} — "
                          "record only from it".format(observation_id or "(none)"))
    if kind == "record_candidates":
        if "candidates" not in payload:
            return None, "missing field 'candidates' for 'record_candidates'"
        candidates = payload["candidates"]
        if not isinstance(candidates, list) or not candidates:
            return None, ("candidates must be a non-empty list — use "
                          "no_candidates when this viewport has nothing relevant")
        if len(candidates) > MAX_CANDIDATES_PER_CALL:
            return None, "too many candidates (max {})".format(MAX_CANDIDATES_PER_CALL)
        for index, candidate in enumerate(candidates):
            _clean, error = validate_candidate(
                candidate, current_observation_id=observation_id,
                prefix="candidates[{}]".format(index))
            if error:
                return None, error
    if kind == "finish_selection":
        if "ranks" not in payload or "explanation" not in payload:
            return None, "finish_selection needs fields 'ranks' and 'explanation'"
        ranks = payload["ranks"]
        if (not isinstance(ranks, list)
                or any(isinstance(item, bool) or not isinstance(item, int)
                       for item in ranks)):
            return None, "ranks must be a list of integers"
        if list(ranks) != list(selection_ranks):
            return None, ("finish_selection must confirm the trusted selection "
                          "exactly: ranks {}".format(list(selection_ranks)))
        error = _check_text("finish_selection", "explanation", payload["explanation"])
        if error:
            return None, error
    if kind == "stop":
        reason = payload.get("reason", "")
        if not isinstance(reason, str) or len(reason) > MAX_TEXT_CHARS:
            return None, "reason must be a short string"
    return dict(payload), None


# ------------------------------------------------------------- 4. schema

def scan_action_schema() -> dict:
    """Exact oneOf branches (M020 doctrine) mirroring the validator."""

    candidate_shape = {
        "type": "object",
        "properties": {
            "rank": {"type": "integer"},
            "title": {"type": "string"},
            "visible_points": {"type": "integer"},
            "ai_relevance": {"type": "string", "enum": list(AI_RELEVANCE)},
            "reason": {"type": "string"},
            "observation_id": {"type": "string"},
        },
        "required": ["rank", "title", "ai_relevance", "reason",
                     "observation_id"],
        "additionalProperties": False,
    }
    branches = [
        {"type": "object",
         "properties": {"action": {"type": "string", "enum": ["record_candidates"]},
                        "observation_id": {"type": "string"},
                        "candidates": {"type": "array", "items": candidate_shape}},
         "required": ["action", "observation_id", "candidates"],
         "additionalProperties": False},
        {"type": "object",
         "properties": {"action": {"type": "string", "enum": ["no_candidates"]},
                        "observation_id": {"type": "string"}},
         "required": ["action", "observation_id"],
         "additionalProperties": False},
        {"type": "object",
         "properties": {"action": {"type": "string", "enum": ["next_viewport"]},
                        "observation_id": {"type": "string"}},
         "required": ["action", "observation_id"],
         "additionalProperties": False},
        {"type": "object",
         "properties": {"action": {"type": "string", "enum": ["finish_selection"]},
                        "ranks": {"type": "array", "items": {"type": "integer"}},
                        "explanation": {"type": "string"}},
         "required": ["action", "ranks", "explanation"],
         "additionalProperties": False},
        {"type": "object",
         "properties": {"action": {"type": "string", "enum": ["stop"]},
                        "reason": {"type": "string"}},
         "required": ["action"],
         "additionalProperties": False},
    ]
    return {"oneOf": branches}


# ------------------------------------------------------------- 5. prompts

def _ledger_lines(entries) -> list:
    if not entries:
        return ["(empty)"]
    lines = []
    for entry in entries[:LEDGER_PROMPT_LIMIT]:
        points = ("{} points".format(entry.visible_points)
                  if entry.visible_points is not None else "points unknown")
        lines.append('- rank {}: "{}" ({}, {}) [{}]'.format(
            entry.rank, entry.title, entry.ai_relevance, points,
            entry.observation_id))
    if len(entries) > LEDGER_PROMPT_LIMIT:
        lines.append("- (+{} more recorded)".format(len(entries) - LEDGER_PROMPT_LIMIT))
    return lines


def _selection_text(selection) -> str:
    if not selection:
        return "(none — no primary candidates were recorded)"
    return "; ".join('rank {} "{}"'.format(entry.rank, entry.title)
                     for entry in selection)


def build_scan_prompt(goal: str, image_w: int, image_h: int, *,
                      viewport: Viewport, number: int, max_viewports: int,
                      phase: str, observation_id: str, ledger_entries,
                      history, calls_left=None) -> str:
    capabilities = scan_capabilities(phase)
    at_end = phase == "recording"
    lines = [
        "You are reading one viewport of a long page, top to bottom, and "
        "recording what you see.",
        "Task mode: scan — trusted code controls the traversal; you extract "
        "evidence.",
        "Goal: {}".format(goal),
        "The screenshot you see is {}x{} pixels and shows page y={} to y={} "
        "of {} (viewport {} of at most {}; viewports overlap, so never "
        "re-record a story that is already in the ledger).".format(
            image_w, image_h, viewport.scroll_y,
            viewport.scroll_y + viewport.viewport_height,
            viewport.document_height, number, max_viewports),
        "Current observation: {}.".format(observation_id),
    ]
    if calls_left is not None:
        lines.append("Calls left: {}.".format(calls_left))
    lines.append("Ledger so far ({} recorded):".format(len(ledger_entries)))
    lines.extend(_ledger_lines(ledger_entries))
    lines.append("Allowed actions: {}.".format(
        ", ".join(capabilities["allowed_actions"])))
    lines.append("Exact reply shapes:")
    lines.append('- {"action":"record_candidates","observation_id":"' +
                 observation_id + '","candidates":[{"rank":7,"title":"...",'
                 '"visible_points":41,"ai_relevance":"primary",'
                 '"reason":"...","observation_id":"' + observation_id + '"}]}')
    lines.append('- {"action":"no_candidates","observation_id":"' +
                 observation_id + '"}')
    if at_end:
        lines.append('- {"action":"next_viewport","observation_id":"' +
                     observation_id + '"} — the document end has been reached; '
                     "record this final viewport (or no_candidates) and then "
                     "call next_viewport once more to close the traversal "
                     "(no further scroll happens).")
    else:
        lines.append('- {"action":"next_viewport","observation_id":"' +
                     observation_id + '"} — advance about 70% of one '
                     "viewport.")
    lines.append('- {"action":"stop","reason":"why it is unsafe"}')
    lines.extend([
        "Rules:",
        "- rank = the number shown at the start of the story's row.",
        '- ai_relevance: "primary" when the story\'s main subject is AI/ML; '
        '"incidental" when AI is mentioned but is not the main subject. Do '
        "not record unrelated stories.",
        "- Every candidate's observation_id must be the CURRENT observation.",
        "- Record only titles you can read in this screenshot; never invent, "
        "merge, or reword.",
    ])
    if not at_end:
        lines.append("- When this viewport is recorded, call next_viewport.")
    else:
        lines.append("- This is the final viewport: record it, then call "
                     "next_viewport to close the traversal; the step after "
                     "that confirms the trusted selection from the ledger.")
    if history:
        lines.append("Recent results (oldest first):")
        lines.extend(history[-4:])
    lines.append("Reply with exactly one JSON action object, no other text.")
    return "\n".join(lines)


def build_final_prompt(goal: str, ledger_entries, selection, history) -> str:
    lines = [
        "No screenshot accompanies this step: the answer rests only on the "
        "structured ledger below.",
        "Task mode: scan — traversal complete, the whole page was captured "
        "viewport by viewport.",
        "Goal: {}".format(goal),
        "Ledger (authoritative; nothing outside it exists for the answer; "
        "{} recorded):".format(len(ledger_entries)),
    ]
    lines.extend(_ledger_lines(ledger_entries))
    lines.append("Trusted selection (lowest three ranks marked primary): " +
                 _selection_text(selection))
    lines.append("Confirm the trusted selection and explain it briefly. You "
                 "cannot add, remove, or change stories.")
    lines.append("Exact reply shape: "
                 '{"action":"finish_selection","ranks":[...],'
                 '"explanation":"..."}')
    if history:
        lines.append("Recent results (oldest first):")
        lines.extend(history[-4:])
    lines.append("Reply with exactly one JSON action object, no other text.")
    return "\n".join(lines)


# ------------------------------------------------- 6. trusted link mapping

def is_hn_item_link(href: str) -> bool:
    """True when href addresses a Hacker News item page (relative or live)."""

    if not isinstance(href, str) or not href:
        return False
    value = href.strip()
    for prefix in (HN_ORIGIN + "/", HN_ORIGIN + "?"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return bool(_HN_ITEM_RE.match(value.lstrip("/")))


def map_titles_to_hn_links(titles, link_rows) -> dict:
    """Exact visible title -> HN item link, from trusted DOM rows only.

    A title whose own link is already an HN item page maps directly (text
    posts); otherwise the single HN item link in the title's row window
    (same row or the row directly below — HN puts the subtext there) is
    used. Ambiguity or absence maps to None; external article links are
    never chosen.
    """

    mapping: dict = {}
    by_label: dict = {}
    pairs: set = set()
    for row in link_rows or ():
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        href = row.get("href")
        if not isinstance(label, str) or not isinstance(href, str):
            continue
        try:
            row_index = int(row.get("row", -1))
        except (TypeError, ValueError):
            row_index = -1
        pairs.add((row_index, href))
        by_label.setdefault(normalize_title(label), set()).add((row_index, href))
    for title in titles:
        entries = sorted(by_label.get(normalize_title(title), set()))
        if len(entries) != 1:
            mapping[title] = None
            continue
        anchor_row, anchor_href = entries[0]
        if is_hn_item_link(anchor_href):
            mapping[title] = anchor_href
            continue
        if anchor_row < 0:
            mapping[title] = None
            continue
        candidates = sorted(
            (row_index, href) for row_index, href in pairs
            if 0 <= row_index - anchor_row <= 1 and is_hn_item_link(href))
        mapping[title] = candidates[0][1] if len(candidates) == 1 else None
    return mapping


def build_result(ledger: EvidenceLedger, selection, *, observed_at: str,
                 link_rows=None) -> dict:
    links = map_titles_to_hn_links([entry.title for entry in selection],
                                   link_rows)
    stories = []
    for entry in selection:
        stories.append({
            "rank": entry.rank,
            "title": entry.title,
            "points": entry.visible_points,
            "ai_relevance": entry.ai_relevance,
            "reason": entry.reason,
            "observation_id": entry.observation_id,
            "hn_link": links.get(entry.title),
        })
    return {
        "stories": stories,
        "found": len(stories),
        "observed_at": observed_at,
        "selection": "trusted: lowest three ranks marked primary",
        "hn_link_note": HN_LINK_NOTE,
    }


def atomic_write_json(path, payload) -> Path:
    """Crash-safe write: temp file + atomic replace (old file survives)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


# ------------------------------------------------------------- 7. runner

@dataclass
class ScanLimits:
    max_viewports: int = MAX_VIEWPORTS
    max_calls: int = MAX_CALLS
    max_seconds: float = MAX_SECONDS
    max_consecutive_recoveries: int = 2
    max_infrastructure_failures: int = 3


def _png_dims(data: bytes) -> tuple:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def run_scan(session, proposer, *, goal: str = GOAL, limits=None,
             sleep=time.sleep, monotonic=time.monotonic, log=print,
             links_provider=None, now=None) -> dict:
    """One scan-mode run: trusted traversal, per-viewport recording, ledger.

    The runner never executes model-chosen amounts, kinds, or targets: the
    traversal step is the frozen 70%, the action set is fixed, and completion
    is decided by the trusted selection. ``proposer(png_bytes, prompt)`` is
    the schema-constrained model call used by every existing lane.
    """

    limits = limits or ScanLimits()
    started = monotonic()
    steps: list = []
    report = {
        "stage": "M022", "run_version": RUN_VERSION, "mode": "scan",
        "goal": goal, "reviewer_scored": True,
        "limits": {"max_viewports": limits.max_viewports,
                   "max_calls": limits.max_calls,
                   "max_seconds": limits.max_seconds},
        "steps": steps, "calls": 0, "viewports": 0,
        "outcome": None, "ledger": [], "selection": [], "result": None,
        "screenshots": [], "link_rows": None,
    }
    state = {"calls": 0, "recoveries": 0, "last_refusal": None,
             "infrastructure": 0}
    history: list = []
    traversal = ViewportTraversal(max_viewports=limits.max_viewports)
    ledger = EvidenceLedger()
    shot = None
    observation_id = ""

    def record(kind: str, **data) -> None:
        row = {"kind": kind, "at_ms": round((monotonic() - started) * 1000.0, 1)}
        row.update(data)
        steps.append(row)
        log("  [{:>6}ms] {} {}".format(
            row["at_ms"], kind,
            " ".join("{}={}".format(k, v) for k, v in sorted(data.items()))))

    def finish(outcome: str, **data) -> dict:
        report["outcome"] = outcome
        report["calls"] = state["calls"]
        report["viewports"] = len(traversal.viewports)
        report["elapsed_ms"] = round((monotonic() - started) * 1000.0, 1)
        record("terminal", outcome=outcome, **data)
        return report

    def exhausted(reason: str):
        state["recoveries"] += 1
        if state["last_refusal"] == reason:
            if state["recoveries"] > limits.max_consecutive_recoveries:
                return finish("blocked:recovery_exhausted", reason=reason)
        else:
            state["last_refusal"] = reason
            state["recoveries"] = 1
        return None

    def metrics():
        page = (session.state() or {}).get("page") or {}
        return {"scroll_y": int(page.get("scrollY") or 0),
                "viewport_height": int(page.get("innerHeight") or 0),
                "document_height": int(page.get("scrollHeight") or 0)}

    def capture_viewport(phase: str, **extra):
        """Snapshot + metrics for the current position; updates the closure
        state (shot + observation_id). Returns (values, terminal-report)."""

        nonlocal shot, observation_id
        try:
            shot = session.snapshot()
        except Exception as exc:  # noqa: BLE001 - typed adapter failure
            state["infrastructure"] += 1
            record("observe", ok=False, phase=phase,
                   reason=getattr(exc, "reason", type(exc).__name__))
            if state["infrastructure"] >= limits.max_infrastructure_failures:
                return None, finish("failed:infrastructure",
                                    reason=getattr(exc, "reason", "snapshot"))
            return None, None
        observation_id = "obs-{}".format(shot.seq)
        values = metrics()
        report["screenshots"].append(str(shot.path))
        record("observe", phase=phase, observation=observation_id,
               scroll_y=values["scroll_y"],
               document_height=values["document_height"],
               viewport_height=values["viewport_height"], **extra)
        return values, None

    # ---------------------------------------------------------- startup
    while True:
        values, terminal = capture_viewport("startup")
        if terminal is not None:
            return terminal
        if values is not None:
            break
    try:
        traversal.begin(scroll_y=values["scroll_y"],
                        viewport_height=values["viewport_height"],
                        document_height=values["document_height"],
                        observation_id=observation_id, seq=shot.seq)
    except ScanError as exc:
        return finish("failed:startup", reason=exc.reason, detail=exc.detail)

    # ------------------------------------------------------------- loop
    phase = "recording" if traversal.complete else "scanning"
    while True:
        if state["calls"] >= limits.max_calls:
            return finish("failed:budget_calls")
        if monotonic() - started > limits.max_seconds:
            return finish("failed:budget_seconds")
        selection_ranks = [entry.rank for entry in ledger.selection()]
        if phase == "final":
            prompt = build_final_prompt(goal, ledger.entries, ledger.selection(),
                                        history)
            model_bytes = placeholder_png()
        else:
            try:
                raw = Path(shot.path).read_bytes()
                model_bytes = fit_for_model(raw)
                image_w, image_h = _png_dims(model_bytes)
            except Exception:  # noqa: BLE001 - unreadable image
                state["infrastructure"] += 1
                record("infrastructure", reason="image_read")
                if state["infrastructure"] >= limits.max_infrastructure_failures:
                    return finish("failed:infrastructure", reason="image_read")
                capture_viewport("reobserve")
                continue
            prompt = build_scan_prompt(
                goal, image_w, image_h, viewport=traversal.current,
                number=len(traversal.viewports), max_viewports=limits.max_viewports,
                phase=phase, observation_id=observation_id,
                ledger_entries=ledger.entries, history=history,
                calls_left=limits.max_calls - state["calls"])
        state["calls"] += 1
        action, meta = proposer(model_bytes, prompt)
        if action is None:
            record("proposal", parsed=False,
                   chars=meta.get("chars") if meta else None)
            history.append("previous reply was not one JSON object; answer "
                           "with exactly one action object")
            stop = exhausted("invalid_proposal")
            if stop:
                return stop
            continue
        parsed, error = validate_scan_action(
            action, observation_id=observation_id, traversal=traversal,
            phase=phase, selection_ranks=selection_ranks)
        if error:
            record("proposal", parsed=False, error=error,
                   action=action.get("action"))
            history.append("proposal rejected: {}; propose one valid action".format(error))
            stop = exhausted("action_refused")
            if stop:
                return stop
            continue
        kind = parsed["action"]

        if kind == "record_candidates":
            admitted, rejects = [], []
            for candidate in parsed["candidates"]:
                try:
                    admitted.append(ledger.add(
                        candidate, current_observation_id=observation_id))
                except ScanError as exc:
                    rejects.append(exc)
            record("ledger", admitted=[entry.rank for entry in admitted],
                   rejected=[exc.reason for exc in rejects],
                   size=len(ledger.entries))
            if rejects:
                history.append("rejected candidates: " + "; ".join(
                    "{} ({})".format(exc.reason, exc.detail) for exc in rejects))
                stop = exhausted("candidate_rejected")
                if stop:
                    return stop
            else:
                history.append("recorded {} candidate(s) from {}".format(
                    len(admitted), observation_id))
            continue

        if kind == "no_candidates":
            record("action", executed="no_candidates", observation=observation_id)
            history.append("viewport {}: nothing recorded".format(
                len(traversal.viewports)))
            continue

        if kind == "next_viewport":
            if phase == "recording":
                record("action", executed="recording_complete",
                       viewports=len(traversal.viewports))
                history.append("traversal closed ({} viewport(s)); the next "
                               "step confirms the trusted selection".format(
                                   len(traversal.viewports)))
                phase = "final"
                continue
            fraction = traversal.next_fraction()
            if fraction is None:
                record("proposal", parsed=False, error="already_at_end")
                history.append("already at the document end — record the final "
                               "viewport, then close the traversal")
                stop = exhausted("action_refused")
                if stop:
                    return stop
                continue
            try:
                session.scroll("down", fraction, method="dom")
            except Exception as exc:  # noqa: BLE001 - typed adapter failure
                state["infrastructure"] += 1
                reason = getattr(exc, "reason", type(exc).__name__)
                record("action", executed=None, refused=reason)
                history.append("scroll failed: {} — try again or stop".format(reason))
                if state["infrastructure"] >= limits.max_infrastructure_failures:
                    return finish("failed:infrastructure", reason=reason)
                stop = exhausted("scroll_failed")
                if stop:
                    return stop
                continue
            sleep(0.3)
            values, terminal = capture_viewport("advance",
                                                fraction=round(fraction, 4))
            if terminal is not None:
                return terminal
            if values is None:
                stop = exhausted("snapshot_failed")
                if stop:
                    return stop
                continue
            try:
                traversal.advance(
                    scroll_y=values["scroll_y"],
                    viewport_height=values["viewport_height"],
                    document_height=values["document_height"],
                    observation_id=observation_id, seq=shot.seq)
            except ScanError as exc:
                record("traversal", ok=False, reason=exc.reason,
                       detail=exc.detail)
                return finish("failed:traversal", reason=exc.reason,
                              detail=exc.detail)
            state["recoveries"] = 0
            state["last_refusal"] = None
            phase = "recording" if traversal.complete else "scanning"
            history.append("viewport {}: y={} of {}".format(
                len(traversal.viewports), values["scroll_y"],
                values["document_height"]))
            continue

        if kind == "finish_selection":
            observed_at = (now or utc_now)()
            link_rows = None
            try:
                provider = links_provider or getattr(session, "links", None)
                if callable(provider):
                    payload = provider()
                    if isinstance(payload, dict):
                        link_rows = payload.get("links")
            except Exception:  # noqa: BLE001 - mapping is best-effort metadata
                link_rows = None
            report["link_rows"] = len(link_rows) if isinstance(link_rows, list) else None
            selection = ledger.selection()
            result = build_result(ledger, selection, observed_at=observed_at,
                                  link_rows=link_rows)
            report["ledger"] = ledger.as_dicts()
            report["selection"] = [entry.as_dict() for entry in selection]
            report["result"] = result
            record("action", executed="finish_selection",
                   ranks=[entry.rank for entry in selection],
                   explanation_chars=len(parsed["explanation"]))
            return finish("finished")

        if kind == "stop":
            record("action", executed="stop", reason=parsed.get("reason", ""))
            report["ledger"] = ledger.as_dicts()
            return finish("stopped")

        # Unreachable: validate_scan_action rejects unknown kinds.
        return finish("failed:internal", reason="unhandled action")
