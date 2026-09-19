# M018A evidence — 50-task manifest, oracles, and fixture/reset contracts

Date: 2026-09-20 (Australia/Sydney). Stage: M018A (manifest and oracles).
Model runs: 0. Browser sessions: 0. Downloads: none.

## What was built

- `src/vision_assistant/browser_fixtures.py` — two independent fixture
  instances (`dev`, `heldout`), 18 stories each across three pages, authors,
  topics, deterministic dates, comments, story codes (`SC-<instance>-<sid>-<hash4>`),
  search semantics (token match, phrase match for multiword queries), plus the
  full page generator. Site builds: dev 78 files / heldout 79 files, both
  byte-identical on rebuild. Content hashes: dev `a2ec11c1ab342878…`, heldout
  `62e19c50eac0ced1…` (full SHA-256s in the manifest JSON).
- `src/vision_assistant/fixture_server.py` — loopback-only stdlib server for
  the generated site: static pages, dynamic search rendering, form saves
  (prefs/draft/settings), the flaky retry page, submissions log (counts only —
  field values are never stored), evaluator-only `/__state` and `/__reset`
  (reset restores defaults; `?seed=<task>` applies that task's frozen start
  state).
- `src/vision_assistant/browser_tasks.py` — frozen limits (20 steps, 25 model
  calls, 120 s, ≤2 consecutive recoveries, 1 run per task, stop after 3
  consecutive infrastructure failures), the typed action schema
  (navigate/click/type_text/press_key/scroll/back/wait/finish/stop with strict
  field checks), the 50-task manifest (30 development / 20 held-out), and the
  independent oracles with positive/negative state generators.
- `src/vision_assistant/browser_cli.py` — `manifest`, `verify`, `site`, `serve`.

## Deterministic gate (`browser_cli verify`)

- Schema: **22/22 adversarial payloads rejected** (unknown kinds, non-object
  payloads, string coordinates, missing/stale screenshots, out-of-viewport and
  negative clicks, foreign origins, protocol-relative and `file` schemes,
  overlong URLs and text, control characters, banned keys, bad scroll values,
  malformed finish answers, negative waits).
- Oracles: **50/50 correct final states pass; 157/157 wrong final states are
  rejected** (wrong URL/query, missing visits, wrong or missing answers,
  defaulted or field-wrong forms, forged success on refusal tasks, and every
  zero-tolerance counter violation).
- Manifest: deterministic (stable SHA-256 across runs; content hashes pinned).
- Fixtures: both instances rebuild **byte-identical**.

Report: `docs/evidence/2026-09-20-m018a-verify.json` (`ok: true`).
Manifest: `docs/evidence/2026-09-20-m018a-manifest.json`.

## Frozen content truths used by oracles (examples)

- Dev highest-ranked AI story: rank 2, "New open model sets a small-vision
  benchmark record" (`d02`). Held-out top three AI stories: `h01`, `h03`, `h07`.
- Held-out decoy `h05` ("AIrline cockpit software gets a redesign") is not an
  AI-subject story; duplicate-title pair `h11`/`h12` ("Model cards considered
  harmful"); "Quantum bread baking" is absent by design (abstention task).
- Search `ai` (dev) matches `d02`, `d11`, `d15`; `robotics` matches `d09`;
  phrase search finds `h08`; `zzzz` has no results; author search finds
  `mira-chen` (held-out).

## Teeth found real bugs during the build (fixed)

1. The `url_wrong` mutation compared a normalized path against a
   non-normalized literal, so for `/news/` it produced the *correct* URL and
   the mutation was wrongly accepted — the gate caught it, the comparison was
   fixed, and 4 previously-accepted mutations now fail closed.
2. The stale-screenshot adversarial probe called `validate_action` without a
   current `screenshot_id`, so the stale click was accepted; the probe now
   passes context and the stale click is rejected.
3. `FixtureServer.reset()` deadlocked (a plain `Lock` re-acquired via
   `snapshot()`), found by the first server test run under a faulthandler
   traceback dump; reset now copies state inline under the lock.
4. The `base_url` template literal (`"http://{}…"`) tripped the frozen M015
   offline audit because loopback-prefix stripping cannot match a template;
   the URL is now assembled from parts (still loopback-only, confirmed by the
   offline audit tests).

## Reproduction

```
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli verify
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli manifest --out runs/m018/m018a-manifest.json
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p "test_browser_tasks.py"
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p "test_fixture_server.py"
```

## Interpretation and honest boundaries

This stage makes the benchmark *reviewable*: tasks, oracles, and fixture state
are frozen and independently validated. It does **not** measure any model. No
task completion rate, refusal accuracy, or Hacker News result is claimed yet;
those belong to M018C–E after the browser adapter (M018B) exists. Smoke tasks
01, 11, 21, 31, 41 are frozen for the five-task M018C smoke stage.
