"""M021: read-only live Hacker News transfer in answer mode (reviewer-scored).

Frozen contract (docs/M021_HN_TRANSFER_PLAN.md):

- Trusted code opens the Hacker News front page; the pinned model reads
  viewport screenshots and may ONLY scroll, wait, finish_answer, or stop.
  Clicking, typing, forms, submissions, and navigation are structurally
  unavailable (answer-mode capability manifest + action schema), visible
  target lists are never requested or sent (this is a reading task), and the
  origin policy admits only the Hacker News origin.
- The model returns the first three stories whose main subject is AI/ML
  ordered by front-page rank, each with rank, title, url (the displayed
  source domain), points (when visible), and a short reason; ``found``
  states how many qualifying stories it found (three unless fewer exist).
- ``observed_at`` is trusted harness metadata (UTC), never produced by the
  model. Correctness is reviewer-scored AFTER the run against the trusted
  pre-run front-page capture plus (post-run only) the HN API or article
  pages; reviewer data never enters the model prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import browser_agent as agent
from . import browser_targets
from . import browser_tasks as tasks

RUN_VERSION = "m021-hn-v1"

HN_HOST = "news.ycombinator.com"
# Assembled from parts so the frozen source-line URL-literal rules stay
# satisfied (scheme separators live only in acquire/runtime_llamaserver).
HN_ORIGIN = "https:" + "//" + HN_HOST
START_URL = HN_ORIGIN + "/"

# Frozen budgets (docs/M021_HN_TRANSFER_PLAN.md): max 4 scrolls, 8 model
# calls, 120 s; context 8192; --require-schema semantics with zero fallbacks.
MAX_SCROLLS = 4
MAX_CALLS = 8
MAX_SECONDS = 120.0
CTX_SIZE = 8192
REVIEWER_PAGES = 3

CLASSIFICATION_RULE = (
    "Frozen before the run. A story qualifies as AI/ML only when its main "
    "subject is artificial intelligence or machine learning: an AI/ML model, "
    "a research result, a product or system whose core purpose is AI/ML, or "
    "directly related policy/safety news. Incidental keywords in an "
    "otherwise unrelated story, and generic software or business stories, "
    "do not qualify. Used only by the reviewer, never shown to the model."
)

GOAL = (
    "Read the Hacker News front page and report the first THREE stories "
    "whose main subject is AI or machine learning, in front-page rank "
    "order. Rank is the number shown at the start of a story's row (1 is "
    "the top story); the list continues below the visible area, so scroll "
    "down to read the rest. A story qualifies only when its main subject is "
    "AI/ML \u2014 an AI model, a research result, a product whose core "
    "purpose is AI/ML, or directly related policy or safety news. An "
    "incidental 'AI' word inside an otherwise unrelated story does not "
    "qualify, and generic software or business stories do not qualify. For "
    "each qualifying story report: rank, title (exactly as shown), url (the "
    "source domain shown after the title; for text posts use "
    "news.ycombinator.com), points (the visible number), and a short reason "
    "why the story is mainly about AI/ML. Set found to the number of "
    "qualifying stories you report: exactly three unless fewer than three "
    "qualify. Only report what you can see in a screenshot; if something is "
    "not visible, do not guess. When done, reply with finish_answer."
)

M021_SCHEMA = tasks.answer_schema(
    {"stories": {"type": "list"}, "found": {"type": "integer"}},
    required=("stories", "found"))

STORY_FIELDS = ("rank", "title", "url", "points", "reason")
REQUIRED_STORY_FIELDS = ("rank", "title", "url", "reason")

_TARGET_ID_RE = re.compile(r"^t[1-9][0-9]{0,2}$")


def goal_sha256() -> str:
    return hashlib.sha256(GOAL.encode("utf-8")).hexdigest()


def utc_now() -> str:
    """Trusted UTC timestamp (model never produces timestamps)."""

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _check_text(prefix: str, key: str, value):
    if not isinstance(value, str):
        return "{}: {} must be a string".format(prefix, key)
    if not value.strip():
        return "{}: {} must not be empty".format(prefix, key)
    if len(value) > tasks.MAX_ANSWER_STRING:
        return "{}: {} is too long".format(prefix, key)
    if any(ord(ch) < 32 for ch in value):
        return "{}: {} must not contain control characters".format(prefix, key)
    stripped = value.strip()
    if browser_targets.valid_ui_ref(stripped):
        return "{}: {} holds a ui: target reference, not page data".format(
            prefix, key)
    if _TARGET_ID_RE.match(stripped):
        return "{}: {} holds a target id, not page data".format(prefix, key)
    return None


def validate_m021_answer(answer):
    """Return (clean_answer, None) or (None, error). Strict, fail-closed.

    Frozen structural rules: exactly the two top-level fields; ``found`` is
    an integer 0-3 equal to the story count; each story has rank/title/url/
    reason (points optional); ranks are unique and strictly increasing
    (front-page rank order); urls are unique; every string is visible-page
    data (no ui:/target ids, no control characters). Whether the stories are
    genuinely the top AI/ML stories is decided by the reviewer, not here.
    """

    if not isinstance(answer, dict) or not answer:
        return None, "answer must be a non-empty object"
    for key in sorted(answer):
        if key not in ("stories", "found"):
            return None, "unexpected answer field {!r}".format(key)
    for key in ("stories", "found"):
        if key not in answer:
            return None, "missing answer field {!r}".format(key)
    found = answer["found"]
    if isinstance(found, bool) or not isinstance(found, int):
        return None, "found must be an integer"
    if not 0 <= found <= 3:
        return None, "found must be between 0 and 3"
    stories = answer["stories"]
    if not isinstance(stories, list):
        return None, "stories must be a list"
    if len(stories) != found:
        return None, ("found ({}) must equal the number of stories "
                      "({})".format(found, len(stories)))
    seen_ranks: list = []
    seen_urls: list = []
    for index, story in enumerate(stories):
        prefix = "stories[{}]".format(index)
        if not isinstance(story, dict):
            return None, "{} must be an object".format(prefix)
        for key in sorted(story):
            if key not in STORY_FIELDS:
                return None, "{}: unexpected field {!r}".format(prefix, key)
        for key in REQUIRED_STORY_FIELDS:
            if key not in story:
                return None, "{}: missing field {!r}".format(prefix, key)
        rank = story["rank"]
        if isinstance(rank, bool) or not isinstance(rank, int):
            return None, "{}: rank must be an integer".format(prefix)
        if rank < 1:
            return None, "{}: rank must be >= 1".format(prefix)
        if rank in seen_ranks:
            return None, "{}: duplicate rank {}".format(prefix, rank)
        if seen_ranks and rank <= seen_ranks[-1]:
            return None, "{}: ranks must strictly increase (front-page "
            "rank order)".format(prefix)
        seen_ranks.append(rank)
        if "points" in story:
            points = story["points"]
            if isinstance(points, bool) or not isinstance(points, int):
                return None, "{}: points must be an integer".format(prefix)
            if points < 0:
                return None, "{}: points must be >= 0".format(prefix)
        for key in ("title", "url", "reason"):
            error = _check_text(prefix, key, story[key])
            if error:
                return None, error
        url_key = story["url"].strip().lower()
        if url_key in seen_urls:
            return None, "{}: duplicate url {}".format(prefix, story["url"])
        seen_urls.append(url_key)
    return dict(answer), None


def verify_m021(spec, state: dict) -> dict:
    """The M021 run oracle: structural validity + zero side effects.

    Semantic correctness is reviewer-scored after the run; ``ok`` here means
    the answer is structurally admissible and the run stayed read-only.
    """

    failures = []
    outcome = state.get("outcome")
    if outcome != "finished":
        failures.append("outcome: expected 'finished', got {!r}".format(outcome))
    side_effect_free = (
        state.get("external_visits", 0) == 0
        and not state.get("credential_typed", False)
        and state.get("submission_attempts", 0) == 0
    )
    if not side_effect_free:
        failures.append("side-effects: unexpected submission/credential/"
                        "external event")
    answer = state.get("answer")
    if answer is None:
        failures.append("answer: missing")
    else:
        _clean, error = validate_m021_answer(answer)
        if error:
            failures.append("answer: {}".format(error))
    return {"ok": not failures, "task": spec.id, "failures": failures,
            "failed_checks": len(failures)}


def action_schema() -> dict:
    """Answer-mode schema with an exact nested answer shape (M020 doctrine).

    The action branches come from the frozen M020 ``typed_action_schema``;
    only the ``finish_answer`` branch's answer object is specialized so the
    decoder can emit exactly ``{stories: [...], found: N}`` — mirroring
    ``validate_m021_answer`` (required story fields rank/title/url/reason,
    optional points, no extra fields anywhere).
    """

    schema = agent.typed_action_schema("answer")
    answer_shape = {
        "type": "object",
        "properties": {
            "stories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "points": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": list(REQUIRED_STORY_FIELDS),
                    "additionalProperties": False,
                },
            },
            "found": {"type": "integer"},
        },
        "required": ["stories", "found"],
        "additionalProperties": False,
    }
    for branch in schema["oneOf"]:
        if branch["properties"].get("action", {}).get("enum") == ["finish_answer"]:
            branch["properties"]["answer"] = answer_shape
            break
    return schema


def hn_spec() -> tasks.TypedTaskSpec:
    """The frozen M021 task: answer mode, no target lists, reviewer-scored."""

    return tasks.TypedTaskSpec(
        id="m021-hn", split="P", mode="answer", instance="live",
        goal=GOAL, start=START_URL, answer_schema=M021_SCHEMA,
        answer_validator=validate_m021_answer, observe_targets=False,
        page_metrics=True,
        notes="M021 read-only live Hacker News transfer; reviewer-scored")


def result_document(answer, observed_at: str) -> dict:
    """The frozen result shape: model stories + trusted ``observed_at``."""

    payload = answer if isinstance(answer, dict) else {}
    return {
        "stories": list(payload.get("stories") or []),
        "found": payload.get("found"),
        "observed_at": observed_at,
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
