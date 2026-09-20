# M019 proposal — task-typed browser agent

Status: accepted. **M019A (deterministic contracts) implemented; M019B
(scripted integration) gate PASSED; M019C (development gate) criteria MET
with the single documented prompt revision `m019c-v2`; M019D (frozen 20-task
evaluation) executed once — productive 10/18, the ≥15/18 product gate NOT met,
results preserved as measured; refusals 2/2 safe, zero forbidden actions.**
The next experiment is a separately approved model comparison, not further
prompt iteration (not started).
Date: 2026-09-20 (Australia/Sydney).

## Why this phase exists

M018 measured three boundaries: screenshot-only control reached 3/18 held-out;
target-assisted control moved a fresh paired set from 1/18 to 6/18; and one
live Hacker News pilot produced no answer after two repeated no-op clicks.

Target IDs fixed some pixel-aim failures, but the remaining failures are now
orchestration failures: target IDs confused with page data, typing before
focus, claims about unsaved forms, wrong target selection, repeated actions
after no change, and unsafe choices on refusal tasks. The HN goal required
reading and answering, yet the agent was offered click actions and clicked.

M019 tests one hypothesis: **trusted task typing and semantic browser actions
can remove avoidable orchestration failures while keeping the same pinned local
model**. It is a separately labelled treatment and does not alter M018 scores.

## Frozen task modes

Trusted code assigns one mode and capability budget before the model sees a
task. The model cannot change either.

| Mode | Allowed | Unavailable |
|---|---|---|
| `answer` | inspect, scroll, wait, structured answer | click, type, submit, external navigation |
| `navigate` | current-target click, back, scroll, wait, finish | typing and form mutation |
| `form` | fill/select/toggle declared fields; authorized local save | credentials, external submit, undeclared fields |
| `stop` | explain why continuation is unsafe | every side effect |

“Find the top three AI stories” is an `answer` task, so clicking is
structurally unavailable.

## Observation and answer contracts

Keep the screenshot and expose only current, visible, viewport-clipped targets:

```json
{
  "observation_id": "opaque-current-snapshot",
  "mode": "navigate",
  "allowed_actions": ["click_target", "scroll", "back", "wait", "finish"],
  "targets": [{
    "target_ref": "ui:17",
    "role": "link",
    "label": "Comments",
    "bounds": [210, 144, 286, 168],
    "enabled": true
  }],
  "last_action": {
    "kind": "click_target",
    "target_ref": "ui:11",
    "result": "no_observable_change"
  }
}
```

Target references always use the `ui:` namespace. Answer fields use explicit
names such as `story_code`, `rank`, `title`, and `points`; a `ui:*` value is
rejected where page data is expected. Hidden DOM text, scripts, passwords,
network data, and off-viewport targets remain excluded.

## Typed actions

- `finish_answer(fields)` — schema chosen by trusted task code;
- `click_target(target_ref, observation_id, expected_change)`;
- `fill_field(target_ref, text, observation_id)` — trusted focus, clear, type,
  and read-back as one bounded operation;
- `select_option(target_ref, option, observation_id)`;
- `set_toggle(target_ref, value, observation_id)`;
- `save_form(target_ref, observation_id)` — only for an explicitly authorized
  fixture-local save;
- `scroll(direction, amount)`, `back()`, `wait()`, or `stop(reason)`.

Raw `click(x,y)` and standalone `type_text` are absent. Existing M018 modes
retain their old schemas for reproducibility.

## Trusted execution rules

1. Resolve targets only against the cited current observation.
2. Reject stale, hidden, disabled, off-viewport, role-changed, or moved targets.
3. `fill_field` must focus, write within budget, and confirm read-back.
4. Form completion requires the independent state oracle after `save_form`.
5. Submit-like targets are absent unless the task authorizes that exact local
   side effect. Credentials and external submissions are always denied.
6. On an unchanged observation, reject the exact same action immediately.
   Return `no_observable_change`; require a different action or stop. Two
   unchanged actions end the task.
7. Completion remains oracle-verified. Structured answers are schema-validated
   before their content is scored.

Do not add an open-ended reflection loop. Each turn contains the goal, mode,
remaining budgets, current observation, and last two action results. For forms,
trusted code may expose a checklist of required field names, but never values.

## Safety invariants

- loopback-only during M019 development;
- zero password typing, external submission, downloads, new tabs, arbitrary
  JavaScript, shell commands, clipboard access, or unrestricted keyboard;
- private screenshots and targets remain ephemeral by default;
- screen text cannot change mode, capabilities, origins, budgets, or oracles;
- any forbidden executed action stops the phase immediately.

## Stages and gates

### M019A — deterministic contracts

Add task modes, capability manifests, action schemas, namespace validation,
compound field operations, and no-repeat-on-unchanged enforcement.

Gate: focused tests cover every allow/deny branch, stale targets, failed
read-back, unsaved forms, target/data confusion, repeated no-ops, credentials,
and external submission. No model runs.

### M019B — scripted integration

Script one answer task, one navigation task, one form task, one moving-target
task, and two refusal tasks. All productive oracles and both refusals must pass
with zero forbidden actions. No model runs.

### M019C — five fresh development smoke tasks

Author after M019A freezes: one read-only ranked-list answer, one named-link
navigation, one two-field local form, one changed-target recovery, and one
credential/external-submit refusal. Run the pinned model once per task.

Proceed only with at least 4/5 expected outcomes, a correct refusal, and zero
forbidden actions. Permit at most one documented prompt revision followed by a
new five-task development set. Never tune on M018 held-out or M018T evaluation.

### M019D — fresh evaluation

Only after M019C passes, freeze 20 new tasks: 18 productive and two refusals,
with no initially satisfied task. Run once. Keep the product gate: at least
15/18 productive, 2/2 refusals, zero forbidden actions, and no human rescue in
successful tasks.

## Cost controls

- reuse pinned Qwen3.5-4B; no model download and no M018 rerun;
- deterministic and scripted gates before inference;
- five model tasks maximum in the first smoke batch;
- no live HN retry during M019A–D;
- stop after any forbidden action, two consecutive infrastructure failures, or
  failure of the scripted safety gate;
- never continue automatically into evaluation.

## Expected implementation files

- `browser_tasks.py`: mode and capability manifest;
- `browser_targets.py`: `ui:` references and submit/credential classification;
- `browser_session.py`: semantic operations and read-back;
- `browser_agent.py`: mode-specific schemas, no-op memory, answer validation;
- `browser_cli.py`: separately labelled M019 commands;
- focused tests and a new M019 invariant test;
- state and learning surfaces only as stages gain observed evidence.

## Decision

Do not move first to a remote or larger model. M018T proved that trusted
scaffolding creates genuine gains with the existing model while exposing a new
safety risk. First test whether M019 removes avoidable orchestration failures.
If M019C fails, stop; the next experiment is a separately approved model
comparison, not more prompt iteration.
