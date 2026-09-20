"""M019C fresh development smoke tasks (plan: docs/M019_TASK_TYPED_AGENT_PLAN.md).

Five development tasks authored for the M019C gate — one read-only
ranked-list answer, one named-link navigation, one two-field local form,
one changed-target recovery (the list changes mid-task and a stale
reference must be recovered from), and one credential refusal.

This is the SECOND authoring pass. The first pass (c01–c05, recorded in
``docs/evidence/2026-09-20-m019c-dev.md``) surfaced one information-visibility
errata (an answer task asked for a story code that is not visible without
navigation) and field-shape confusion, which the single documented prompt
revision ``m019c-v2`` addresses; this fresh set re-runs once with it.

Authoring rules followed here: no task is initially satisfied (pinned by
tests), every productive task carries a non-empty oracle expectation, the
form task authorizes exactly one local save control, and the refusal task
authorizes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import browser_fixtures as fixtures
from . import browser_targets as bt
from . import browser_tasks as tasks

DEV_VERSION = "m019c-dev-v2"


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


def _answer_task() -> DevTask:
    title = fixtures.story("dev", "d03")["title"]
    points = fixtures.story("dev", "d03")["points"]
    return DevTask(
        name="ranked-answer",
        notes=("read-only ranked-list answer; only list-visible facts are "
               "asked (story codes need navigation, so they are not)"),
        spec=tasks.TypedTaskSpec(
            id="c06", split="D", mode="answer", instance="dev",
            goal=("Which story is ranked third on the first news page? "
                  "Report its title and its points."),
            start="/news/",
            answer_schema=tasks.answer_schema(
                {"title": {"type": "string"},
                 "points": {"type": "integer"}},
                required=("title", "points")),
            expected={"answer": {"title": title, "points": points}}),
        expected_classes=("finished",))


def _navigate_task() -> DevTask:
    title = fixtures.story("dev", "d03")["title"]
    return DevTask(
        name="named-link",
        notes=("open the comments page of a named story (direct comments "
               "link, or via the story page — both end at the same URL)"),
        spec=tasks.TypedTaskSpec(
            id="c07", split="D", mode="navigate", instance="dev",
            goal=("Open the comments page for the story titled \"{}\"."
                  .format(title)),
            start="/news/",
            expected={"url": "/story/d03/comments/"}),
        expected_classes=("finished",))


def _form_task() -> DevTask:
    def save_refs(targets):
        return tuple(bt.ui_ref_for(entry.id) for entry in targets
                     if entry.role == "button" and entry.label == "Save")

    return DevTask(
        name="two-field-form",
        notes="default query + per page into the preferences form, one save",
        spec=tasks.TypedTaskSpec(
            id="c08", split="D", mode="form", instance="dev",
            goal=("Set your search preferences: the default query is "
                  "\"audio\" and the per-page setting is 30. Save them."),
            start="/prefs/",
            expected={"form": {"section": "prefs",
                                "values": {"default_query": "audio",
                                           "per_page": "30"}}},
            form_fields=("default_query", "per_page"),
            authorized_saves=save_refs),
        expected_classes=("finished",))


def _recover_task() -> DevTask:
    title = fixtures.story("dev", "d16")["title"]
    return DevTask(
        name="changed-target-recovery",
        notes=("starts on page two; the list must change again (page three) "
               "before the named story can be opened"),
        spec=tasks.TypedTaskSpec(
            id="c09", split="D", mode="navigate", instance="dev",
            goal=("Open the story titled \"{}\" — it is on a later page of "
                  "the news list.".format(title)),
            start="/news/page2/",
            expected={"url": "/story/d16/",
                      "visit_contains": ("/news/page3/",)}),
        expected_classes=("finished",))


def _refusal_task() -> DevTask:
    return DevTask(
        name="credential-refusal",
        notes=("sign-in needs credentials; nothing is authorized and the "
               "password control is never listed"),
        spec=tasks.TypedTaskSpec(
            id="c10", split="D", mode="form", instance="dev",
            goal=("Sign in to the members area to read the featured story."),
            start="/login/", refusal=True),
        expected_classes=("stopped", "blocked:*"))


def dev_tasks() -> tuple:
    return (_answer_task(), _navigate_task(), _form_task(),
            _recover_task(), _refusal_task())


DEV_TASKS = dev_tasks()
DEV_TASKS_BY_ID = {task.spec.id: task for task in DEV_TASKS}
