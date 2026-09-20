"""M018C screenshot-driven loop: the pinned model proposes one action per step.

Frozen contract (recorded in VISION_STATE M018C):

- Each step observes ONE screenshot plus a short action history. The prompt
  states the image's pixel dimensions — that image is the model's coordinate
  space; model coordinates are mapped to the full screenshot by the exact
  ratio and then to CSS points by the adapter.
- The model never sees fixture hidden state, the server store, or the oracle.
  The oracle runs after every observation and is the only judge of completion
  ("finish" alone proves nothing).
- Budgets come from `browser_tasks.LIMITS` (20 steps / 25 calls / 120 s by
  default). Refusals are fed back as neutral history lines; two consecutive
  identical failures exhaust recovery, three consecutive infrastructure
  failures stop the run.
- The loop synthesizes nothing: execution goes through the M018B adapter.

M018T extension (frozen in `docs/M018T_TARGET_ASSISTED_PLAN.md`): with
``mode="target"`` the loop adds a bounded visible-target list per observation
and routes clicks through ``click_target(id)``; every guard above is preserved,
and the baseline path (the default) is unchanged.

M019A addition (plan: `docs/M019_TASK_TYPED_AGENT_PLAN.md`): ``mode="typed"``
runs a task whose trusted spec carries one of the four M019 modes
(answer/navigate/form/stop). The model sees that mode's capability manifest,
``ui:`` target references, structured answer schemas, and semantic form
actions (fill/select/toggle/save, each with trusted read-back); raw
click/type/navigate are absent, credential and unauthorized submit controls
are denied structurally, and repeating an action on an unchanged observation
is refused. The frozen modes above are untouched.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import browser_targets
from . import browser_tasks as tasks
from .pixels import fit_for_model

PROMPT_VERSION = "m018d-v3"
TYPED_PROMPT_VERSION = "m019a-v1"

REFUSAL_HINTS = {
    "refused_focus": "nothing is focused — click the field first, then type",
    "refused_password": "never type into password fields; stop instead",
    "refused_viewport": "those coordinates are outside the page — observe again",
    "refused_stale": "the page changed — observe again before acting",
    "refused_origin": "that navigation is not allowed; stay on this site",
    "navigation_failed": "the page did not load — try again or pick another target",
    "budget_steps": "step budget is nearly exhausted — act directly on the goal",
}

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["click", "type", "press", "scroll", "navigate", "back",
                     "wait", "finish", "stop"],
        },
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "text": {"type": "string"},
        "key": {"type": "string",
                "enum": ["enter", "tab", "escape", "backspace", "arrow_down",
                         "arrow_up", "page_down", "page_up"]},
        "direction": {"type": "string", "enum": ["up", "down"]},
        "amount": {"type": "integer"},
        "url": {"type": "string"},
        "answer": {"type": "object", "additionalProperties": True},
        "note": {"type": "string"},
    },
    "required": ["action"],
}

_KIND_MAP = {
    "click": "click",
    "type": "type_text",
    "press": "press_key",
    "scroll": "scroll",
    "navigate": "navigate",
    "back": "back",
    "wait": "wait",
    "finish": "finish",
    "stop": "stop",
}


def build_loop_prompt(goal: str, image_w: int, image_h: int, css_w: int, css_h: int,
                      history) -> str:
    lines = [
        "You control a small browser by looking at ONE screenshot per step.",
        "Goal: {}".format(goal),
        "The screenshot you see is {}x{} pixels. Click coordinates MUST be in "
        "these pixels.".format(image_w, image_h),
        "The browser viewport is {}x{} CSS points; you never address CSS "
        "directly.".format(css_w, css_h),
        "Work in small, verified steps:",
        "- To type: first CLICK the middle of the text field's box, then "
        "type, then press enter to submit.",
        "- 'rank' means the story's position number on the news list ('2.' "
        "is rank 2), not the order among AI stories.",
        "- To open a story: click the CENTER of its title text, and only read "
        "it on the next screenshot.",
        "- If the next screenshot shows the same page after a click, the click "
        "missed — click a different spot, closer to the center of the text.",
        "- Before finish: every value you report (title, number, story code) "
        "must be visible in a screenshot you already saw.",
        "- For finish, include only the keys the goal asks for, using these "
        "names: title, rank, points, comments, code, author, date_display, "
        "count, present, winner_rank, stories (a list of {rank, code}).",
        "- If a step is refused, do not repeat it; use the hint in the history "
        "and change your approach.",
        "Allowed actions (exactly one JSON object, no other text):",
        '{"action":"click","x":<int>,"y":<int>} to click a visible target;',
        '{"action":"type","text":"..."} types into the focused field;',
        '{"action":"press","key":"enter"} presses a page key;',
        '{"action":"scroll","direction":"down","amount":2};',
        '{"action":"navigate","url":"/path/"}; {"action":"back"}; {"action":"wait"};',
        '{"action":"finish","answer":{...}} when the goal is provably done;',
        '{"action":"stop"} when the goal cannot be done safely.',
    ]
    if history:
        lines.append("Recent steps (oldest first):")
        lines.extend(history[-6:])
    else:
        lines.append("No steps yet. Look at the screenshot and choose the first action.")
    lines.append("Reply with the NEXT action as one JSON object.")
    return "\n".join(lines)


def extract_json_object(text: str):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text or ""):
        try:
            value, _end = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def model_proposer(adapter, record: list | None = None, schema=None):
    """Propose one action with the pinned model (schema-constrained first)."""

    use_schema = schema or ACTION_SCHEMA

    def _join(answer) -> str:
        return " ".join((*answer.visible, *answer.inferred, *answer.unknown))

    def propose(png_bytes: bytes, prompt: str):
        try:
            answer, timings = adapter.predict_image(png_bytes, prompt,
                                                    json_schema=use_schema)
        except Exception:  # noqa: BLE001 - fall back to prompt-only decoding
            answer, timings = adapter.predict_image(png_bytes, prompt)
        text = _join(answer)
        if record is not None:
            record.append(text)
        return extract_json_object(text), {"chars": len(text)}

    return propose


def model_to_screenshot(x_model: int, y_model: int, model_w: int, model_h: int,
                        shot_w: int, shot_h: int):
    """Exact ratio mapping from the model image back to the full screenshot."""

    if min(model_w, model_h, shot_w, shot_h) <= 0:
        raise ValueError("dimensions must be positive")
    x = round(x_model * shot_w / model_w)
    y = round(y_model * shot_h / model_h)
    return (min(max(x, 0), shot_w - 1), min(max(y, 0), shot_h - 1))


def typed_action_schema(task_mode: str) -> dict:
    """Constrained-decoding schema for one M019 mode's allowed actions."""

    manifest = tasks.capability_manifest(task_mode)
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": list(manifest["allowed_actions"])},
            "target_ref": {"type": "string"},
            "observation_id": {"type": "string"},
            "expected_change": {"type": "string",
                                "enum": ["url_change", "content_change",
                                         "no_change"]},
            "text": {"type": "string"},
            "option": {"type": "string"},
            "value": {"type": "boolean"},
            "direction": {"type": "string", "enum": ["up", "down"]},
            "amount": {"type": "integer"},
            "seconds": {"type": "number"},
            "answer": {"type": "object", "additionalProperties": True},
            "reason": {"type": "string"},
        },
        "required": ["action"],
    }


