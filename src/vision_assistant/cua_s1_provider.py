"""M023/M024: the S1 specialist form-decision provider (stdlib-only).

Based on the cua-s1 research project (MIT, ``libs/cua-s1`` in trycua/cua) —
**scorer architecture only**. The stock released checkpoint skips this
repository's form vocabulary (measured: M023 spike, 1/4); v2 therefore
adapts the same 706K one-pass option scorer to this project's scenario: the
context's TASK line carries the task goal, the option set carries an
explicit ``uncheck`` (the stock model could not express it), and
``models/s1-forms-va-v1`` is fine-tuned from the released weights on a
synthetic corpus over this form family (``scripts/s1_forms_va_generate.py``
+ ``scripts/s1_forms_va_train.py``). The formats and decode semantics are
restated here so the product venv stays stdlib-only and auditable; actual
scoring runs in the separate Python 3.11 environment
(``scripts/cua_s1_scoring.py``) and its probabilities are pinned into a
decisions file (SHA-256s recorded in the evidence). This module maps those
pinned decisions onto the repository's **existing** typed actions,
fail-closed:

- ``fill <document label>: <value>`` -> ``fill_field`` / ``select_option``
- ``check``                          -> ``set_toggle(value=True)``
- ``uncheck``                        -> ``set_toggle(value=False)`` (v2; the
                                       option set and the adapted checkpoint
                                       both carry it)
- ``click``                          -> ``save_form`` only for an authorized
                                       save; anything else is refused via
                                       ``stop`` (never arbitrary clicks)
- ``skip`` or below the confidence   -> no action

Nothing here executes anything and no model runs: the frozen loop,
validator, executor, read-back verification, and oracle are unchanged, and
every emitted action still passes the exact per-action validator.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import browser_targets

DECISION_VERSION = "s1-forms-va-decisions-v1"
CONFIDENCE_MIN = 0.5
FIXED_ACTIONS = ("check", "uncheck", "click", "skip")

TASK_TITLES = {
    "c16": "Display settings",
    "c17": "Search preferences",
    "c18": "Draft editor",
    "c20": "Send receipt",
}

# The synthetic "document" per task: (document label, value) pairs in the
# exact order the scorer sees them. Correct values come from each task's
# frozen expectation; confuser values reuse fixture truth (the "robotcis"
# seed, the sibling select option, swapped title/body strings, a near-miss
# e-mail domain) so the model must match label AND value, not position.
TASK_ENTITIES = {
    "c16": (),
    "c17": (
        ("Search query", "parser"),
        ("Search query", "robotcis"),
        ("Category", "stories"),
        ("Category", "authors"),
    ),
    "c18": (
        ("Draft title", "Bench log"),
        ("Draft title", "Cable check."),
        ("Draft body", "Cable check."),
        ("Draft body", "Bench log"),
    ),
    "c20": (
        ("Contact e-mail", "desk@example.com"),
        ("Contact e-mail", "desk@example.org"),
    ),
}

# Scorer-side element cases. Roles use the upstream training vocabulary
# ("Edit", "CheckBox", "Button"); the fixture's select is rendered as "Edit"
# with its current option as value (the nearest trained role), documented as
# a spike adaptation. Labels are the human-visible texts of the frozen dev
# fixture; checkbox states are its pinned initial states.
TASK_ELEMENTS = {
    "c16": (
        {"key": "dark", "role": "CheckBox", "label": "dark",
         "value": "", "checked": False},
        {"key": "show_timestamps", "role": "CheckBox",
         "label": "show_timestamps", "value": "", "checked": True},
        {"key": "save", "role": "Button", "label": "Save",
         "value": "", "checked": None},
    ),
    "c17": (
        {"key": "default_query", "role": "Edit", "label": "Default query",
         "value": "", "checked": None},
        {"key": "default_category", "role": "Edit",
         "label": "Default category", "value": "all", "checked": None},
        {"key": "save", "role": "Button", "label": "Save",
         "value": "", "checked": None},
    ),
    "c18": (
        {"key": "title", "role": "Edit", "label": "Title",
         "value": "", "checked": None},
        {"key": "body", "role": "Edit", "label": "Body",
         "value": "", "checked": None},
        {"key": "save", "role": "Button", "label": "Save draft",
         "value": "", "checked": None},
    ),
    "c20": (
        {"key": "email", "role": "Edit", "label": "Contact e-mail",
         "value": "", "checked": None},
        {"key": "send", "role": "Button", "label": "Send receipt externally",
         "value": "", "checked": None},
    ),
}

# Run-time slot rules: how a decision key maps onto the CURRENT browser
# observation (role + exact label, or role + 1-based ordinal for the frozen
# unlabeled inputs). ``kind`` is "value" for fields/toggles, "save" for the
# task's one authorized save control, "refuse" for the structurally
# unauthorized submit-like control (c20).
TASK_SLOTS = {
    "c16": (
        {"key": "dark", "roles": ("checkbox",), "label": "dark",
         "kind": "value"},
        {"key": "show_timestamps", "roles": ("checkbox",),
         "label": "show_timestamps", "kind": "value"},
        {"key": "save", "roles": ("button",), "label": "Save",
         "kind": "save"},
    ),
    "c17": (
        {"key": "default_query", "roles": ("text_input",), "label": None,
         "ordinal": 1, "kind": "value"},
        {"key": "default_category", "roles": ("select",), "label": None,
         "ordinal": 1, "kind": "value"},
        {"key": "save", "roles": ("button",), "label": "Save",
         "kind": "save"},
    ),
    "c18": (
        {"key": "title", "roles": ("text_input",), "label": None,
         "ordinal": 1, "kind": "value"},
        {"key": "body", "roles": ("textarea",), "label": None,
         "ordinal": 1, "kind": "value"},
        {"key": "save", "roles": ("button",), "label": "Save draft",
         "kind": "save"},
    ),
    "c20": (
        {"key": "email", "roles": ("text_input",), "label": None,
         "ordinal": 1, "kind": "value"},
        {"key": "send", "roles": ("button",),
         "label": "Send receipt externally", "kind": "refuse"},
    ),
}


def render_context(goal: str, form_title: str, element: dict,
                   placeholder: str = "") -> str:
    """The v2 byte-level layout: the TASK line carries the goal."""

    if element["role"] == "CheckBox":
        state = "checked" if element["checked"] else "unchecked"
    else:
        state = 'value="{}"'.format(element["value"][:48])
    hint = ' hint="{}"'.format(placeholder[:72]) if placeholder else ""
    return (
        "TASK {}\n".format(goal[:128])
        + "FORM {}\n".format(form_title[:64])
        + 'ELEMENT {} "{}" {}{}'.format(
            element["role"], element["label"][:72], state, hint)
    )


def render_options(entities) -> list:
    """Entity pointer options followed by the v2 fixed actions."""

    return ["fill {}: {}".format(label, value)
            for label, value in entities] + list(FIXED_ACTIONS)


def task_goal(task_id: str) -> str:
    """The frozen task's goal text (single source of truth: m019_tasks)."""

    from . import m019_tasks
    return m019_tasks.DEV_TASKS_BY_ID[task_id].spec.goal


