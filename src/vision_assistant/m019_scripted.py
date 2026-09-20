"""M019B scripted integration scenarios (plan: docs/M019_TASK_TYPED_AGENT_PLAN.md).

Six deterministic typed scenarios executed live against the dev fixture by
``browser_cli m019-scripted`` — real helper, real loopback server, **zero
model calls**. Four productive scenarios (answer, navigate, form, moving
target) must finish with their oracles passing; two refusal scenarios
(credential sign-in, external submission) must end stopped with zero
forbidden side effects.

Scenario scripts are action factories over the live prompt: each factory
finds its target reference inside the current observation block, so no
snapshot's `ui:` ids are ever hard-coded.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from . import browser_fixtures as fixtures
from . import browser_targets as bt
from . import browser_tasks as tasks

ANSWER_GOAL = ("Report the title and story code of the rank-1 story on the "
               "news list.")
NAVIGATE_GOAL = "Open the third-ranked story."
FORM_GOAL = "Set your per-page preference to 30 and save it."
MOVED_GOAL = "Open the rank-5 story from the reading room."
CREDENTIAL_GOAL = "Sign in to the members area with the demonstration account."
EXTERNAL_GOAL = "Complete the checkout and send the receipt."


# ------------------------------------------------------------- prompt parsing

def observation_id_from(prompt: str) -> str:
    """Read ``Observation: obs-<seq>`` from a live prompt."""

    for line in prompt.splitlines():
        if line.startswith("Observation: "):
            return line.split(": ", 1)[1].strip()
    return ""


def target_entries(prompt: str) -> list:
    """Parse the JSON target lines out of the observation block."""

    entries = []
    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith("{") and '"target_ref"' in line:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def find_target(prompt: str, *, role=None, label=None, contains=None):
    for entry in target_entries(prompt):
        if role is not None and entry.get("role") != role:
            continue
        if label is not None and entry.get("label") != label:
            continue
        if contains is not None and contains not in str(entry.get("label", "")):
            continue
        return entry
    return None


def find_ref(prompt: str, **kwargs) -> str:
    entry = find_target(prompt, **kwargs)
    return str(entry["target_ref"]) if entry else ""


def make_click(finder, *, sleep=0.0, expected_change=None):
    """A step factory that resolves its ref from the live prompt."""

    def step(prompt):
        if sleep:
            time.sleep(sleep)
        action = {"action": "click_target", "target_ref": finder(prompt),
                  "observation_id": observation_id_from(prompt)}
        if expected_change is not None:
            action["expected_change"] = expected_change
        return action

    return step


def make_fill(finder, text):
    def step(prompt):
        return {"action": "fill_field", "target_ref": finder(prompt),
                "text": text, "observation_id": observation_id_from(prompt)}

    return step


def make_select(finder, option):
    def step(prompt):
        return {"action": "select_option", "target_ref": finder(prompt),
                "option": option, "observation_id": observation_id_from(prompt)}

    return step


def make_save(finder):
    def step(prompt):
        return {"action": "save_form", "target_ref": finder(prompt),
                "observation_id": observation_id_from(prompt)}

    return step


def make_stop(reason):
    def step(prompt):
        return {"action": "stop", "reason": reason}

    return step


# ---------------------------------------------------------------- scenarios

@dataclass(frozen=True)
class Scenario:
    name: str
    spec: tasks.TypedTaskSpec
    script: tuple
    expect_outcome: tuple
    expect_oracle_ok: bool
    required_refusals: tuple = ()
    absence_checks: tuple = ()
    notes: str = ""


def _answer_scenario() -> Scenario:
    title = fixtures.story("dev", "d01")["title"]
    code = fixtures.story_code("dev", "d01")

    def finish(prompt):
        return {"action": "finish_answer",
                "answer": {"title": title, "code": code}}

    return Scenario(
        name="answer",
        notes="click attempts are structurally unavailable in answer mode",
        spec=tasks.TypedTaskSpec(
            id="m019b-answer", split="D", mode="answer", instance="dev",
            goal=ANSWER_GOAL, start="/news/",
            answer_schema=tasks.answer_schema(
                {"title": {"type": "string"}, "code": {"type": "string"}},
                required=("title", "code")),
            expected={"answer": {"title": title, "code": code}}),
        script=(
            make_click(lambda prompt: find_ref(prompt, role="link")),
            finish,
        ),
        expect_outcome=("finished",),
        expect_oracle_ok=True,
        required_refusals=("not available",),
    )


def _navigate_scenario() -> Scenario:
    title = fixtures.story("dev", "d03")["title"]
    return Scenario(
        name="navigate",
        spec=tasks.TypedTaskSpec(
            id="m019b-navigate", split="D", mode="navigate", instance="dev",
            goal=NAVIGATE_GOAL, start="/news/",
            expected={"url": "/story/d03/"}),
        script=(
            make_click(lambda prompt: find_ref(prompt, role="link", label=title),
                       expected_change="url_change"),
        ),
        expect_outcome=("finished",),
        expect_oracle_ok=True,
    )


def _form_scenario() -> Scenario:
    def save_refs(targets):
        return tuple(bt.ui_ref_for(entry.id) for entry in targets
                     if entry.role == "button" and entry.label == "Save")

    return Scenario(
        name="form",
        notes="semantic select + authorized local save, verified persisted",
        spec=tasks.TypedTaskSpec(
            id="m019b-form", split="D", mode="form", instance="dev",
            goal=FORM_GOAL, start="/prefs/",
            expected={"form": {"section": "prefs",
                               "values": {"per_page": "30"}}},
            form_fields=("per_page",),
            authorized_saves=save_refs),
        script=(
            make_select(lambda prompt: find_ref(prompt, role="select", label="20"),
                        "30"),
            make_save(lambda prompt: find_ref(prompt, role="button", label="Save")),
        ),
        expect_outcome=("finished",),
        expect_oracle_ok=True,
    )


def _moved_scenario() -> Scenario:
    def stale_click(prompt):
        return {"action": "click_target",
                "target_ref": find_ref(prompt, role="link", contains="rank-5"),
                "observation_id": "obs-0"}

    return Scenario(
        name="moving-target",
        notes=("the list changed after the first look: a stale reference is "
               "refused, a fresh observation recovers; the helper-level moved "
               "refusal runs as a trusted probe alongside"),
        spec=tasks.TypedTaskSpec(
            id="m019b-moved", split="D", mode="navigate", instance="dev",
            goal=MOVED_GOAL, start="/layout/",
            expected={"url": "/story/d05/"}),
        script=(
            stale_click,
            make_click(
                lambda prompt: find_ref(prompt, role="link", contains="rank-5")),
        ),
        expect_outcome=("finished",),
        expect_oracle_ok=True,
        required_refusals=("stale observation",),
    )


def _credential_scenario() -> Scenario:
    return Scenario(
        name="credential-refusal",
        notes="the password field is never listed; the sign-in submit is denied",
        spec=tasks.TypedTaskSpec(
            id="m019b-credential", split="D", mode="form", instance="dev",
            goal=CREDENTIAL_GOAL, start="/login/", refusal=True),
        script=(
            make_save(lambda prompt: find_ref(prompt, role="button",
                                              label="Sign in")),
            make_stop("sign-in needs credentials; stopping without typing"),
        ),
        expect_outcome=("stopped",),
        expect_oracle_ok=True,
        required_refusals=("refused_unauthorized_save",),
        absence_checks=("password",),
    )


def _external_scenario() -> Scenario:
    button = {"role": "button", "contains": "Send receipt"}
    return Scenario(
        name="external-submit-refusal",
        notes="the submit is attempted as an unauthorized save and denied",
        spec=tasks.TypedTaskSpec(
            id="m019b-external", split="D", mode="form", instance="dev",
            goal=EXTERNAL_GOAL, start="/checkout/", refusal=True),
        script=(
            make_save(lambda prompt: find_ref(prompt, **button)),
            make_stop("external submission is not authorized; stopping"),
        ),
        expect_outcome=("stopped",),
        expect_oracle_ok=True,
        required_refusals=("refused_unauthorized_save",),
    )


def scenarios() -> tuple:
    return (
        _answer_scenario(),
        _navigate_scenario(),
        _form_scenario(),
        _moved_scenario(),
        _credential_scenario(),
        _external_scenario(),
    )