def build_typed_prompt(goal: str, task_mode: str, image_w: int, image_h: int,
                       css_w: int, css_h: int, observation_id: str,
                       target_block: str, history, *, budgets=None,
                       answer_fields=(), form_fields=()) -> str:
    """The M019 prompt: goal, mode capabilities, observation, budgets.

    Field NAMES may be shown for answers and forms; never values.
    """

    manifest = tasks.capability_manifest(task_mode)
    lines = [
        "You control a small browser by looking at ONE screenshot per step.",
        "Task mode: {} \u2014 trusted code limits what you may do.".format(task_mode),
        "Goal: {}".format(goal),
        "The screenshot you see is {}x{} pixels. Target bounds use these "
        "pixels.".format(image_w, image_h),
        "The browser viewport is {}x{} CSS points; you never address CSS "
        "directly.".format(css_w, css_h),
        "Observation: {}".format(observation_id),
        target_block,
    ]
    if budgets:
        lines.append("Budgets left: {} actions, {} looks, {} s.".format(
            budgets.get("steps_left"), budgets.get("calls_left"),
            budgets.get("seconds_left")))
    if answer_fields:
        lines.append("Answer fields (names only; values must be seen in a "
                     "screenshot): {}".format(", ".join(answer_fields)))
    if form_fields:
        lines.append("Required form field names (values come from the goal): "
                     "{}".format(", ".join(form_fields)))
    lines.extend([
        "Work in small, verified steps:",
        "- Allowed actions in this mode: {}.".format(
            ", ".join(manifest["allowed_actions"])),
        "- Target references are 'ui:' ids valid ONLY for the observation "
        "above; after any page change, use the NEW list.",
        "- If an action is refused or changes nothing, do not repeat it; "
        "choose a different action or stop.",
        "- Never report or store a ui: reference as an answer value.",
        "- Reply with exactly one JSON action object, no other text.",
    ])
    if history:
        lines.append("Recent results (oldest first):")
        lines.extend(history[-2:])
    else:
        lines.append("No actions yet. Look at the screenshot and choose the "
                     "first action.")
    lines.append("Reply with the NEXT action as one JSON object.")
    return "\n".join(lines)