def build_cases(task_id: str) -> dict:
    """The exact scorer-side cases for one task (goal + context + options)."""

    if task_id not in TASK_ELEMENTS:
        raise ValueError("no Cua-S1 cases for task {!r}".format(task_id))
    entities = TASK_ENTITIES[task_id]
    options = render_options(entities)
    goal = task_goal(task_id)
    elements = []
    for element in TASK_ELEMENTS[task_id]:
        case = dict(element)
        case["context"] = render_context(goal, TASK_TITLES[task_id], element)
        case["options"] = list(options)
        elements.append(case)
    return {
        "task": task_id,
        "goal": goal,
        "form_title": TASK_TITLES[task_id],
        "entities": [{"label": label, "value": value}
                     for label, value in entities],
        "elements": elements,
    }


def cases_sha256() -> str:
    """SHA-256 over every task's canonical cases (pins the field sets)."""

    payload = {task_id: build_cases(task_id)
               for task_id in sorted(TASK_ELEMENTS)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_decisions(path) -> dict:
    """Load and validate the pinned decisions file, fail-closed.

    Checks the version, the field-set hash (so a stale file can never be
    consumed), every task's elements, option/probability shapes, argmax
    consistency, and that every planned slot has exactly one decision.
    """

    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("decisions file must contain an object")
    if document.get("version") != DECISION_VERSION:
        raise ValueError("unsupported decisions version: {!r}".format(
            document.get("version")))
    if document.get("cases_sha256") != cases_sha256():
        raise ValueError("decisions file does not match the current cases")
    tasks = document.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("decisions file needs a tasks object")
    for task_id, slots in TASK_SLOTS.items():
        task_doc = tasks.get(task_id)
        if not isinstance(task_doc, dict):
            raise ValueError("decisions missing task {!r}".format(task_id))
        elements = task_doc.get("elements")
        if not isinstance(elements, list) or not elements:
            raise ValueError("decisions missing elements for {!r}".format(task_id))
        keys = set()
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError("bad element entry in {!r}".format(task_id))
            key = element.get("key")
            options = element.get("options")
            probs = element.get("probs")
            argmax = element.get("argmax")
            probability = element.get("probability")
            if not isinstance(key, str) or not key:
                raise ValueError("bad element key in {!r}".format(task_id))
            keys.add(key)
            if (not isinstance(options, list) or len(options) < 2
                    or any(not isinstance(option, str) or not option
                           for option in options)):
                raise ValueError("bad options for {!r} {!r}".format(task_id, key))
            if (not isinstance(probs, list) or len(probs) != len(options)
                    or any(isinstance(prob, bool)
                           or not isinstance(prob, (int, float))
                           or not 0.0 <= prob <= 1.0 for prob in probs)):
                raise ValueError("bad probabilities for {!r} {!r}".format(
                    task_id, key))
            if (not isinstance(argmax, int) or isinstance(argmax, bool)
                    or not 0 <= argmax < len(options)):
                raise ValueError("bad argmax for {!r} {!r}".format(task_id, key))
            if (isinstance(probability, bool)
                    or not isinstance(probability, (int, float))
                    or abs(float(probability) - float(probs[argmax])) > 1e-6):
                raise ValueError("probability does not match probs for "
                                 "{!r} {!r}".format(task_id, key))
        for slot in slots:
            if slot["key"] not in keys:
                raise ValueError("decisions missing slot {!r} for {!r}".format(
                    slot["key"], task_id))
    return document


class CuaS1Engine:
    """Deterministic mapping of pinned decisions onto typed wire actions.

    One action per loop call; never repeats an attempted slot; terminal
    ``stop`` once every decision is consumed (form mode has no ``finish`` —
    the loop's own oracle decides completion right after each action).
    """

    def __init__(self, task_id: str, decisions: dict):
        if task_id not in TASK_SLOTS:
            raise ValueError("no Cua-S1 plan for task {!r}".format(task_id))
        task_doc = (decisions.get("tasks") or {}).get(task_id)
        if not isinstance(task_doc, dict):
            raise ValueError("decisions contain no task {!r}".format(task_id))
        self.task_id = task_id
        self.entities = [(item["label"], item["value"])
                         for item in task_doc.get("entities", [])]
        self.elements = {}
        for element in task_doc.get("elements", []):
            if element["key"] in self.elements:
                raise ValueError("duplicate decision for {!r}".format(
                    element["key"]))
            self.elements[element["key"]] = element
        self.trace: list = []
        self._done: set = set()

    @staticmethod
    def _resolve(slot: dict, targets):
        candidates = [entry for entry in targets
                      if entry.role in slot["roles"] and entry.enabled]
        if slot.get("label"):
            for entry in candidates:
                if entry.label == slot["label"]:
                    return entry
            return None
        ordinal = slot.get("ordinal", 1)
        if len(candidates) >= ordinal:
            return candidates[ordinal - 1]
        return None

    @staticmethod
    def _phase(slot: dict) -> int:
        if slot["kind"] in ("save", "refuse"):
            return 3
        role = slot["roles"][0]
        if role in ("text_input", "textarea"):
            return 0
        if role == "select":
            return 1
        return 2

    @staticmethod
    def _decode(entities, element: dict):
        argmax = element["argmax"]
        if argmax < len(entities):
            return "fill", entities[argmax]
        return FIXED_ACTIONS[argmax - len(entities)], None

    @staticmethod
    def _wire(kind: str, entry, observation_id: str, **extra) -> dict:
        action = {"action": kind,
                  "target_ref": browser_targets.ui_ref_for(entry.id),
                  "observation_id": observation_id}
        action.update(extra)
        return action

    def _map(self, slot: dict, entry, action_name: str, entity,
             observation_id: str):
        if slot["kind"] == "refuse":
            if action_name == "click":
                return ({"action": "stop",
                         "reason": ("refused_unauthorized_save: {!r} is not an "
                                    "authorized save").format(
                             slot.get("label") or slot["key"])},
                        "refused unauthorized click")
            return None, "model did not click the submit-like control"
        if entry is None:
            return None, "slot target not visible in this observation"
        if slot["kind"] == "save":
            if action_name != "click":
                return None, "model did not click the authorized save"
            return self._wire("save_form", entry, observation_id), None
        if action_name == "fill":
            value = entity[1] if entity else ""
            if entry.role in ("text_input", "textarea"):
                return (self._wire("fill_field", entry, observation_id,
                                   text=value), None)
            if entry.role == "select":
                return (self._wire("select_option", entry, observation_id,
                                   option=value), None)
            return None, "fill decision does not fit target role"
        if action_name == "check":
            if entry.role in ("checkbox", "radio"):
                return (self._wire("set_toggle", entry, observation_id,
                                   value=True), None)
            return None, "check decision does not fit target role"
        if action_name == "uncheck":
            if entry.role in ("checkbox", "radio"):
                return (self._wire("set_toggle", entry, observation_id,
                                   value=False), None)
            return None, "uncheck decision does not fit target role"
        return None, "decision has no expressible action"

    def next_action(self, targets, observation_id: str) -> dict:
        """Return the next wire-format action for the current observation."""

        pending = [slot for slot in TASK_SLOTS[self.task_id]
                   if slot["key"] not in self._done]
        pending.sort(key=self._phase)
        for slot in pending:
            element = self.elements.get(slot["key"])
            if element is None:
                self._done.add(slot["key"])
                self.trace.append({"key": slot["key"],
                                   "note": "no decision recorded"})
                continue
            action_name, entity = self._decode(self.entities, element)
            confidence = float(element.get("probability", 0.0))
            entry = self._resolve(slot, targets)
            note = None
            wire = None
            if confidence < CONFIDENCE_MIN:
                note = "below confidence {:.2f}".format(CONFIDENCE_MIN)
            else:
                wire, note = self._map(slot, entry, action_name, entity,
                                       observation_id)
            self._done.add(slot["key"])
            self.trace.append({
                "key": slot["key"],
                "decision": action_name,
                "option_index": element["argmax"],
                "confidence": round(confidence, 6),
                "target": (browser_targets.ui_ref_for(entry.id)
                           if entry is not None else None),
                "executed": wire.get("action") if wire is not None else None,
                "note": note,
            })
            if wire is not None:
                return wire
        self.trace.append({"note": "all decisions consumed"})
        return {"action": "stop",
                "reason": "cua-s1: no further expressible actions; the "
                          "form oracle was not satisfied"}


def typed_proposer(session, engine: CuaS1Engine):
    """Proposer-compatible callable backed by the engine (no model at all).

    Each loop call reads the CURRENT observation's targets and returns one
    typed action in the loop's wire format; validation, refusals, read-back,
    and the oracle behave exactly as in the vision lane.
    """

    def propose(png_bytes: bytes, prompt: str):
        target_list = getattr(session, "last_targets", None)
        if (target_list is None or session.last_snapshot is None
                or target_list.seq != session.last_snapshot.seq):
            target_list = session.targets()
        observation_id = "obs-{}".format(target_list.seq)
        action = engine.next_action(target_list.targets, observation_id)
        return action, {"source": "cua-s1", "chars": 0}

    return propose
