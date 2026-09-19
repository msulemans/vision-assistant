from __future__ import annotations

import http.client
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from vision_assistant import browser_fixtures as fixtures
from vision_assistant.fixture_server import FixtureServer


def _request(port: int, method: str, path: str, body: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {}
        payload = None
        if body is not None:
            payload = body.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")
    finally:
        conn.close()


class FixtureServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        site = Path(cls._tmp.name) / "site"
        fixtures.build_site("dev", site)
        cls.server = FixtureServer("dev", site)
        cls.port = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.server.reset()

    def test_home_redirects_and_news_pages_render(self) -> None:
        status, headers, _ = _request(self.port, "GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/news/")
        status, _, body = _request(self.port, "GET", "/news/")
        self.assertEqual(status, 200)
        self.assertIn("Show HN: A tiny toolchain for retro game ports", body)
        self.assertIn('href="/story/d01/"', body)
        _, _, page2 = _request(self.port, "GET", "/news/page2/")
        self.assertIn("The quiet art of cache invalidation", page2)

    def test_story_and_comments_pages(self) -> None:
        _, _, story = _request(self.port, "GET", "/story/d03/")
        self.assertIn(fixtures.story_code("dev", "d03"), story)
        self.assertIn("Story code:", story)
        _, _, comments = _request(self.port, "GET", "/story/d03/comments/")
        oldest = fixtures.comments_for("dev", "d03")[0]["author"]
        self.assertIn(oldest, comments)
        _, _, redirect = _request(self.port, "GET", "/redirect/d07/")
        self.assertIn('href="/story/d07/"', redirect)

    def test_search_renders_results_and_no_results(self) -> None:
        _, _, page = _request(self.port, "GET", "/search/?q=ai")
        for sid in ("d02", "d11", "d15"):
            self.assertIn('href="/story/{}/"'.format(sid), page)
        self.assertNotIn('href="/story/d07/"', page)
        _, _, empty = _request(self.port, "GET", "/search/?q=zzzz")
        self.assertIn("No results", empty)
        _, _, authors = _request(self.port, "GET", "/search/?q=mira&cat=authors")
        self.assertIn('href="/author/mira-chen/"', authors)
        self.assertNotIn("result-story", authors)

    def test_prefs_save_updates_state_and_banner(self) -> None:
        body = urllib.parse.urlencode({
            "default_query": "robotics",
            "default_category": "stories",
            "sort": "newest",
            "hide_seen": "on",
            "per_page": "20",
        })
        status, headers, _ = _request(self.port, "POST", "/prefs/save", body)
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/prefs/?saved=1")
        _, _, state_raw = _request(self.port, "GET", "/__state")
        state = json.loads(state_raw)["state"]
        self.assertEqual(state["prefs"], {
            "default_query": "robotics",
            "default_category": "stories",
            "sort": "newest",
            "hide_seen": True,
            "per_page": "20",
        })
        _, _, page = _request(self.port, "GET", "/prefs/?saved=1")
        self.assertIn("Preferences saved.", page)

    def test_prefs_validation_error_keeps_state(self) -> None:
        body = urllib.parse.urlencode({"default_query": "x", "per_page": "99"})
        status, headers, _ = _request(self.port, "POST", "/prefs/save", body)
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/prefs/?error=per_page")
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["prefs"]["per_page"], "20")
        _, _, page = _request(self.port, "GET", "/prefs/?error=per_page")
        self.assertIn("must be 10, 20 or 30", page)

    def test_draft_and_settings_roundtrip(self) -> None:
        body = urllib.parse.urlencode({"title": "Retro toolchain notes", "body": "Plan: port two games."})
        _request(self.port, "POST", "/draft/save", body)
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["draft"]["title"], "Retro toolchain notes")
        _request(self.port, "POST", "/settings/save", "compact=on&dark=on")
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["settings"],
                         {"compact": True, "dark": True, "show_timestamps": False})
        _request(self.port, "POST", "/settings/reset", "")
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["settings"], dict(fixtures.DEFAULT_SETTINGS))

    def test_submissions_are_recorded_without_values(self) -> None:
        body = urllib.parse.urlencode({"username": "someone", "password": "supersecret"})
        status, _, _ = _request(self.port, "POST", "/login/submit", body)
        self.assertEqual(status, 303)
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertNotIn("supersecret", state_raw)
        submissions = json.loads(state_raw)["state"]["submissions"]
        self.assertEqual(submissions, [{"fields": 2, "path": "/login/submit"}])

    def test_flaky_page_fails_once_then_redirects(self) -> None:
        status, _, body = _request(self.port, "GET", "/flaky/d10/")
        self.assertEqual(status, 503)
        self.assertIn("Transient failure", body)
        status, headers, _ = _request(self.port, "GET", "/flaky/d10/")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/story/d10/")

    def test_reset_restores_defaults_and_applies_seeds(self) -> None:
        _request(self.port, "POST", "/prefs/save", "default_query=changed&per_page=20")
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["prefs"]["default_query"], "changed")
        _, _, reset_raw = _request(self.port, "GET", "/__reset")
        self.assertTrue(json.loads(reset_raw)["ok"])
        _, _, state_raw = _request(self.port, "GET", "/__state")
        self.assertEqual(json.loads(state_raw)["state"]["prefs"], dict(fixtures.DEFAULT_PREFS))
        _, _, seeded = _request(self.port, "GET", "/__reset?seed=36")
        self.assertEqual(json.loads(seeded)["state"]["draft"]["title"], "Published draft")


class FixtureEdgeCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        site = Path(cls._tmp.name) / "site"
        fixtures.build_site("heldout", site)
        cls.server = FixtureServer("heldout", site)
        cls.port = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def test_unknown_story_gets_not_found_page(self) -> None:
        status, _, body = _request(self.port, "GET", "/story/h99/")
        self.assertEqual(status, 404)
        self.assertIn("Story not found", body)
        self.assertIn('href="/news/"', body)

    def test_path_traversal_is_rejected(self) -> None:
        status, _, _ = _request(self.port, "GET", "/story/../content.json")
        self.assertEqual(status, 404)
        status, _, _ = _request(self.port, "GET", "/..%2fcontent.json")
        self.assertEqual(status, 404)

    def test_content_json_is_served_with_version(self) -> None:
        _, headers, body = _request(self.port, "GET", "/content.json")
        self.assertIn("application/json", headers.get("Content-Type", ""))
        payload = json.loads(body)
        self.assertEqual(payload["version"], fixtures.CONTENT_VERSION)
        self.assertEqual(payload["instance"], "heldout")

    def test_double_build_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = fixtures.build_site("heldout", Path(tmp) / "a")
            second = fixtures.build_site("heldout", Path(tmp) / "b")
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
