"""M011 practice app: a deterministic toy window the simulated loop acts on.

The app is a plain Python state machine rendered to a PNG with the project's
embedded bitmap font. Intents are applied only through `apply_intent`, which
mutates this object — there is no host UI, and no input-event path exists
anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .corpus import rasterize_text
from .fixture import _encode_png, _fill_rect
from .intents import ActionIntent

WIDTH, HEIGHT = 480, 300

LIGHT_PAGE = (245, 246, 250)
LIGHT_PANEL = (255, 255, 255)
LIGHT_TEXT = (40, 44, 52)
LIGHT_MUTED = (120, 126, 138)
TITLEBAR = (70, 84, 112)
TITLE_TEXT = (245, 246, 250)
ACCENT = (57, 122, 202)
GOOD = (56, 142, 96)
BORDER = (200, 202, 208)

ELEMENT_CATALOG = (
    ("app:sync-toggle", "checkbox", "SYNC"),
    ("app:notify-toggle", "checkbox", "NOTIFICATIONS"),
    ("app:search", "textfield", "SEARCH"),
    ("app:save", "button", "SAVE"),
    ("app:cancel", "button", "CANCEL"),
)

_SEARCH_TARGETS = {"app:search", "search", "search field", "search box"}


@dataclass
class PracticeApp:
    revision: int = 0
    state: dict = field(
        default_factory=lambda: {
            "sync_enabled": False,
            "notifications": False,
            "search_text": "",
            "dialog_open": True,
            "saved": False,
            "log": [],
        }
    )

    # -- observation ---------------------------------------------------------

    def elements(self) -> list[dict]:
        return [
            {"element_id": "app:sync-toggle", "role": "checkbox", "name": "SYNC",
             "state": "on" if self.state["sync_enabled"] else "off"},
            {"element_id": "app:notify-toggle", "role": "checkbox", "name": "NOTIFICATIONS",
             "state": "on" if self.state["notifications"] else "off"},
            {"element_id": "app:search", "role": "textfield", "name": "SEARCH",
             "state": self.state["search_text"]},
            {"element_id": "app:save", "role": "button", "name": "SAVE",
             "state": "available" if self.state["dialog_open"] else "hidden"},
            {"element_id": "app:cancel", "role": "button", "name": "CANCEL",
             "state": "available" if self.state["dialog_open"] else "hidden"},
        ]

    def observation(self) -> dict:
        return {
            "app": "practice",
            "revision": self.revision,
            "elements": self.elements(),
        }

    # -- rendering -----------------------------------------------------------

    def render(self) -> bytes:
        rgb = bytearray(WIDTH * HEIGHT * 3)
        _fill_rect(rgb, WIDTH, 0, 0, WIDTH, HEIGHT, LIGHT_PAGE)
        _fill_rect(rgb, WIDTH, 0, 0, WIDTH, 34, TITLEBAR)
        rasterize_text(rgb, WIDTH, 14, 10, "PRACTICE APP", 2, TITLE_TEXT)
        if self.state["dialog_open"]:
            _fill_rect(rgb, WIDTH, 40, 54, WIDTH - 40, 210, LIGHT_PANEL)
            _fill_rect(rgb, WIDTH, 40, 54, WIDTH - 40, 56, BORDER)
            rasterize_text(rgb, WIDTH, 60, 78, "CONFIRM CHANGES", 2, LIGHT_TEXT)
            rasterize_text(rgb, WIDTH, 60, 112, "APPLY SETTINGS?", 2, LIGHT_MUTED)
            _fill_rect(rgb, WIDTH, 60, 156, 200, 192, GOOD)
            rasterize_text(rgb, WIDTH, 80, 166, "SAVE", 2, LIGHT_PANEL)
            _fill_rect(rgb, WIDTH, 220, 156, 360, 192, BORDER)
            rasterize_text(rgb, WIDTH, 240, 166, "CANCEL", 2, LIGHT_TEXT)
        else:
            rasterize_text(rgb, WIDTH, 60, 78, "DIALOG CLOSED", 2, LIGHT_MUTED)
        sync_mark = "[X]" if self.state["sync_enabled"] else "[ ]"
        notify_mark = "[X]" if self.state["notifications"] else "[ ]"
        rasterize_text(rgb, WIDTH, 40, 226, f"{sync_mark} SYNC", 2, LIGHT_TEXT)
        rasterize_text(rgb, WIDTH, 180, 226, f"{notify_mark} NOTIFICATIONS", 2, LIGHT_TEXT)
        search = self.state["search_text"] or "_"
        rasterize_text(rgb, WIDTH, 40, 258, f"SEARCH: {search}", 2, ACCENT)
        return _encode_png(WIDTH, HEIGHT, bytes(rgb))

    # -- fake execution ------------------------------------------------------

    def apply_intent(self, intent: ActionIntent) -> dict:
        """Apply one validated intent to this Python object. No host effects."""
        self.state["log"].append(intent.kind)
        if intent.kind == "click_element":
            element_id = intent.params["element_id"]
            if element_id == "app:sync-toggle":
                self.state["sync_enabled"] = not self.state["sync_enabled"]
            elif element_id == "app:notify-toggle":
                self.state["notifications"] = not self.state["notifications"]
            elif element_id == "app:cancel":
                self.state["dialog_open"] = False
                self.state["log"].append("cancelled")
            elif element_id == "app:save":
                self.state["dialog_open"] = False
                self.state["saved"] = True
                self.state["log"].append("saved")
            else:
                return {"applied": False, "reason": "unknown element"}
        elif intent.kind == "type_text":
            target = intent.params.get("element_id") or intent.params.get("field") or ""
            if target.lower() not in _SEARCH_TARGETS:
                return {"applied": False, "reason": "unknown element"}
            self.state["search_text"] = intent.params["text"]
        elif intent.kind == "press_key":
            if intent.params["key"] == "escape":
                self.state["dialog_open"] = False
                self.state["log"].append("escape")
        elif intent.kind == "scroll":
            pass  # toy app has nothing to scroll; recorded as applied, no change
        else:
            return {"applied": False, "reason": "handled by the loop"}
        self.revision += 1
        return {"applied": True, "reason": "applied"}


@dataclass(frozen=True)
class PracticeTask:
    task_id: str
    instruction: str
    verify: Callable[[dict], bool]


FROZEN_TASKS: tuple[PracticeTask, ...] = (
    PracticeTask(
        task_id="enable-sync",
        instruction="Turn on the Sync checkbox.",
        verify=lambda state: bool(state["sync_enabled"]),
    ),
    PracticeTask(
        task_id="type-search",
        instruction="Type the word hello into the search field.",
        verify=lambda state: state["search_text"].strip().lower() == "hello",
    ),
    PracticeTask(
        task_id="cancel-dialog",
        instruction="Close the confirmation dialog using Cancel or the Escape key.",
        verify=lambda state: not state["dialog_open"],
    ),
)
