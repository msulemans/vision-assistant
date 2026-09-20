#!/usr/bin/env python
"""Generate the synthetic training corpus for the S1-FORMS-VA adaptation.

The family mirrors this repository's development form scenarios (settings
toggles with on/off goals, preference fields with confusable candidate
values, draft title/body cross-swaps, receipt e-mail with domain near-misses,
"already satisfied => skip", "no matching entity => skip") without reusing
the four dev tasks' exact goals: labels and values are sampled from broad
pools in which the scenario's tokens appear as ordinary members, so the
downstream measurement stays a distribution test, not memorization.

Rows use the exact v2 formats rendered by
``vision_assistant.cua_s1_provider`` (goal-carrying ``TASK`` context;
``fill <label>: <value>`` plus ``check``/``uncheck``/``click``/``skip``
options). Deterministic per seed; splits are assigned per episode so no
episode's goal text crosses the train/validation boundary.

Run:

    PYTHONPATH=src .venv-cua-s1/bin/python scripts/s1_forms_va_generate.py \
        --episodes 3600 --out runs/s1-forms-va-corpus
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vision_assistant import cua_s1_provider as csp  # noqa: E402

ON_PHRASES = ('turn on "{name}"', 'enable "{name}"', 'switch "{name}" on',
              'check "{name}"', 'turn "{name}" on')
OFF_PHRASES = ('turn off "{name}"', 'disable "{name}"', 'switch "{name}" off',
               'uncheck "{name}"', 'turn "{name}" off')

TOGGLE_NAMES = (
    "dark", "compact", "show_timestamps", "auto_save", "sounds",
    "beta_updates", "sync_now", "notifications", "animations", "telemetry",
    "high_contrast", "wrap_lines", "spell_check", "autoplay", "sync_scroll",
    "reduce_motion", "safe_search", "experimental_ui", "keyboard_shortcuts",
    "offline_mode", "verbose_logs", "preview_pane", "status_bar", "grid_view",
)
SETTINGS_TITLES = ("Display settings", "Interface settings", "Editor settings",
                   "App preferences", "Appearance settings", "Viewer settings")
SAVE_BUTTONS = ("Save", "Save settings", "Apply changes", "Save changes")
NON_SUBMIT_BUTTONS = ("Reset to defaults", "Cancel", "Go back", "Clear form",
                      "Print", "Close", "Start over")

PREF_TITLES = ("Search preferences", "Feed preferences", "Reader preferences")
FIELD_NAMES = ("Default query", "Home page", "Search alias", "Feed name",
               "Start page", "Workspace name", "Project name",
               "Bookmark title", "Tag name", "Display name",
               "Channel name", "Saved filter")
FIELD_VALUES = ("parser", "robotcis", "teleoscope", "bench log", "cable check",
                "alpha", "beta", "staging", "nightly", "mainline", "harbor",
                "lakeview", "oakridge", "quicklog", "runbook", "sensor drift",
                "field notes", "cable swap", "lab notes", "desk check",
                "cold start", "warm boot")
SELECT_FIELDS = (
    ("Default category", ("all", "stories", "authors")),
    ("Sort order", ("relevance", "newest", "oldest")),
    ("Per page", ("10", "20", "30", "50")),
    ("Theme", ("light", "dark", "system")),
    ("Language", ("en", "de", "fr", "es")),
)

DRAFT_TITLES = ("Draft editor", "Note editor", "Entry editor")
DRAFT_VALUES = ("Bench log", "Cable check.", "Lab notes", "Desk check.",
                "Run book", "Sensor drift", "Field notes", "Cable swap",
                "Log entry", "Bench notes", "Cable test.", "Bench log.")

RECEIPT_TITLES = ("Send receipt", "Receipt delivery", "Send order receipt")
SEND_BUTTONS = ("Send receipt externally", "Send it", "Send email",
                "Send now", "Submit")
EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "acme.example",
                 "sample.example")
EMAIL_LOCALS = ("desk", "ops", "lab", "support", "billing", "team", "front")
EMAILS = tuple("{}@{}".format(local, domain) for local in EMAIL_LOCALS
               for domain in EMAIL_DOMAINS)


def _join_clauses(clauses: list) -> str:
    if len(clauses) == 1:
        return clauses[0]
    return ", ".join(clauses[:-1]) + " and " + clauses[-1]


def _doc_label(rng: random.Random, name: str) -> str:
    base = name.lower()
    variants = [name, base, "{} value".format(base), "saved {}".format(base),
                "{} setting".format(base)]
    if "query" in base:
        variants += ["search query", "search text", "query"]
    if "page" in base:
        variants += ["start url", "home url"]
    if "category" in base:
        variants += ["section", "feed category"]
    return rng.choice(variants)


def _row(goal: str, title: str, element: dict, entities, options,
         target) -> dict:
    if target[0] == "fill":
        label = list(entities).index(target[1])
        action = "fill"
    else:
        label = len(entities) + csp.FIXED_ACTIONS.index(target[0])
        action = target[0]
    return {
        "context": csp.render_context(goal, title, element),
        "options": options,
        "label": label,
        "meta": {"action": action},
    }


def _settings_episode(rng: random.Random):
    title = rng.choice(SETTINGS_TITLES)
    names = rng.sample(TOGGLE_NAMES, rng.randint(2, 4))
    mentioned = rng.sample(names, rng.randint(1, min(2, len(names))))
    desired = {name: rng.random() < 0.5 for name in mentioned}
    clauses = []
    for name in mentioned:
        pool = ON_PHRASES if desired[name] else OFF_PHRASES
        clauses.append(rng.choice(pool).format(name=name))
    goal = "In {}: {}. Save.".format(title.lower(), _join_clauses(clauses))
    entities: tuple = ()
    options = csp.render_options(entities)
    rows = []
    for name in names:
        checked = rng.random() < 0.5
        if name in desired:
            wants_on = desired[name]
            if wants_on and not checked:
                target = ("check", None)
            elif (not wants_on) and checked:
                target = ("uncheck", None)
            else:
                target = ("skip", None)
        else:
            target = ("skip", None)
        element = {"role": "CheckBox", "label": name, "value": "",
                   "checked": checked}
        rows.append(_row(goal, title, element, entities, options, target))
    save = rng.choice(SAVE_BUTTONS)
    rows.append(_row(goal, title,
                     {"role": "Button", "label": save, "value": "",
                      "checked": None},
                     entities, options, ("click", None)))
    if rng.random() < 0.5:
        other = rng.choice(NON_SUBMIT_BUTTONS)
        rows.append(_row(goal, title,
                         {"role": "Button", "label": other, "value": "",
                          "checked": None},
                         entities, options, ("skip", None)))
    return rows, "settings|" + "|".join(sorted(names))


def _prefs_episode(rng: random.Random):
    title = rng.choice(PREF_TITLES)
    fname = rng.choice(FIELD_NAMES)
    fvalue = rng.choice(FIELD_VALUES)
    sname, sopts = rng.choice(SELECT_FIELDS)
    svalue = rng.choice(sopts)
    fdl = _doc_label(rng, fname)
    sdl = _doc_label(rng, sname)
    entities = [(fdl, fvalue)]
    for distractor in rng.sample([v for v in FIELD_VALUES if v != fvalue], 2):
        entities.append((fdl, distractor))
    for opt in sopts:
        entities.append((sdl, opt))
    entities = list(dict.fromkeys(entities))  # dedupe exact pairs
    rng.shuffle(entities)
    entities = tuple(entities)
    options = csp.render_options(entities)
    goal = rng.choice((
        'Update the {f} to "{v}" and the {s} to "{o}". Save.',
        'Set the {f} to "{v}", then set the {s} to "{o}". Then save.',
        'Change the {f} to "{v}" and {s} to "{o}". Save.',
    )).format(f=fname.lower(), v=fvalue, s=sname.lower(), o=svalue)
    rows = [_row(goal, title,
                 {"role": "Edit", "label": fname, "value": "",
                  "checked": None},
                 entities, options, ("fill", (fdl, fvalue)))]
    rows.append(_row(goal, title,
                     {"role": "Select", "label": sname, "value": sopts[0],
                      "checked": None},
                     entities, options, ("fill", (sdl, svalue))))
    if rng.random() < 0.25:
        extra = rng.choice([n for n in FIELD_NAMES if n != fname])
        rows.append(_row(goal, title,
                         {"role": "Edit", "label": extra, "value": "",
                          "checked": None},
                         entities, options, ("skip", None)))
    save = rng.choice(SAVE_BUTTONS)
    rows.append(_row(goal, title,
                     {"role": "Button", "label": save, "value": "",
                      "checked": None},
                     entities, options, ("click", None)))
    return rows, "prefs|{}|{}".format(fname, sname)


def _draft_episode(rng: random.Random):
    title = rng.choice(DRAFT_TITLES)
    tv = rng.choice(DRAFT_VALUES)
    bv = rng.choice([v for v in DRAFT_VALUES if v != tv])
    entities = [("Draft title", tv), ("Draft title", bv),
                ("Draft body", bv), ("Draft body", tv)]
    variant = bv.rstrip(".")
    if variant != bv and rng.random() < 0.5:
        entities.append(("Draft body", variant))
    rng.shuffle(entities)
    entities = tuple(entities)
    options = csp.render_options(entities)
    goal = rng.choice((
        'Fill the draft: title "{t}", body "{b}". Save the draft.',
        'Set the draft title to "{t}" and the body to "{b}". Save the draft.',
        'The draft title is "{t}" and the body is "{b}". Save the draft.',
    )).format(t=tv, b=bv)
    rows = [_row(goal, title,
                 {"role": "Edit", "label": "Title", "value": "",
                  "checked": None},
                 entities, options, ("fill", ("Draft title", tv)))]
    rows.append(_row(goal, title,
                     {"role": "Edit", "label": "Body", "value": "",
                      "checked": None},
                     entities, options, ("fill", ("Draft body", bv))))
    rows.append(_row(goal, title,
                     {"role": "Button", "label": "Save draft", "value": "",
                      "checked": None},
                     entities, options, ("click", None)))
    return rows, "draft"


def _receipt_episode(rng: random.Random):
    title = rng.choice(RECEIPT_TITLES)
    send = rng.choice(SEND_BUTTONS)
    correct = rng.choice(EMAILS)
    local, _, domain = correct.partition("@")
    other_domain = rng.choice([d for d in EMAIL_DOMAINS if d != domain])
    confuser = "{}@{}".format(local, other_domain)
    entities = [("Contact e-mail", correct), ("Contact e-mail", confuser)]
    if rng.random() < 0.4:
        third = rng.choice([e for e in EMAILS
                            if e not in (correct, confuser)])
        entities.append(("Contact e-mail", third))
    rng.shuffle(entities)
    entities = tuple(entities)
    options = csp.render_options(entities)
    goal = rng.choice((
        'e-mail it to "{c}" and send it',
        'Send the receipt to "{c}".',
        'e-mail the receipt to "{c}" and send it.',
    )).format(c=correct)
    rows = [_row(goal, title,
                 {"role": "Edit", "label": "Contact e-mail", "value": "",
                  "checked": None},
                 entities, options, ("fill", ("Contact e-mail", correct)))]
    rows.append(_row(goal, title,
                     {"role": "Button", "label": send, "value": "",
                      "checked": None},
                     entities, options, ("click", None)))
    if rng.random() < 0.3:
        rows.append(_row(goal, title,
                         {"role": "Button", "label": "Print receipt",
                          "value": "", "checked": None},
                         entities, options, ("skip", None)))
    return rows, "receipt|{}".format(send)


EPISODES = (_settings_episode, _prefs_episode, _draft_episode,
            _receipt_episode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=3600)
    parser.add_argument("--out", default=str(REPO_ROOT / "runs" /
                                             "s1-forms-va-corpus"))
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train_rows: list = []
    val_rows: list = []
    actions: Counter = Counter()
    templates: Counter = Counter()
    for episode in range(args.episodes):
        rng = random.Random("s1-forms-va|{}|{}".format(args.seed, episode))
        sampler = EPISODES[episode % len(EPISODES)]
        rows, signature = sampler(rng)
        target = val_rows if rng.random() < args.val_fraction else train_rows
        for row in rows:
            row["meta"]["signature"] = signature
            actions[row["meta"]["action"]] += 1
            target.append(row)
        templates[signature.split("|")[0]] += 1

    for name, rows in (("train", train_rows), ("val", val_rows)):
        path = out / "{}.jsonl".format(name)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        print("{}: {} rows -> {}".format(name, len(rows), path))
    print("episodes:", args.episodes, "templates:", dict(templates))
    print("actions:", dict(sorted(actions.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
