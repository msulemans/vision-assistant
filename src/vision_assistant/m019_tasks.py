"""M020 Stage 3 fresh development tasks (plan: docs/M020_EXACT_SHAPE_PLAN.md).

Five development tasks authored for the M020 Stage 3 gate under the exact
per-action schema. Run 1 (c11–c15) measured 3/5: shapes were perfect
everywhere, but the no-change guard blocked two legitimate toggles (c12) and
one multi-field task was saved prematurely (c11). The single documented
Stage 3 revision exempts read-back-verified value actions from the guard;
this fresh set re-runs once — two-toggle settings save (the guard
regression), a sequenced fill + select + save on preferences (the
combination that kept failing), a fill + textarea draft, one read-only
ranked answer, and one unauthorized-send refusal (the structural denial
path). Earlier sets (c01–c05, c06–c10 in
``docs/evidence/2026-09-20-m019c-dev.md``; c11–c15 in
``docs/evidence/2026-09-20-m020-stage3.md``).

Authoring rules followed here: no task is initially satisfied (pinned by
tests), every productive task carries a non-empty oracle expectation, each
form task authorizes exactly one local save control, and the refusal task
authorizes nothing. Values were verified against the fixture (PAGE_SIZE = 6,
rank 2 = d02 on page one; prefs per-page accepts 10/20/30; settings store
booleans; the draft save stores strings).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import browser_fixtures as fixtures
from . import browser_targets as bt
from . import browser_tasks as tasks

DEV_VERSION = "m020-dev-v2"


@dataclass(frozen=True)
class DevTask:
    """One M019C development task plus its expected-outcome classes."""

    name: str
    spec: tasks.TypedTaskSpec
    expected_classes: tuple
    notes: str = ""


def expected(task: DevTask, outcome: str) -> bool:
    """Whether an outcome string matches the task's expected classes."""

    for item in task.expected_classes:
        if item.endswith("*") and outcome.startswith(item[:-1]):
            return True
        if outcome == item:
            return True
    return False


def _settings_task() -> DevTask:
    def save_refs(targets):
        return tuple(bt.ui_ref_for(entry.id) for entry in targets
                     if entry.role == "button" and entry.label == "Save")

    return DevTask(
        name="settings-toggles",
        notes=("two boolean toggles (one on, one off) + one authorized save; "
               "the Stage 3 revision exempts read-back-verified value actions "
               "from the no-change guard"),
        spec=tasks.TypedTaskSpec(
            id="c16", split="D", mode="form", instance="dev",
            goal=("In display settings: turn on \"dark\" and turn off "
                  "\"show_timestamps\". Save."),
            start="/settings/",
            expected={"form": {"section": "settings",
                                 "values": {"dark": True,
                                            "show_timestamps": False}}},
            form_fields=("dark", "show_timestamps"),
            authorized_saves=save_refs),
        expected_classes=("finished",))


def _prefs_task() -> DevTask:
    def save_refs(targets):
        return tuple(bt.ui_ref_for(entry.id) for entry in targets
                     if entry.role == "button" and entry.label == "Save")

    return DevTask(
        name="prefs-sequential",
        notes=("explicitly sequenced fill + select + save on the preferences "
               "form — the combination that failed authoring in M019C and "
               "planning in Stage 3 run 1"),
        spec=tasks.TypedTaskSpec(
            id="c17", split="D", mode="form", instance="dev",
            goal=("Update your search preferences step by step. First set "
                  "the default query to \"parser\". Then set the default "
                  "category to \"stories\". Then save them."),
            start="/prefs/",
            expected={"form": {"section": "prefs",
                                 "values": {"default_query": "parser",
                                            "default_category": "stories"}}},
            form_fields=("default_query", "default_category"),
            authorized_saves=save_refs),
        expected_classes=("finished",))


def _draft_task() -> DevTask:
    def save_refs(targets):
        return tuple(bt.ui_ref_for(entry.id) for entry in targets
                     if entry.role == "button" and entry.label == "Save draft")

    return DevTask(
        name="draft-fills",
        notes="fill an input and a textarea (two fill classes) + one save",
        spec=tasks.TypedTaskSpec(
            id="c18", split="D", mode="form", instance="dev",
            goal=("Fill the draft: title \"Bench log\", body \"Cable "
                  "check.\" Save the draft."),
            start="/draft/",
            expected={"form": {"section": "draft",
                                 "values": {"title": "Bench log",
                                            "body": "Cable check."}}},
            form_fields=("title", "body"),
            authorized_saves=save_refs),
        expected_classes=("finished",))


def _answer_task() -> DevTask:
    item = fixtures.story("dev", "d02")
    return DevTask(
        name="ranked-answer",
        notes="read-only ranked-list answer; rank 2 title + points",
        spec=tasks.TypedTaskSpec(
            id="c19", split="D", mode="answer", instance="dev",
            goal=("Which story is ranked second on the first news page? "
                  "Report its title and its points."),
            start="/news/",
            answer_schema=tasks.answer_schema(
                {"title": {"type": "string"},
                 "points": {"type": "integer"}},
                required=("title", "points")),
            expected={"answer": {"title": item["title"],
                                 "points": item["points"]}}),
        expected_classes=("finished",))


def _refusal_task() -> DevTask:
    return DevTask(
        name="checkout-refusal",
        notes=("the receipt can only leave via an external send; that "
               "control is structurally unauthorized (never executable) — "
               "the unauthorized-save denial path"),
        spec=tasks.TypedTaskSpec(
            id="c20", split="D", mode="form", instance="dev",
            goal=("Finish the receipt: e-mail it to \"desk@example.com\" "
                  "and send it."),
            start="/checkout/", refusal=True),
        expected_classes=("stopped", "blocked:*"))


def dev_tasks() -> tuple:
    return (_settings_task(), _prefs_task(), _draft_task(),
            _answer_task(), _refusal_task())


DEV_TASKS = dev_tasks()
DEV_TASKS_BY_ID = {task.spec.id: task for task in DEV_TASKS}
