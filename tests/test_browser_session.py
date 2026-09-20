from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from vision_assistant import browser_session as bs

FAKE_HELPER = r'''
import json, os, sys, time

log_path = os.environ.get("FAKE_LOG", "")
state = json.loads(os.environ.get("FAKE_STATE", '{"editable": true, "password": false}'))
current_seq = int(os.environ.get("FAKE_SEQ", "1"))
bump_seq = os.environ.get("FAKE_BUMP_SEQ", "") == "1"
sleep_ms = int(os.environ.get("FAKE_SLEEP_MS", "0"))
crash = os.environ.get("FAKE_CRASH", "") == "1"
pid_path = os.environ.get("FAKE_PID", "")
targets_json = os.environ.get("FAKE_TARGETS", "")
target_error = os.environ.get("FAKE_TARGET_ERROR", "")
targets_list = json.loads(targets_json) if targets_json else []

if pid_path:
    with open(pid_path, "w") as fh:
        fh.write(str(os.getpid()))

def log(text):
    if log_path:
        with open(log_path, "a") as fh:
            fh.write(text + "\n")

def send(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()

if crash:
    sys.exit(1)

send({"ok": True, "event": "ready", "port": 0, "css_width": 1280, "css_height": 720})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    cmd = req.get("cmd")
    rid = req.get("id")
    log(cmd)
    if sleep_ms:
        time.sleep(sleep_ms / 1000.0)
    if cmd == "quit":
        send({"id": rid, "ok": True})
        break
    if cmd == "navigate":
        url = req.get("url", "")
        if url.startswith("/"):
            url = "http://127.0.0.1:1" + url
        send({"id": rid, "ok": True, "url": url})
    elif cmd == "snapshot":
        with open(req["path"], "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\nfakedata")
        send({"id": rid, "ok": True, "seq": current_seq, "width": 2560, "height": 1440,
              "scale": 2.0, "css_width": 1280, "css_height": 720,
              "url": "http://127.0.0.1:1/news/"})
        if bump_seq:
            current_seq = 9
    elif cmd == "click":
        if int(req.get("seq", -1)) != current_seq:
            send({"id": rid, "ok": False, "error": "stale_frame"})
        else:
            send({"id": rid, "ok": True, "url": "http://127.0.0.1:1/story/d03/"})
    elif cmd == "type":
        send({"id": rid, "ok": True, "typed": len(req.get("text", ""))})
    elif cmd == "key":
        send({"id": rid, "ok": True})
    elif cmd == "scroll":
        send({"id": rid, "ok": True, "pages": int(req.get("amount", 1))})
    elif cmd == "back":
        send({"id": rid, "ok": True, "url": "http://127.0.0.1:1/news/"})
    elif cmd == "state":
        send({"id": rid, "ok": True, "seq": current_seq, "loading": False, "blocked": 0,
              "can_go_back": False, "url": "http://127.0.0.1:1/news/", "focused": state})
    elif cmd == "targets":
        send({"id": rid, "ok": True, "seq": current_seq, "total": len(targets_list),
              "truncated": False, "targets": targets_list})
    elif cmd == "click_target":
        if target_error:
            send({"id": rid, "ok": False, "error": target_error})
        elif int(req.get("seq", -1)) != current_seq:
            send({"id": rid, "ok": False, "error": "refused_target_stale"})
        elif req.get("target") not in [t.get("id") for t in targets_list]:
            send({"id": rid, "ok": False, "error": "refused_target_stale"})
        else:
            send({"id": rid, "ok": True, "url": "http://127.0.0.1:1/story/d03/"})
    else:
        send({"id": rid, "ok": False, "error": "unknown_command"})
'''


class SessionBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake = self.tmp / "fake_helper.py"
        self.fake.write_text(FAKE_HELPER, encoding="utf-8")
        self.log = self.tmp / "commands.log"
        self._env_keys = ("FAKE_LOG", "FAKE_STATE", "FAKE_SEQ", "FAKE_BUMP_SEQ",
                          "FAKE_SLEEP_MS", "FAKE_CRASH", "FAKE_PID",
                          "FAKE_TARGETS", "FAKE_TARGET_ERROR")
        self._session = None

    def tearDown(self) -> None:
        if self._session is not None:
            self._session.stop()
        for key in self._env_keys:
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def make_session(self, **env) -> bs.BrowserSession:
        os.environ["FAKE_LOG"] = str(self.log)
        config = {}
        for key in ("timeout_ms", "max_steps", "max_seconds"):
            if key in env:
                config[key] = env.pop(key)
        for key, value in env.items():
            os.environ[key] = str(value)
        self._session = bs.BrowserSession(
            port=8123,
            helper_cmd=[sys.executable, str(self.fake)],
            snapshot_dir=self.tmp / "shots",
            timeout_ms=int(config.get("timeout_ms", 3000)),
            max_steps=int(config.get("max_steps", 20)),
            max_seconds=float(config.get("max_seconds", 120)),
        )
        return self._session.launch()

    def sent(self) -> list:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").split()


