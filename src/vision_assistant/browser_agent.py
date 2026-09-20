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
             mode="screenshot") -> dict:
    """Run one frozen task: observe → propose → execute → observe → verify.

    ``mode="screenshot"`` is the frozen M018 baseline path (unchanged by
    default). ``mode="target"`` is the M018T target-assisted treatment: the
    model sees the same screenshot plus a bounded visible-target list and
    clicks by opaque id; results are labelled separately and never merged
    into the baseline score.
    """

    if mode not in ("screenshot", "target"):
        raise ValueError("mode must be 'screenshot' or 'target'")
    target_mode = mode == "target"
    hints = REFUSAL_HINTS
    if target_mode:
        hints = dict(REFUSAL_HINTS)
        hints.update(browser_targets.TARGET_REFUSAL_HINTS)
    limits = limits or LoopLimits()
    started = monotonic()
    steps: list = []
    report = {
        "task": spec.id,
        "instance": spec.instance,
        "goal": spec.goal,
        "mode": mode,
        "prompt_version": (browser_targets.PROMPT_VERSION if target_mode
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
             "infrastructure": 0}
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
        if target_mode:
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

        if target_mode:
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
                session.click_target(parsed["target"])
                executed = "click_target {}".format(parsed["target"])
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
            elif kind == "finish":
                finish_answer = dict(parsed["answer"])
                executed = "finish"
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

        state["recoveries"] = 0
        state["last_refusal"] = None

        if kind == "finish":
            verdict = oracle("finished")
            record("action", step=step_no, executed="finish",
                   answer_fields=sorted(finish_answer))
            if verdict["ok"]:
                return finish("finished")
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