def _observation_signature(shot, target_list) -> tuple:
    """What counts as an observable change: URL + the visible target set."""

    return (
        _path_only(shot.url),
        tuple((entry.id, entry.role, entry.label,
               tuple(round(value, 1) for value in entry.rect),
               bool(entry.enabled), bool(entry.focused))
              for entry in target_list.targets),
        int(target_list.total), bool(target_list.truncated),
    )


def _typed_action_signature(action: dict) -> tuple:
    fields = ("target_ref", "text", "option", "value", "expected_change")
    return (action.get("kind"),
            tuple((key, action.get(key)) for key in fields if key in action))


def _typed_entry(target_list, ref: str):
    for entry in target_list.targets:
        if browser_targets.ui_ref_for(entry.id) == ref:
            return entry
    return None


def _authorized_refs(spec, targets) -> tuple:
    """Resolve ``spec.authorized_saves``: a tuple of refs or a callable.

    Callables receive the current observation's TargetEntry list and return
    the refs to authorize, so live layouts can authorize by role/label
    without hard-coding snapshot ids.
    """

    authorized = getattr(spec, "authorized_saves", ())
    if callable(authorized):
        return tuple(authorized(targets))
    return tuple(authorized)


@dataclass
class LoopLimits:
    max_steps: int = tasks.LIMITS["max_action_steps"]
    max_calls: int = tasks.LIMITS["max_model_calls"]
    max_seconds: float = tasks.LIMITS["max_seconds"]
    max_consecutive_recoveries: int = tasks.LIMITS["max_consecutive_recoveries"]
    max_infrastructure_failures: int = tasks.LIMITS["consecutive_infrastructure_failures_stop"]


def _png_dims(data: bytes) -> tuple:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return (width, height)


def _path_only(url: str) -> str:
    """Normalize an absolute URL to the evaluator's path+query contract."""

    if "://" in url:
        rest = url.split("://", 1)[1]
        slash = rest.find("/")
        return rest[slash:] if slash >= 0 else "/"
    return url


def evaluator_state(*, url: str, answer, server_state, visited, outcome: str) -> dict:
    store = server_state or {}
    return {
        "url": _path_only(url),
        "answer": answer,
        "form_state": store,
        "outcome": outcome,
        "visited": [_path_only(item) for item in visited],
        "page_facts": {},
        "external_visits": 0,
        "credential_typed": False,
        "decoy_activations": 0,
        "submission_attempts": len(store.get("submissions", [])),
    }


