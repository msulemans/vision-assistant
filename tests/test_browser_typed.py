"""M019A focused tests: manifests, ui: namespace, typed validation, answer
schemas, semantic session operations (protocol-level fake helper), and the
typed agent loop (no-repeat, credential/submission denials). Deterministic:
no model, no browser, no fixture server, no network.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from vision_assistant import browser_agent as agent
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks
from vision_assistant import browser_session as bs
from vision_assistant.browser_session import BrowserError, Snapshot, TargetList


def _make_png(width: int = 64, height: int = 36) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _entry(tid, role, label):
    return {"id": tid, "role": role, "label": label,
            "rect": [10.0, 10.0, 200.0, 24.0], "enabled": True, "focused": False}


DEFAULT_TARGETS = [
    _entry("t1", "text_input", "Query"),
    _entry("t2", "button", "Save"),
    _entry("t3", "select", "Per page"),
    _entry("t4", "checkbox", "Enable sync"),
    _entry("t5", "text_input", "Password"),
]


# ----------------------------------------------------------------- validators

class ManifestTest(unittest.TestCase):
    def test_capability_manifests_are_frozen(self) -> None:
        self.assertEqual(tasks.TYPED_MODES, ("answer", "navigate", "form", "stop"))
        self.assertEqual(tasks.MODE_CAPABILITIES, {
            "answer": ("scroll", "wait", "finish_answer", "stop"),
            "navigate": ("click_target", "back", "scroll", "wait", "finish",
                         "stop"),
            "form": ("fill_field", "select_option", "set_toggle", "save_form",
                     "scroll", "wait", "stop"),
            "stop": ("stop",),
        })
        for mode in tasks.TYPED_MODES:
            manifest = tasks.capability_manifest(mode)
            allowed = set(manifest["allowed_actions"])
            unavailable = set(manifest["unavailable_actions"])
            self.assertEqual(allowed & unavailable, set())
            self.assertEqual(allowed | unavailable, set(tasks.TYPED_ACTIONS))

    def test_namespace_helpers(self) -> None:
        self.assertTrue(bt.valid_ui_ref("ui:1"))
        self.assertTrue(bt.valid_ui_ref("ui:999"))
        for bad in ("t3", "ui:", "ui:0", "ui:03", "ui:1000", "UI:1", 7, None):
            self.assertFalse(bt.valid_ui_ref(bad), bad)
        self.assertEqual(bt.ui_ref_for("t3"), "ui:3")
        self.assertEqual(bt.ui_ref_for("t26"), "ui:26")
        self.assertEqual(bt.ui_ref_for("nope"), "")

    def test_typed_target_block_uses_ui_namespace_only(self) -> None:
        entries = (
            bt.TargetEntry("t1", "link", "Story one", (16.0, 100.0, 400.0, 20.0),
                           True, False),
            bt.TargetEntry("t2", "button", "Save", (600.0, 300.0, 80.0, 24.0),
                           True, False),
        )
        block = bt.render_typed_target_block(entries, 1280, 720, 2560, 1440, 2.0)
        self.assertIn('"target_ref": "ui:1"', block)
        self.assertIn('"target_ref": "ui:2"', block)
        self.assertIn('"bounds"', block)
        self.assertNotIn('"id"', block)

    def test_classification_uses_word_boundaries(self) -> None:
        self.assertTrue(bt.classify_control("text_input", "Password")["credential"])
        self.assertFalse(bt.classify_control("button", "Subtract")["submit_like"])
        self.assertFalse(bt.classify_control("link", "Card games")["submit_like"])
        self.assertTrue(bt.classify_control("button", "Submit order")["submit_like"])
        self.assertTrue(bt.classify_control("link", "Sign in")["submit_like"])
        self.assertFalse(bt.classify_control("link", "Story one")["submit_like"])
        self.assertTrue(bt.submit_authorized("ui:3", ("ui:3", "ui:4")))
        self.assertFalse(bt.submit_authorized("ui:5", ("ui:3",)))


def _targets():
    return (
        bt.TargetEntry("t1", "text_input", "Query", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t2", "text_input", "Password", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t3", "button", "Save", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t4", "link", "Story", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t5", "select", "Per page", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t6", "checkbox", "Enable", (0.0, 0.0, 10.0, 10.0), True, False),
        bt.TargetEntry("t7", "button", "Submit", (0.0, 0.0, 10.0, 10.0), True, False),
    )


OBS = "obs-1"


class TypedValidationTest(unittest.TestCase):
    def _validate(self, payload, mode, authorized=(), schema=None):
        return tasks.validate_typed_action(
            payload, mode=mode, observation_id=OBS, targets=_targets(),
            authorized_saves=authorized, answer_schema=schema)

    def test_allow_branches(self) -> None:
        cases = (
            ("answer", {"kind": "scroll", "direction": "down", "amount": 2}),
            ("answer", {"kind": "wait", "seconds": 2}),
            ("answer", {"kind": "finish_answer", "answer": {"rank": 2}}),
            ("answer", {"kind": "stop", "reason": "needs a login"}),
            ("navigate", {"kind": "click_target", "target_ref": "ui:4",
                          "observation_id": OBS, "expected_change": "url_change"}),
            ("navigate", {"kind": "back"}),
            ("navigate", {"kind": "finish"}),
            ("form", {"kind": "fill_field", "target_ref": "ui:1", "text": "hello",
                      "observation_id": OBS}),
            ("form", {"kind": "select_option", "target_ref": "ui:5",
                      "option": "50", "observation_id": OBS}),
            ("form", {"kind": "set_toggle", "target_ref": "ui:6", "value": True,
                      "observation_id": OBS}),
            ("form", {"kind": "save_form", "target_ref": "ui:3",
                      "observation_id": OBS}),
            ("stop", {"kind": "stop"}),
        )
        for mode, payload in cases:
            authorized = ("ui:3",) if payload.get("kind") == "save_form" else ()
            parsed, error = self._validate(payload, mode, authorized)
            self.assertIsNone(error, (mode, payload, error))
            self.assertEqual(parsed["kind"], payload["kind"])

    def test_raw_actions_are_absent_in_every_mode(self) -> None:
        raws = (
            {"kind": "click", "x": 1, "y": 2},
            {"kind": "type_text", "text": "hello"},
            {"kind": "navigate", "url": "/news/"},
        )
        for mode in tasks.TYPED_MODES:
            for payload in raws:
                _parsed, error = self._validate(payload, mode)
                self.assertIsNotNone(error, (mode, payload))

    def test_mode_gating(self) -> None:
        denied = (
            ("answer", {"kind": "click_target", "target_ref": "ui:4",
                        "observation_id": OBS}),
            ("answer", {"kind": "back"}),
            ("navigate", {"kind": "fill_field", "target_ref": "ui:1",
                          "text": "x", "observation_id": OBS}),
            ("navigate", {"kind": "finish_answer", "answer": {"rank": 1}}),
            ("form", {"kind": "finish"}),
            ("form", {"kind": "back"}),
            ("stop", {"kind": "click_target", "target_ref": "ui:4",
                      "observation_id": OBS}),
            ("stop", {"kind": "finish_answer", "answer": {"rank": 1}}),
        )
        for mode, payload in denied:
            _parsed, error = self._validate(payload, mode)
            self.assertIsNotNone(error, (mode, payload))
            self.assertIn("not available", error)

    def test_target_and_observation_rules(self) -> None:
        payload = {"kind": "click_target", "target_ref": "t4",
                   "observation_id": OBS}
        self.assertIn("ui:3", self._validate(payload, "navigate")[1])
        payload = {"kind": "click_target", "target_ref": "ui:99",
                   "observation_id": OBS}
        self.assertIn("unknown target_ref", self._validate(payload, "navigate")[1])
        payload = {"kind": "click_target", "target_ref": "ui:4",
                   "observation_id": "obs-9"}
        self.assertIn("stale observation", self._validate(payload, "navigate")[1])
        payload = {"kind": "click_target", "target_ref": "ui:4"}
        self.assertIn("missing field", self._validate(payload, "navigate")[1])
        payload = {"kind": "click_target", "target_ref": "ui:4",
                   "observation_id": OBS, "z": 1}
        self.assertIn("unexpected field", self._validate(payload, "navigate")[1])

    def test_role_checks(self) -> None:
        cases = (
            ("form", {"kind": "fill_field", "target_ref": "ui:4", "text": "x",
                      "observation_id": OBS}, "fill_field needs a text field"),
            ("form", {"kind": "select_option", "target_ref": "ui:6",
                      "option": "50", "observation_id": OBS},
             "select_option needs a select"),
            ("form", {"kind": "set_toggle", "target_ref": "ui:5", "value": True,
                      "observation_id": OBS}, "set_toggle needs a checkbox"),
            ("navigate", {"kind": "click_target", "target_ref": "ui:1",
                          "observation_id": OBS}, "click_target needs a link"),
        )
        for mode, payload, needle in cases:
            _parsed, error = self._validate(payload, mode)
            self.assertIsNotNone(error)
            self.assertIn(needle, error)

    def test_credentials_and_submissions_are_denied(self) -> None:
        payload = {"kind": "fill_field", "target_ref": "ui:2", "text": "hunter2",
                   "observation_id": OBS}
        self.assertIn("refused_credential", self._validate(payload, "form")[1])
        payload = {"kind": "click_target", "target_ref": "ui:2",
                   "observation_id": OBS}
        self.assertIn("refused_credential", self._validate(payload, "navigate")[1])
        payload = {"kind": "click_target", "target_ref": "ui:7",
                   "observation_id": OBS}
        self.assertIn("refused_unauthorized_save",
                      self._validate(payload, "navigate")[1])
        payload = {"kind": "save_form", "target_ref": "ui:3",
                   "observation_id": OBS}
        self.assertIn("refused_unauthorized_save",
                      self._validate(payload, "form")[1])
        _parsed, error = self._validate(payload, "form", authorized=("ui:3",))
        self.assertIsNone(error)

    def test_value_rules(self) -> None:
        cases = (
            ("form", {"kind": "set_toggle", "target_ref": "ui:6", "value": "yes",
                      "observation_id": OBS}),
            ("form", {"kind": "select_option", "target_ref": "ui:5", "option": "",
                      "observation_id": OBS}),
            ("form", {"kind": "fill_field", "target_ref": "ui:1",
                      "text": "bad\x07char", "observation_id": OBS}),
            ("answer", {"kind": "scroll", "direction": "left", "amount": 2}),
            ("answer", {"kind": "scroll", "direction": "down", "amount": 0}),
            ("answer", {"kind": "wait", "seconds": -1}),
            ("navigate", {"kind": "click_target", "target_ref": "ui:4",
                          "observation_id": OBS, "expected_change": "vibes"}),
        )
        for mode, payload in cases:
            _parsed, error = self._validate(payload, mode)
            self.assertIsNotNone(error, (mode, payload))


class AnswerSchemaTest(unittest.TestCase):
    def test_schema_rules(self) -> None:
        schema = tasks.answer_schema(
            {"rank": {"type": "integer"}, "title": {"type": "string"},
             "stories": {"type": "list"}},
            required=("rank", "title"))
        clean, error = tasks.validate_structured_answer(
            {"rank": 2, "title": "Hello", "stories": [{"rank": 1, "code": "SC-1"}]},
            schema)
        self.assertIsNone(error)
        self.assertEqual(clean["rank"], 2)
        bad = (
            ({"rank": 2}, "missing answer field"),
            ({"rank": 2, "title": "Hi", "extra": 1}, "unexpected answer field"),
            ({"rank": "two", "title": "Hi"}, "must be of type integer"),
            ({}, "non-empty"),
            ({"rank": True, "title": "Hi"}, "must be of type integer"),
        )
        for answer, needle in bad:
            _clean, error = tasks.validate_structured_answer(answer, schema)
            self.assertIsNotNone(error, answer)
            self.assertIn(needle, error)

    def test_ui_references_are_never_page_data(self) -> None:
        _clean, error = tasks.validate_structured_answer({"title": "ui:3"})
        self.assertIn("ui: target reference", error)
        _clean, error = tasks.validate_structured_answer({"title": "ui:3"})
        self.assertIn("ui: target reference", error)
        _clean, error = tasks.validate_structured_answer(
            {"story_code": "t6", "rank": 2})
        self.assertIn("target id", error)
        mode_clean, error = tasks.validate_typed_action(
            {"kind": "finish_answer", "answer": {"stories": [{"code": "ui:2"}]}},
            mode="answer")
        self.assertIsNone(mode_clean)
        self.assertIn("ui: target reference", error)
        _clean, error = tasks.validate_structured_answer(
            {"stories": [{"code": "SC-ok"}]})
        self.assertIsNone(error)

    def test_list_limits(self) -> None:
        too_many = {"stories": [{"rank": i} for i in range(21)]}
        _clean, error = tasks.validate_structured_answer(too_many)
        self.assertIn("too many items", error)


class VerifyTypedTaskTest(unittest.TestCase):
    def _spec(self, **kw):
        base = dict(id="m19-t01", split="D", mode="navigate", instance="dev",
                    goal="g", start="/news/")
        base.update(kw)
        return tasks.TypedTaskSpec(**base)

    def _state(self, **kw):
        state = {"url": "/news/", "answer": None, "outcome": "finished",
                 "visited": [], "external_visits": 0, "credential_typed": False,
                 "submission_attempts": 0}
        state.update(kw)
        return state

    def test_refusal_tasks(self) -> None:
        spec = self._spec(mode="stop", refusal=True)
        self.assertTrue(tasks.verify_typed_task(spec, self._state(outcome="stopped"))["ok"])
        self.assertTrue(tasks.verify_typed_task(
            spec, self._state(outcome="blocked:no_progress"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, self._state(outcome="finished"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, self._state(outcome="stopped",
                              submission_attempts=1))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, self._state(outcome="stopped", credential_typed=True))["ok"])

    def test_answer_and_url_checks(self) -> None:
        spec = self._spec(mode="answer", expected={"answer": {"rank": 2}})
        self.assertTrue(tasks.verify_typed_task(
            spec, self._state(answer={"rank": 2, "title": "x"}))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, self._state(answer={"rank": 3}))["ok"])
        spec = self._spec(expected={"url": "/story/d03/"})
        self.assertFalse(tasks.verify_typed_task(spec, self._state())["ok"])
        self.assertTrue(tasks.verify_typed_task(
            spec, self._state(url="/story/d03/"))["ok"])

    def test_form_check(self) -> None:
        spec = self._spec(mode="form", expected={
            "form": {"section": "prefs", "values": {"per_page": "50"}}})
        good = self._state(form_state={"prefs": {"per_page": "50"}})
        bad = self._state(form_state={"prefs": {"per_page": "20"}})
        self.assertTrue(tasks.verify_typed_task(spec, good)["ok"])
        self.assertFalse(tasks.verify_typed_task(spec, bad)["ok"])


# --------------------------------------------------- session operations
# Protocol-level fake helper: the BrowserSession under test is the real one.

FAKE_M019_HELPER = r'''
import json, os, sys

log_path = os.environ.get("FAKE_LOG", "")
targets_json = os.environ.get("FAKE_TARGETS", "")
targets_list = json.loads(targets_json) if targets_json else []
fill_readback = os.environ.get("FAKE_FILL_READBACK", "")
fill_error = os.environ.get("FAKE_FILL_ERROR", "")
select_value = os.environ.get("FAKE_SELECT_VALUE", "")
option_error = os.environ.get("FAKE_OPTION_ERROR", "")
toggle_checked = os.environ.get("FAKE_TOGGLE_CHECKED", "")
current_seq = 0

def log(text):
    if log_path:
        with open(log_path, "a") as fh:
            fh.write(text + "\n")

def send(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()

send({"ok": True, "event": "ready", "port": 0, "css_width": 1280, "css_height": 720})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    cmd = req.get("cmd")
    rid = req.get("id")
    log(cmd)
    if cmd == "quit":
        send({"id": rid, "ok": True}); break
    if cmd == "navigate":
        url = req.get("url", "")
        if url.startswith("/"):
            url = "http://127.0.0.1:1" + url
        send({"id": rid, "ok": True, "url": url})
    elif cmd == "snapshot":
        current_seq += 1
        with open(req["path"], "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\nfakedata")
        send({"id": rid, "ok": True, "seq": current_seq, "width": 2560,
              "height": 1440, "scale": 2.0, "url": "http://127.0.0.1:1/news/"})
    elif cmd == "targets":
        send({"id": rid, "ok": True, "seq": current_seq,
              "total": len(targets_list), "truncated": False,
              "targets": targets_list})
    elif cmd == "fill":
        if fill_error:
            send({"id": rid, "ok": False, "error": fill_error})
        else:
            value = req.get("value", "")
            send({"id": rid, "ok": True,
                  "value": fill_readback if fill_readback else value})
    elif cmd == "set_control":
        mode = req.get("mode")
        if mode == "select":
            if option_error:
                send({"id": rid, "ok": False, "error": option_error})
            else:
                send({"id": rid, "ok": True,
                      "value": select_value or req.get("option", "")})
        elif mode == "toggle":
            want = bool(req.get("value"))
            got = want if not toggle_checked else toggle_checked == "true"
            send({"id": rid, "ok": True, "checked": got})
        else:
            send({"id": rid, "ok": False, "error": "bad_request"})
    elif cmd == "click_target":
        if int(req.get("seq", -1)) != current_seq:
            send({"id": rid, "ok": False, "error": "refused_target_stale"})
        else:
            send({"id": rid, "ok": True,
                  "url": "http://127.0.0.1:1/story/d03/"})
    elif cmd == "state":
        send({"id": rid, "ok": True, "seq": current_seq,
              "focused": {"editable": True, "password": False}})
    else:
        send({"id": rid, "ok": False, "error": "unknown_command"})
'''


class SessionOpsBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake = self.tmp / "fake_m019.py"
        self.fake.write_text(FAKE_M019_HELPER, encoding="utf-8")
        self.log = self.tmp / "commands.log"
        self._session = None
        self._env_keys = ("FAKE_LOG", "FAKE_TARGETS", "FAKE_FILL_READBACK",
                          "FAKE_FILL_ERROR", "FAKE_SELECT_VALUE",
                          "FAKE_OPTION_ERROR", "FAKE_TOGGLE_CHECKED")

    def tearDown(self) -> None:
        if self._session is not None:
            self._session.stop()
        for key in self._env_keys:
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def make_session(self, targets=None, **config) -> bs.BrowserSession:
        os.environ["FAKE_LOG"] = str(self.log)
        if targets is not None:
            os.environ["FAKE_TARGETS"] = json.dumps(targets)
        session = bs.BrowserSession(
            port=1, helper_cmd=[sys.executable, str(self.fake)],
            snapshot_dir=self.tmp / "shots", **config)
        self._session = session
        session.launch()
        session.navigate("/news/")
        session.snapshot()
        session.targets()
        return session

    def commands(self):
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text().splitlines() if line]


class FillFieldTest(SessionOpsBase):
    def test_fill_happy_path_reads_back(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        self.assertEqual(session.observation_id, "obs-1")
        self.assertEqual(session.fill_field("ui:1", "hello", "obs-1"), "hello")
        self.assertIn("fill", self.commands())
        # one step for the setup navigate, one for the fill
        self.assertEqual(session.steps_used, 2)

    def test_fill_read_back_failure(self) -> None:
        os.environ["FAKE_FILL_READBACK"] = "MISMATCH"
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:1", "hello", "obs-1")
        self.assertEqual(caught.exception.reason, "read_back_failed")

    def test_fill_credential_label_never_reaches_the_helper(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:5", "hunter2", "obs-1")
        self.assertEqual(caught.exception.reason, "refused_credential")
        self.assertNotIn("fill", self.commands())
        self.assertEqual(session.steps_used, 1)  # setup navigate only

    def test_fill_stale_observation_refused(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:1", "hello", "obs-99")
        self.assertEqual(caught.exception.reason, "refused_target_stale")
        self.assertNotIn("fill", self.commands())

    def test_fill_role_mismatch_refused(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:2", "hello", "obs-1")
        self.assertEqual(caught.exception.reason, "refused_target_role")

    def test_fill_helper_reports_password_field(self) -> None:
        os.environ["FAKE_FILL_ERROR"] = "password_field"
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:1", "hello", "obs-1")
        self.assertEqual(caught.exception.reason, "password_field")

    def test_fill_consumes_the_action_budget(self) -> None:
        session = self.make_session(DEFAULT_TARGETS, max_steps=2)
        self.assertEqual(session.fill_field("ui:1", "a", "obs-1"), "a")
        with self.assertRaises(BrowserError) as caught:
            session.fill_field("ui:1", "b", "obs-1")
        self.assertEqual(caught.exception.reason, "budget_steps")


class SelectToggleTest(SessionOpsBase):
    def test_select_option_happy(self) -> None:
        os.environ["FAKE_SELECT_VALUE"] = "50"
        session = self.make_session(DEFAULT_TARGETS)
        self.assertEqual(session.select_option("ui:3", "50", "obs-1"), "50")
        self.assertIn("set_control", self.commands())

    def test_select_option_not_found(self) -> None:
        os.environ["FAKE_OPTION_ERROR"] = "option_not_found"
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.select_option("ui:3", "9000", "obs-1")
        self.assertEqual(caught.exception.reason, "option_not_found")

    def test_set_toggle_happy_and_read_back_failure(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        self.assertIs(session.set_toggle("ui:4", True, "obs-1"), True)
        session.stop()
        self._session = None
        os.environ["FAKE_TOGGLE_CHECKED"] = "false"
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.set_toggle("ui:4", True, "obs-1")
        self.assertEqual(caught.exception.reason, "read_back_failed")


class SaveFormTest(SessionOpsBase):
    def test_unauthorized_save_never_reaches_the_helper(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        with self.assertRaises(BrowserError) as caught:
            session.save_form("ui:2", "obs-1", authorized_saves=())
        self.assertEqual(caught.exception.reason, "refused_unauthorized_save")
        self.assertNotIn("click_target", self.commands())

    def test_authorized_save_clicks_the_declared_control(self) -> None:
        session = self.make_session(DEFAULT_TARGETS)
        session.save_form("ui:2", "obs-1", authorized_saves=("ui:2",))
        self.assertIn("click_target", self.commands())


# ------------------------------------------------------------- typed agent

class FakeTypedSession:
    width = 1280
    height = 720

    def __init__(self, tmp: Path, urls, target_factory=None, store=None):
        self.tmp = tmp
        self.urls = list(urls)
        self.calls: list = []
        self.seq = 0
        self.target_factory = target_factory
        self.store = store if store is not None else {"submissions": []}
        self.save_effect = None
        self.fail_fill = None

    def _targets(self) -> TargetList:
        if self.target_factory is not None:
            return self.target_factory(self.seq)
        entries = (
            bt.TargetEntry("t1", "text_input", "Query", (10.0, 10.0, 200.0, 24.0),
                           True, False),
            bt.TargetEntry("t2", "button", "Save", (10.0, 60.0, 80.0, 24.0),
                           True, False),
            bt.TargetEntry("t3", "link", "Story one", (10.0, 100.0, 300.0, 20.0),
                           True, False),
        )
        return TargetList(seq=self.seq, targets=entries, truncated=False,
                          total=len(entries))

    def navigate(self, url: str) -> str:
        self.calls.append(("navigate", url))
        return "http://127.0.0.1:1" + url if url.startswith("/") else url

    def snapshot(self) -> Snapshot:
        self.seq += 1
        url = self.urls.pop(0) if self.urls else "http://127.0.0.1:1/news/"
        path = self.tmp / "shot-{}.png".format(self.seq)
        path.write_bytes(_make_png())
        return Snapshot(seq=self.seq, width=2560, height=1440, scale=2.0,
                        url=url, path=str(path))

    def targets(self) -> TargetList:
        return self._targets()

    def click_target(self, target_id: str, method=None) -> str:
        self.calls.append(("click_target", target_id, method))
        return ""

    def fill_field(self, ref: str, text: str, observation_id: str) -> str:
        if self.fail_fill:
            raise BrowserError(self.fail_fill)
        self.calls.append(("fill_field", ref, text))
        return text

    def select_option(self, ref: str, option: str, observation_id: str) -> str:
        self.calls.append(("select_option", ref, option))
        return option

    def set_toggle(self, ref: str, value: bool, observation_id: str) -> bool:
        self.calls.append(("set_toggle", ref, value))
        return value

    def save_form(self, ref: str, observation_id: str, authorized_saves=()) -> str:
        self.calls.append(("save_form", ref))
        if self.save_effect is not None:
            self.save_effect(self.store)
        return ""

    def click(self, px: int, py: int) -> str:
        self.calls.append(("click", px, py))
        return ""

    def type_text(self, text: str) -> int:
        self.calls.append(("type_text", text))
        return len(text)

    def press_key(self, key: str) -> None:
        self.calls.append(("press", key))

    def scroll(self, direction: str, amount: int) -> int:
        self.calls.append(("scroll", direction, amount))
        return amount

    def back(self) -> str:
        self.calls.append(("back",))
        return ""

    def stop(self) -> None:
        pass


def _obs_from(prompt: str) -> str:
    for token in prompt.split():
        if token.startswith("obs-"):
            return token.strip(".,")
    return ""


class TypedProposer:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts: list = []

    def __call__(self, png_bytes, prompt):
        self.prompts.append(prompt)
        if not self.actions:
            return None, {"chars": 0}
        item = self.actions.pop(0)
        if callable(item):
            item = item(prompt)
        return item, {"chars": 42}


def _spec(mode, **kw):
    base = dict(id="m19-t01", split="D", mode=mode, instance="dev",
                goal="Do the thing.", start="/news/")
    base.update(kw)
    return tasks.TypedTaskSpec(**base)


def _click(ref):
    return lambda prompt: {"action": "click_target", "target_ref": ref,
                           "observation_id": _obs_from(prompt)}


def _fill(ref, text):
    return lambda prompt: {"action": "fill_field", "target_ref": ref,
                           "text": text, "observation_id": _obs_from(prompt)}


def _toggle(ref, value):
    return lambda prompt: {"action": "set_toggle", "target_ref": ref,
                           "value": value, "observation_id": _obs_from(prompt)}


def _save(ref):
    return lambda prompt: {"action": "save_form", "target_ref": ref,
                           "observation_id": _obs_from(prompt)}


class TypedLoopBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_typed(self, spec, actions, urls, target_factory=None, store=None,
                  save_effect=None, **limits):
        session = FakeTypedSession(self.tmp, urls, target_factory, store)
        session.save_effect = save_effect
        proposer = TypedProposer(actions)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=lambda: session.store,
            sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
            limits=agent.LoopLimits(**limits) if limits else None,
            mode="typed",
        )
        return session, proposer, report


class TypedLoopTest(TypedLoopBase):
    def test_typed_mode_needs_a_typed_spec(self) -> None:
        spec = tasks.TASKS_BY_ID["01"]
        with self.assertRaises(ValueError):
            self.run_typed(spec, [{"action": "stop"}], ["http://127.0.0.1:1/news/"])

    def test_answer_mode_prompt_and_finish(self) -> None:
        spec = _spec("answer",
                     answer_schema=tasks.answer_schema(
                         {"rank": {"type": "integer"},
                          "title": {"type": "string"}},
                         required=("rank", "title")),
                     expected={"answer": {"rank": 2, "title": "Hello"}})
        session, proposer, report = self.run_typed(
            spec,
            [{"action": "finish_answer",
              "answer": {"rank": 2, "title": "Hello"}}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["mode"], "typed")
        self.assertEqual(report["task_mode"], "answer")
        self.assertEqual(report["prompt_version"], agent.TYPED_PROMPT_VERSION)
        prompt = proposer.prompts[0]
        self.assertIn("Task mode: answer", prompt)
        self.assertIn("Allowed actions in this mode: scroll, wait, "
                      "finish_answer, stop", prompt)
        self.assertIn('"target_ref": "ui:1"', prompt)
        self.assertIn("Answer fields (names only", prompt)
        self.assertIn("rank, title", prompt)
        self.assertNotIn(("click", 0, 0), session.calls)

    def test_typed_prompt_includes_exact_action_shapes(self) -> None:
        entries = (
            bt.TargetEntry("t2", "text_input", "Query",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t5", "select", "20",
                           (0.0, 0.0, 10.0, 10.0), True, False),
        )
        block = bt.render_typed_target_block(entries, 1280, 720, 2560, 1440, 2.0)
        form_prompt = agent.build_typed_prompt(
            "g", "form", 1280, 720, 1280, 720, "obs-4", block, [])
        self.assertIn('"action":"fill_field","target_ref":"ui:2",'
                      '"text":"hello","observation_id":"obs-4"', form_prompt)
        self.assertIn('"action":"select_option","target_ref":"ui:5",'
                      '"option":"30"', form_prompt)
        self.assertIn("field named text", form_prompt)
        answer_prompt = agent.build_typed_prompt(
            "g", "answer", 1280, 720, 1280, 720, "obs-4", block, [])
        self.assertIn('"action":"finish_answer"', answer_prompt)
        self.assertNotIn("fill_field", answer_prompt)

    def test_answer_mode_click_is_structurally_unavailable(self) -> None:
        spec = _spec("answer")
        session, _proposer, report = self.run_typed(
            spec,
            [{"action": "click_target", "target_ref": "ui:3",
              "observation_id": "obs-1"},
             {"action": "stop", "reason": "cannot click in answer mode"}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "stopped")
        self.assertEqual([c for c in session.calls if c[0] == "click_target"], [])
        rejected = [step for step in report["steps"]
                    if step.get("kind") == "proposal" and not step.get("parsed")]
        self.assertTrue(rejected)
        self.assertIn("not available", rejected[0]["error"])

    def test_ui_value_in_answer_is_rejected(self) -> None:
        spec = _spec("answer")
        _session, _proposer, report = self.run_typed(
            spec,
            [{"action": "finish_answer", "answer": {"title": "ui:3"}},
             {"action": "stop"}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "stopped")
        rejected = [step for step in report["steps"]
                    if step.get("kind") == "proposal" and not step.get("parsed")]
        self.assertIn("ui: target reference", rejected[0]["error"])

    def test_navigate_repeat_on_unchanged_is_refused_then_ends(self) -> None:
        spec = _spec("navigate", expected={"url": "/story/d03/"})
        session, _proposer, report = self.run_typed(
            spec,
            [_click("ui:3"), _click("ui:3")],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "blocked:no_progress")
        clicks = [c for c in session.calls if c[0] == "click_target"]
        self.assertEqual(clicks, [("click_target", "t3", "dom")])
        errors = [step.get("error") for step in report["steps"]
                  if step.get("kind") == "proposal"]
        self.assertIn("no_observable_change", errors)
        self.assertTrue(any(step.get("kind") == "no_change"
                            for step in report["steps"]))

    def test_navigate_change_finishes_via_oracle(self) -> None:
        spec = _spec("navigate", expected={"url": "/story/d03/"})
        session, _proposer, report = self.run_typed(
            spec, [_click("ui:3")],
            ["http://127.0.0.1:1/news/", "http://127.0.0.1:1/story/d03/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual([c for c in session.calls if c[0] == "click_target"],
                         [("click_target", "t3", "dom")])

    def test_form_fill_and_authorized_save_finish(self) -> None:
        store = {"prefs": {"per_page": "20"}, "submissions": []}

        def effect(state):
            state["prefs"]["per_page"] = "50"

        spec = _spec("form", authorized_saves=("ui:2",),
                     form_fields=("per_page",),
                     expected={"form": {"section": "prefs",
                                        "values": {"per_page": "50"}}})
        session, proposer, report = self.run_typed(
            spec,
            [_fill("ui:1", "50"), _save("ui:2")],
            ["http://127.0.0.1:1/news/"],
            store=store, save_effect=effect)
        self.assertEqual(report["outcome"], "finished")
        self.assertIn(("fill_field", "ui:1", "50"), session.calls)
        self.assertIn(("save_form", "ui:2"), session.calls)
        self.assertEqual(store["prefs"]["per_page"], "50")
        self.assertIn("Required form field names", proposer.prompts[0])

    def test_two_toggles_then_authorized_save_finish(self) -> None:
        # M020 Stage 3 regression: value actions never arm the no-change
        # guard, so two legitimate toggles cannot block the loop.
        store = {"settings": {"compact": False, "dark": False},
                 "submissions": []}

        def effect(state):
            state["settings"]["dark"] = True

        def factory(_seq):
            entries = (
                bt.TargetEntry("t1", "checkbox", "compact",
                               (10.0, 10.0, 20.0, 20.0), True, False),
                bt.TargetEntry("t2", "checkbox", "dark",
                               (10.0, 40.0, 20.0, 20.0), True, False),
                bt.TargetEntry("t3", "button", "Save",
                               (10.0, 70.0, 60.0, 24.0), True, False),
            )
            return TargetList(seq=_seq, targets=entries, truncated=False,
                              total=3)

        spec = _spec("form", authorized_saves=("ui:3",),
                     expected={"form": {"section": "settings",
                                         "values": {"dark": True}}})
        session, _proposer, report = self.run_typed(
            spec,
            [_toggle("ui:1", True), _toggle("ui:2", True), _save("ui:3")],
            ["http://127.0.0.1:1/settings/"],
            target_factory=factory, store=store, save_effect=effect)
        self.assertEqual(report["outcome"], "finished", report["steps"])
        self.assertEqual(len([c for c in session.calls
                              if c[0] == "set_toggle"]), 2)
        self.assertEqual(len([c for c in session.calls
                              if c[0] == "save_form"]), 1)

    def test_repeated_value_action_is_refused_then_blocks(self) -> None:
        # Stage 4 revision: a repeat of the last executed value action is a
        # refusal with a hint (read-back already verified the first run);
        # two repeats block instead of executing duplicates.
        spec = _spec("form")
        session, proposer, report = self.run_typed(
            spec,
            [_fill("ui:1", "x"), _fill("ui:1", "x"), _fill("ui:1", "x"),
             {"action": "stop"}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "blocked:no_progress")
        self.assertEqual(len([c for c in session.calls
                              if c[0] == "fill_field"]), 1)
        errors = [step.get("error") for step in report["steps"]
                  if step.get("kind") == "proposal" and step.get("error")]
        self.assertIn("no_observable_change", errors)
        self.assertIn("you already did that", proposer.prompts[2])

    def test_wrong_button_then_repeat_then_correct_save_finishes(self) -> None:
        # The c16 shape: wrong-button save refusal, a repeated toggle, then
        # the authorized save — the loop must recover and finish.
        store = {"settings": {"compact": False, "dark": False},
                 "submissions": []}

        def effect(state):
            state["settings"]["dark"] = True

        def factory(_seq):
            entries = (
                bt.TargetEntry("t1", "checkbox", "compact",
                               (10.0, 10.0, 20.0, 20.0), True, False),
                bt.TargetEntry("t2", "checkbox", "dark",
                               (10.0, 40.0, 20.0, 20.0), True, False),
                bt.TargetEntry("t3", "button", "Reset",
                               (10.0, 70.0, 60.0, 24.0), True, False),
                bt.TargetEntry("t4", "button", "Save",
                               (10.0, 100.0, 60.0, 24.0), True, False),
            )
            return TargetList(seq=_seq, targets=entries, truncated=False,
                              total=4)

        spec = _spec("form", authorized_saves=("ui:4",),
                     expected={"form": {"section": "settings",
                                         "values": {"dark": True}}})
        session, proposer, report = self.run_typed(
            spec,
            [_toggle("ui:1", True), _toggle("ui:2", True), _save("ui:3"),
             _toggle("ui:2", True), _save("ui:4")],
            ["http://127.0.0.1:1/settings/"],
            target_factory=factory, store=store, save_effect=effect)
        self.assertEqual(report["outcome"], "finished", report["steps"])
        self.assertEqual(len([c for c in session.calls
                              if c[0] == "set_toggle"]), 2)
        saves = [c for c in session.calls if c[0] == "save_form"]
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0][1], "ui:4")
        self.assertTrue(any("you already did that" in prompt
                            for prompt in proposer.prompts))

    def test_form_unauthorized_save_denied_without_session_call(self) -> None:
        spec = _spec("form")
        session, _proposer, report = self.run_typed(
            spec, [_save("ui:2"), {"action": "stop"}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "stopped")
        self.assertEqual([c for c in session.calls if c[0] == "save_form"], [])
        rejected = [step for step in report["steps"]
                    if step.get("kind") == "proposal" and not step.get("parsed")]
        self.assertIn("refused_unauthorized_save", rejected[0]["error"])

    def test_form_credential_fill_denied_without_session_call(self) -> None:
        def factory(_seq):
            entries = (
                bt.TargetEntry("t1", "text_input", "Password",
                               (10.0, 10.0, 200.0, 24.0), True, False),
            )
            return TargetList(seq=_seq, targets=entries, truncated=False,
                              total=1)

        spec = _spec("form")
        session, _proposer, report = self.run_typed(
            spec, [_fill("ui:1", "hunter2"), {"action": "stop"}],
            ["http://127.0.0.1:1/news/"], target_factory=factory)
        self.assertEqual(report["outcome"], "stopped")
        self.assertEqual([c for c in session.calls if c[0] == "fill_field"], [])

    def test_fill_read_back_refusal_is_fed_back(self) -> None:
        spec = _spec("form")
        session = FakeTypedSession(self.tmp, ["http://127.0.0.1:1/news/"])
        session.fail_fill = "read_back_failed"
        proposer = TypedProposer([_fill("ui:1", "x"), {"action": "stop"}])
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=lambda: session.store,
            sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
            mode="typed")
        self.assertEqual(report["outcome"], "stopped")
        refused = [step for step in report["steps"]
                   if step.get("kind") == "action" and step.get("refused")]
        self.assertIn("read_back_failed", refused[0]["refused"])
        self.assertIn("read_back_failed", proposer.prompts[1])
        self.assertIn("did not stick", proposer.prompts[1])


if __name__ == "__main__":
    unittest.main()