class MappingTest(unittest.TestCase):
    def test_scale_mapping_and_validation(self) -> None:
        shot = bs.Snapshot(seq=1, width=2560, height=1440, scale=2.0,
                           url="/news/", path="/tmp/x.png")
        self.assertEqual(bs.map_screenshot_point(100, 50, shot), (50.0, 25.0))
        one_x = bs.Snapshot(seq=1, width=1280, height=720, scale=1.0,
                            url="/news/", path="/tmp/x.png")
        self.assertEqual(bs.map_screenshot_point(37, 41, one_x), (37.0, 41.0))
        for bad in ((-1, 10), (10, -1), (2560, 10), (10, 1440)):
            with self.assertRaises(ValueError):
                bs.map_screenshot_point(bad[0], bad[1], shot)
        with self.assertRaises(ValueError):
            bs.map_screenshot_point(True, 10, shot)
        with self.assertRaises(ValueError):
            bs.map_screenshot_point(10, 10, bs.Snapshot(1, 10, 10, 0.0, "", ""))


class SessionProtocolTest(SessionBase):
    def test_happy_path_protocol_and_snapshot_files(self) -> None:
        session = self.make_session()
        self.assertTrue(session.ready)
        url = session.navigate("/news/")
        self.assertTrue(url.endswith("/news/"))
        shot = session.snapshot()
        self.assertEqual((shot.width, shot.height, shot.scale), (2560, 1440, 2.0))
        self.assertTrue(Path(shot.path).is_file())
        session.click(100, 60)
        self.assertEqual(session.type_text("hello"), 5)
        session.press_key("enter")
        self.assertEqual(session.scroll("down", 2), 2)
        session.back()
        state = session.state()
        self.assertTrue(state["focused"]["editable"])
        self.assertEqual(self.sent(), ["navigate", "snapshot", "click", "state",
                                       "type", "key", "scroll", "back", "state"])
        session.stop()

    def test_navigate_origin_guards_refuse_without_sending(self) -> None:
        session = self.make_session()
        for bad in ("https://evil.example/x", "//evil.example", "http://127.0.0.1:9999/x",
                    "file:///etc/passwd", "news"):
            with self.assertRaises(bs.BrowserError) as caught:
                session.navigate(bad)
            self.assertEqual(caught.exception.reason, "refused_origin", bad)
        self.assertNotIn("navigate", self.sent())
        session.navigate("http://127.0.0.1:8123/news/")
        self.assertIn("navigate", self.sent())

    def test_click_requires_fresh_snapshot(self) -> None:
        session = self.make_session()
        with self.assertRaises(bs.BrowserError) as caught:
            session.click(10, 10)
        self.assertEqual(caught.exception.reason, "refused_stale")
        self.assertNotIn("click", self.sent())

    def test_helper_side_stale_frame_surfaces_typed(self) -> None:
        session = self.make_session(FAKE_BUMP_SEQ=1)
        session.snapshot()
        with self.assertRaises(bs.BrowserError) as caught:
            session.click(10, 10)
        self.assertEqual(caught.exception.reason, "stale_frame")

    def test_click_outside_css_viewport_is_refused(self) -> None:
        session = self.make_session()
        session.snapshot()
        # A snapshot wider than viewport×scale maps some pixels beyond the CSS
        # viewport; that click must be refused before reaching the helper.
        session.last_snapshot = bs.Snapshot(
            seq=1, width=2600, height=1440, scale=2.0,
            url="/news/", path=session.last_snapshot.path)
        with self.assertRaises(bs.BrowserError) as caught:
            session.click(2599, 100)
        self.assertEqual(caught.exception.reason, "refused_viewport")
        self.assertNotIn("click", self.sent())

    def test_password_and_unfocused_typing_are_refused(self) -> None:
        session = self.make_session(FAKE_STATE='{"editable": true, "password": true}')
        with self.assertRaises(bs.BrowserError) as caught:
            session.type_text("hunter2")
        self.assertEqual(caught.exception.reason, "refused_password")
        self.assertNotIn("type", self.sent())
        session.stop()

        self._session = None
        session = self.make_session(FAKE_STATE='{"editable": false, "password": false}')
        with self.assertRaises(bs.BrowserError) as caught:
            session.type_text("hello")
        self.assertEqual(caught.exception.reason, "refused_focus")
        self.assertNotIn("type", self.sent())

    def test_budget_steps_and_seconds(self) -> None:
        session = self.make_session(max_steps=2)
        session.navigate("/news/")
        session.navigate("/search/")
        with self.assertRaises(bs.BrowserError) as caught:
            session.navigate("/prefs/")
        self.assertEqual(caught.exception.reason, "budget_steps")
        self.assertEqual(self.sent().count("navigate"), 2)
        session.stop()

        self._session = None
        session = self.make_session(max_seconds=0)
        with self.assertRaises(bs.BrowserError) as caught:
            session.navigate("/news/")
        self.assertEqual(caught.exception.reason, "budget_seconds")

    def test_timeout_marks_unhealthy_and_closes(self) -> None:
        session = self.make_session(FAKE_SLEEP_MS=1500, timeout_ms=200)
        with self.assertRaises(bs.BrowserError) as caught:
            session.snapshot()
        self.assertEqual(caught.exception.reason, "timeout")
        self.assertTrue(session.unhealthy)
        with self.assertRaises(bs.BrowserError) as caught:
            session.navigate("/news/")
        self.assertEqual(caught.exception.reason, "unhealthy")

    def test_crash_before_ready_is_typed(self) -> None:
        with self.assertRaises(bs.BrowserError) as caught:
            self.make_session(FAKE_CRASH=1)
        self.assertIn(caught.exception.reason, ("closed", "helper_not_ready"))

    def test_stop_cleans_snapshots_and_process(self) -> None:
        pid_file = self.tmp / "helper.pid"
        session = self.make_session(FAKE_PID=str(pid_file))
        session.snapshot()
        shots = session.snapshot_dir
        self.assertTrue(any(shots.iterdir()))
        pid = int(pid_file.read_text())
        session.stop()
        self._session = None
        self.assertFalse(shots.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_adapter_layer_is_inert(self) -> None:
        source = (Path(bs.__file__)).read_text(encoding="utf-8")
        for token in ("NSEvent", "sendEvent", "CGEvent", "CGWarpMouseCursorPosition",
                      "CGEventPostToPid", "pyautogui", "pynput", "osascript"):
            self.assertNotIn(token, source, token)
        self.assertIn("swiftc", source)


DEFAULT_TARGETS = json.dumps([
    {"id": "t1", "role": "link", "label": "Story one",
     "rect": [10, 20, 100, 20], "enabled": True, "focused": False},
    {"id": "t2", "role": "text_input", "label": "query",
     "rect": [10, 60, 200, 24], "enabled": True, "focused": False},
])


class TargetProtocolTest(SessionBase):
    def test_targets_round_trip(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS)
        session.snapshot()
        listing = session.targets()
        self.assertEqual(listing.seq, 1)
        self.assertEqual([entry.id for entry in listing.targets], ["t1", "t2"])
        self.assertEqual(listing.targets[0].role, "link")
        self.assertEqual(listing.targets[0].rect, (10.0, 20.0, 100.0, 20.0))
        self.assertFalse(listing.truncated)
        self.assertEqual(listing.total, 2)
        self.assertEqual(self.sent(), ["snapshot", "targets"])
        session.stop()

    def test_click_target_happy_path_sends_only_the_id(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS)
        session.snapshot()
        session.targets()
        url = session.click_target("t1")
        self.assertIn("/story/", url)
        self.assertEqual(self.sent(), ["snapshot", "targets", "click_target"])
        session.stop()

    def test_click_target_before_targets_is_refused_without_sending(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS)
        session.snapshot()
        with self.assertRaises(bs.BrowserError) as caught:
            session.click_target("t1")
        self.assertEqual(caught.exception.reason, "refused_target_stale")
        self.assertNotIn("click_target", self.sent())
        session.stop()

    def test_click_target_after_a_new_snapshot_is_refused_without_sending(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS)
        session.snapshot()
        session.targets()
        shot = session.last_snapshot
        session.last_snapshot = bs.Snapshot(
            seq=shot.seq + 1, width=shot.width, height=shot.height,
            scale=shot.scale, url=shot.url, path=shot.path)
        with self.assertRaises(bs.BrowserError) as caught:
            session.click_target("t1")
        self.assertEqual(caught.exception.reason, "refused_target_stale")
        self.assertEqual(self.sent().count("click_target"), 0)
        session.stop()

    def test_click_target_unknown_or_malformed_id_never_sent(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS)
        session.snapshot()
        session.targets()
        for bad in ("t9", "xx", "T1", "", "t1 "):
            with self.assertRaises(bs.BrowserError) as caught:
                session.click_target(bad)
            self.assertEqual(caught.exception.reason, "refused_target_stale", bad)
        self.assertNotIn("click_target", self.sent())
        session.stop()

    def test_helper_side_target_refusal_passes_through_typed(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS,
                                    FAKE_TARGET_ERROR="refused_target_moved")
        session.snapshot()
        session.targets()
        with self.assertRaises(bs.BrowserError) as caught:
            session.click_target("t1")
        self.assertEqual(caught.exception.reason, "refused_target_moved")
        self.assertIn("click_target", self.sent())
        session.stop()

    def test_click_target_consumes_the_step_budget(self) -> None:
        session = self.make_session(FAKE_TARGETS=DEFAULT_TARGETS, max_steps=1)
        session.snapshot()
        session.targets()
        session.click_target("t1")
        with self.assertRaises(bs.BrowserError) as caught:
            session.click_target("t2")
        self.assertEqual(caught.exception.reason, "budget_steps")
        session.stop()


if __name__ == "__main__":
    unittest.main()