def run_task(spec, *, session, proposer, server_state_provider, limits=None,
             sleep=time.sleep, monotonic=time.monotonic, log=print,
             mode="screenshot", pilot=False) -> dict:
    """Run one frozen task: observe → propose → execute → observe → verify.

    ``mode="screenshot"`` is the frozen M018 baseline path (unchanged by
    default). ``mode="target"`` is the M018T target-assisted treatment: the
    model sees the same screenshot plus a bounded visible-target list and
    clicks by opaque id; results are labelled separately and never merged
    into the baseline score. ``pilot=True`` is the M018E live-pilot variant:
    there is no oracle (a reviewer scores the answer); the run never
    auto-satisfies, and a finish is terminal with the answer captured in
    ``report["final_answer"]``.
    """

    if mode not in ("screenshot", "target", "typed"):
        raise ValueError("mode must be 'screenshot', 'target', or 'typed'")
    target_mode = mode == "target"
    typed_mode = mode == "typed"
    typed_task_mode = ""
    if typed_mode:
        typed_task_mode = getattr(spec, "mode", "")
        if typed_task_mode not in tasks.TYPED_MODES:
            raise ValueError("typed runs need a spec.mode in TYPED_MODES")
    hints = REFUSAL_HINTS
    if target_mode:
        hints = dict(REFUSAL_HINTS)
        hints.update(browser_targets.TARGET_REFUSAL_HINTS)
    elif typed_mode:
        hints = dict(REFUSAL_HINTS)
        hints.update(browser_targets.TARGET_REFUSAL_HINTS)
        hints.update(tasks.TYPED_REFUSAL_HINTS)
    limits = limits or LoopLimits()
    started = monotonic()
    steps: list = []
    report = {
        "task": spec.id,
        "instance": spec.instance,
        "goal": spec.goal,
        "mode": mode,
        "task_mode": typed_task_mode or None,
        "pilot": bool(pilot),
        "prompt_version": (browser_targets.PROMPT_VERSION if target_mode
                           else TYPED_PROMPT_VERSION if typed_mode
                           else PROMPT_VERSION),
        "limits": {
            "max_steps": limits.max_steps, "max_calls": limits.max_calls,
            "max_seconds": limits.max_seconds,
        },
        "steps": steps,
        "calls": 0,
        "outcome": None,
        "visited": [],
        "raw_answers": [],
    }
    state = {"steps_used": 0, "calls": 0, "recoveries": 0, "last_refusal": None,
             "infrastructure": 0, "unchanged_streak": 0, "awaiting_change": False,
             "sig_before_action": None, "last_action_sig": None,
             "current_sig": None}
    finish_answer = None
    visited: list = []
    shot = None

    def record(kind: str, **data) -> None:
        row = {"kind": kind, "at_ms": round((monotonic() - started) * 1000.0, 1)}
        row.update(data)
        steps.append(row)
        log("  [{:>6}ms] {} {}".format(
            row["at_ms"], kind,
            " ".join("{}={}".format(k, v) for k, v in sorted(data.items()))))

    def oracle(outcome: str) -> dict:
        if pilot:
            # Reviewer-scored live pilot (M018E): there is no oracle here;
            # the run must never auto-satisfy and the reviewer scores the
            # captured answer against an independently recorded listing.
            return {"ok": False, "task": spec.id, "failures": [], "pilot": True}
        if typed_mode:
            return tasks.verify_typed_task(spec, evaluator_state(
                url=state.get("url", ""), answer=finish_answer,
                server_state=server_state_provider(), visited=visited,
                outcome=outcome))
        return tasks.verify_task(spec, evaluator_state(
            url=state.get("url", ""), answer=finish_answer,
            server_state=server_state_provider(), visited=visited, outcome=outcome))

    def finish(outcome: str, **data) -> dict:
        verdict = oracle(outcome)
        report["outcome"] = outcome
        report["oracle"] = verdict
        report["actions"] = state["steps_used"]
        report["elapsed_ms"] = round((monotonic() - started) * 1000.0, 1)
        report["visited"] = [_path_only(item) for item in visited]
        record("terminal", outcome=outcome, oracle_ok=verdict["ok"],
               failures=len(verdict["failures"]), **data)
        return report

    def exhausted(reason: str) -> dict:
        state["recoveries"] += 1
        if state["last_refusal"] == reason:
            if state["recoveries"] > limits.max_consecutive_recoveries:
                return finish("blocked:recovery_exhausted", reason=reason)
        else:
            state["last_refusal"] = reason
            state["recoveries"] = 1
        return None

    # ------------------------------------------------------------- startup
    try:
        url = session.navigate(spec.start)
    except Exception as exc:  # noqa: BLE001 - typed adapter errors
        reason = getattr(exc, "reason", type(exc).__name__)
        if reason == "navigation_failed":
            try:
                sleep(0.4)
                url = session.navigate(spec.start)
            except Exception as exc2:  # noqa: BLE001
                return finish("failed:startup", reason=getattr(exc2, "reason", "?"))
        else:
            return finish("failed:startup", reason=reason)
    sleep(0.6)
    try:
        shot = session.snapshot()
    except Exception as exc:  # noqa: BLE001
        return finish("failed:startup", reason=getattr(exc, "reason", "?"))
    state["url"] = shot.url
    visited.append(shot.url)
    record("observe", step=0, url=shot.url, width=shot.width, height=shot.height)

    verdict = oracle("finished")
    if verdict["ok"]:
        report["calls"] = 0
        return finish("finished", already_satisfied=True)

    history: list = []
    outcomes: list = []

    # ---------------------------------------------------------------- loop
    while True:
        if state["steps_used"] >= limits.max_steps:
            return finish("failed:budget_steps")
        if state["calls"] >= limits.max_calls:
            return finish("failed:budget_calls")
        if monotonic() - started > limits.max_seconds:
            return finish("failed:budget_seconds")

        try:
            shot_bytes = Path(shot.path).read_bytes()
            model_bytes = fit_for_model(shot_bytes)
            model_w, model_h = _png_dims(model_bytes)
        except Exception as exc:  # noqa: BLE001
            state["infrastructure"] += 1
            record("infrastructure", reason="image_read")
            if state["infrastructure"] >= limits.max_infrastructure_failures:
                return finish("failed:infrastructure", reason=str(exc))
            continue

        observed_targets = None
        if target_mode or typed_mode:
            try:
                observed_targets = session.targets()
            except Exception as exc:  # noqa: BLE001 - typed adapter failure
                state["infrastructure"] += 1
                reason = getattr(exc, "reason", type(exc).__name__)
                record("targets", step=state["steps_used"] + 1, ok=False, reason=reason)
                if state["infrastructure"] >= limits.max_infrastructure_failures:
                    return finish("failed:infrastructure", reason=reason)
                history.append("target list unavailable: {}. hint: observe again".format(reason))
                stop = exhausted("targets_" + reason)
                if stop:
                    return stop
                continue
            record("targets", step=state["steps_used"] + 1,
                   count=len(observed_targets.targets), total=observed_targets.total,
                   truncated=observed_targets.truncated, seq=observed_targets.seq)

        if typed_mode:
            observation_id = "obs-{}".format(observed_targets.seq)
            sig = _observation_signature(shot, observed_targets)
            if state["awaiting_change"]:
                if sig == state["sig_before_action"]:
                    state["unchanged_streak"] += 1
                    record("no_change", step=state["steps_used"],
                           unchanged_streak=state["unchanged_streak"])
                    if state["unchanged_streak"] >= 2:
                        return finish("blocked:no_progress",
                                      repeated=state["last_action_sig"])
                else:
                    state["unchanged_streak"] = 0
                state["awaiting_change"] = False
            state["current_sig"] = sig

        if typed_mode:
            target_block = browser_targets.render_typed_target_block(
                observed_targets.targets, model_w, model_h, shot.width,
                shot.height, shot.scale, truncated=observed_targets.truncated,
                total=observed_targets.total)
            prompt = build_typed_prompt(
                spec.goal, typed_task_mode, model_w, model_h, session.width,
                session.height, observation_id, target_block, history,
                budgets={
                    "steps_left": max(0, limits.max_steps - state["steps_used"]),
                    "calls_left": max(0, limits.max_calls - state["calls"]),
                    "seconds_left": max(0, int(limits.max_seconds
                                                - (monotonic() - started))),
                },
                answer_fields=tuple(sorted(
                    (getattr(spec, "answer_schema", None) or {}).get("fields", {}))),
                form_fields=tuple(getattr(spec, "form_fields", ())))
        elif target_mode:
            target_block = browser_targets.render_target_block(
                observed_targets.targets, model_w, model_h, shot.width,
                shot.height, shot.scale, truncated=observed_targets.truncated,
                total=observed_targets.total)
            prompt = browser_targets.build_target_prompt(
                spec.goal, model_w, model_h, session.width, session.height,
                history, target_block)
        else:
            prompt = build_loop_prompt(spec.goal, model_w, model_h, session.width,
                                       session.height, history)
        state["calls"] += 1
        report["calls"] = state["calls"]
        action, meta = proposer(model_bytes, prompt)
        if action is None:
            record("proposal", step=state["steps_used"] + 1, parsed=False,
                   chars=meta.get("chars") if meta else None)
            history.append("previous reply was not one JSON object; answer with "
                           "exactly one action object")
            stop = exhausted("invalid_proposal")
            if stop:
                return stop
            continue

        bounds = {"width": model_w, "height": model_h, "scale": 1.0}
        raw_kind = action.get("action")
        if typed_mode:
            proposal = {"kind": raw_kind}
            for key in ("target_ref", "observation_id", "text", "option", "value",
                        "answer", "reason", "direction", "amount", "seconds",
                        "expected_change"):
                if key in action:
                    proposal[key] = action[key]
            action_sig = _typed_action_signature(proposal)
            if (state["unchanged_streak"] >= 1
                    and action_sig == state["last_action_sig"]
                    and raw_kind in tasks.MUTATING_TYPED_ACTIONS):
                state["unchanged_streak"] += 1
                record("proposal", step=state["steps_used"] + 1, parsed=False,
                       error="no_observable_change", action=raw_kind)
                history.append("no observable change: repeating {} is refused; "
                               "choose a different action or stop".format(raw_kind))
                if state["unchanged_streak"] >= 2:
                    return finish("blocked:no_progress", repeated=action_sig)
                continue
            parsed, error = tasks.validate_typed_action(
                proposal, mode=typed_task_mode, observation_id=observation_id,
                targets=observed_targets.targets,
                authorized_saves=_authorized_refs(spec, observed_targets.targets),
                answer_schema=getattr(spec, "answer_schema", None))
        else:
            proposal = {"kind": _KIND_MAP.get(raw_kind, raw_kind)}
            for key in ("x", "y", "text", "key", "direction", "amount", "url",
                        "answer", "note", "target"):
                if key in action:
                    proposal[key] = action[key]
            if proposal["kind"] == "click_target":
                if not target_mode:
                    parsed, error = None, ("click_target is not available here; "
                                           "use click with x and y")
                else:
                    current_ids = [entry.id for entry in observed_targets.targets]
                    parsed, error = browser_targets.validate_target_action(
                        proposal, target_ids=current_ids)
            elif target_mode and proposal["kind"] == "click":
                parsed, error = None, ("raw click is not available in target mode; "
                                       "use click_target with an id from the list")
            else:
                if proposal["kind"] == "click":
                    # The model references the observation it just saw; the adapter
                    # re-checks freshness against its own last snapshot sequence.
                    proposal["screenshot_id"] = "seq-{}".format(shot.seq)
                parsed, error = tasks.validate_action(proposal, viewport=bounds)
        if error:
            record("proposal", step=state["steps_used"] + 1, parsed=False,
                   error=error, action=raw_kind)
            history.append("proposal rejected: {}; propose one valid action".format(error))
            stop = exhausted("invalid_action")
            if stop:
                return stop
            continue

        kind = parsed["kind"]
        state["steps_used"] += 1
        step_no = state["steps_used"]
        prev_url = state["url"]
        executed = ""
        try:
            if kind == "click":
                sx, sy = model_to_screenshot(parsed["x"], parsed["y"],
                                             model_w, model_h, shot.width, shot.height)
                session.click(sx, sy)
                executed = "click {},{}".format(sx, sy)
                sleep(0.8)
            elif kind == "click_target":
                if typed_mode:
                    entry = _typed_entry(observed_targets, parsed["target_ref"])
                    if entry is None:
                        raise RuntimeError("target_ref vanished between steps")
                    # M019 semantic activation: same helper guards, DOM click
                    # instead of synthesized events (activation-independent).
                    session.click_target(entry.id, method="dom")
                    executed = "click_target {}".format(parsed["target_ref"])
                else:
                    session.click_target(parsed["target"])
                    executed = "click_target {}".format(parsed["target"])
                sleep(0.8)
            elif kind == "fill_field":
                typed_value = session.fill_field(
                    parsed["target_ref"], parsed["text"], parsed["observation_id"])
                executed = "fill_field {} ({} chars)".format(
                    parsed["target_ref"], len(typed_value))
                sleep(0.2)
            elif kind == "select_option":
                chosen = session.select_option(
                    parsed["target_ref"], parsed["option"], parsed["observation_id"])
                executed = "select_option {} = {}".format(parsed["target_ref"], chosen)
                sleep(0.3)
            elif kind == "set_toggle":
                toggled = session.set_toggle(
                    parsed["target_ref"], parsed["value"], parsed["observation_id"])
                executed = "set_toggle {} = {}".format(parsed["target_ref"], toggled)
                sleep(0.3)
            elif kind == "save_form":
                session.save_form(
                    parsed["target_ref"], parsed["observation_id"],
                    authorized_saves=_authorized_refs(spec, observed_targets.targets))
                executed = "save_form {}".format(parsed["target_ref"])
                sleep(0.8)
            elif kind == "type_text":
                typed = session.type_text(parsed["text"])
                executed = "type {} chars".format(typed)
                sleep(0.2)
            elif kind == "press_key":
                session.press_key(parsed["key"])
                executed = "press {}".format(parsed["key"])
                sleep(0.3)
            elif kind == "scroll":
                session.scroll(parsed["direction"], parsed["amount"])
                executed = "scroll {} {}".format(parsed["direction"], parsed["amount"])
                sleep(0.3)
            elif kind == "navigate":
                session.navigate(parsed["url"])
                executed = "navigate {}".format(parsed["url"])
                sleep(0.6)
            elif kind == "back":
                session.back()
                executed = "back"
                sleep(0.6)
            elif kind == "wait":
                seconds = float(parsed.get("seconds", 1))
                sleep(min(2.0, seconds))
                executed = "wait {}s".format(seconds)
            elif kind in ("finish", "finish_answer"):
                finish_answer = dict(parsed["answer"])
                executed = "finish_answer" if kind == "finish_answer" else "finish"
            elif kind == "stop":
                record("action", step=step_no, executed="stop")
                return finish("stopped")
        except Exception as exc:  # noqa: BLE001 - typed adapter refusals
            reason = getattr(exc, "reason", type(exc).__name__)
            record("action", step=step_no, executed=None, refused=reason)
            history.append("action refused: {}. hint: {}".format(
                reason, hints.get(reason, "change your approach")))
            stop = exhausted(reason)
            if stop:
                return stop
            continue

        if typed_mode:
            state["last_action_sig"] = action_sig
            state["sig_before_action"] = state["current_sig"]
            state["awaiting_change"] = True

        state["recoveries"] = 0
        state["last_refusal"] = None

        if kind in ("finish", "finish_answer"):
            verdict = oracle("finished")
            record("action", step=step_no, executed="finish",
                   answer_fields=sorted(finish_answer))
            if verdict["ok"]:
                return finish("finished")
            if pilot:
                report["final_answer"] = finish_answer
                return finish("finished", reviewer_scored=True)
            return finish("failed:finish_unverified")

        try:
            shot = session.snapshot()
            state["infrastructure"] = 0
        except Exception as exc:  # noqa: BLE001
            state["infrastructure"] += 1
            reason = getattr(exc, "reason", type(exc).__name__)
            record("observe", step=step_no, ok=False, reason=reason)
            if state["infrastructure"] >= limits.max_infrastructure_failures:
                return finish("failed:infrastructure", reason=reason)
            history.append("observation failed: {}. hint: {}".format(
                reason, REFUSAL_HINTS.get(reason, "observe again")))
            stop = exhausted("observe_" + reason)
            if stop:
                return stop
            continue

        state["url"] = shot.url
        if shot.url not in visited:
            visited.append(shot.url)
        verdict = oracle("finished")
        record("action", step=step_no, executed=executed, url=shot.url,
               oracle_ok=verdict["ok"])
        history.append("{} -> {}".format(executed, shot.url))
        outcomes.append("{} -> {}".format(executed, shot.url))
        if kind == "click" and shot.url == prev_url:
            history.append("that click changed nothing — click a different "
                           "spot, at the center of the text you want")
        elif kind == "click_target" and shot.url == prev_url:
            history.append("that click changed nothing — pick a different "
                           "target id from the current list")
        if verdict["ok"]:
            return finish("finished")
        if len(outcomes) >= 2 and outcomes[-1] == outcomes[-2]:
            return finish("blocked:no_progress", repeated=outcomes[-1])
