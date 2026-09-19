"""Frozen synthetic UI states for the M012 grounding gate.

Each variant is one window state rendered to a PNG **and** converted to an
`AxWindow` snapshot from the *same* element geometry — a single source of
truth, so the gate tests the alignment and resolution logic, not fixture
drift. Variants cover two layouts (frames reflowed, same identities) at two
scales (1x / 2x, as a Retina capture would be), each at a different window
origin so offset math has teeth.

Frozen tasks (10) run on all variants; see `FROZEN_TASKS`. The duplicate
"SYNC" checkbox exists deliberately: it must be resolvable only through its
stable identifier and must fail closed (`ambiguous`) without it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ax_vision import AxElement, AxWindow
from .corpus import rasterize_text
from .fixture import _encode_png, _fill_rect
from .grounding import Frame, TargetSpec

WINDOW_SIZE = (520.0, 340.0)

PAGE = (245, 246, 250)
PANEL = (255, 255, 255)
TEXT = (40, 44, 52)
ACCENT = (57, 122, 202)
BUTTON = (214, 218, 226)
BORDER = (188, 192, 200)

_FILL_COLORS = {
    "AXCheckBox": PANEL,
    "AXTextField": PANEL,
    "AXButton": BUTTON,
    "AXLink": PAGE,
    "AXStaticText": PAGE,
}


@dataclass(frozen=True)
class FixtureElement:
    element_id: str
    role: str
    name: str
    identifier: str
    rel_frame: Frame
    value: str = ""


_STACKED: tuple[FixtureElement, ...] = (
    FixtureElement("title", "AXStaticText", "PREFERENCES", "prefs.title", (24.0, 18.0, 200.0, 20.0)),
    FixtureElement("sync", "AXCheckBox", "SYNC", "prefs.sync.primary", (24.0, 64.0, 160.0, 22.0), "0"),
    FixtureElement("backup", "AXCheckBox", "SYNC", "prefs.sync.backup", (24.0, 96.0, 160.0, 22.0), "0"),
    FixtureElement("notify", "AXCheckBox", "NOTIFICATIONS", "prefs.notify", (24.0, 128.0, 200.0, 22.0), "1"),
    FixtureElement("search", "AXTextField", "SEARCH", "prefs.search", (24.0, 168.0, 300.0, 26.0), ""),
    FixtureElement("discard", "AXButton", "DISCARD", "prefs.discard", (250.0, 260.0, 116.0, 28.0)),
    FixtureElement("save", "AXButton", "SAVE", "prefs.save", (380.0, 260.0, 116.0, 28.0)),
    FixtureElement("help", "AXLink", "LEARN MORE", "prefs.help", (24.0, 264.0, 140.0, 20.0)),
    FixtureElement("status", "AXStaticText", "READY", "prefs.status", (24.0, 306.0, 120.0, 18.0)),
)

_SPLIT: tuple[FixtureElement, ...] = (
    FixtureElement("title", "AXStaticText", "PREFERENCES", "prefs.title", (24.0, 18.0, 200.0, 20.0)),
    FixtureElement("search", "AXTextField", "SEARCH", "prefs.search", (24.0, 58.0, 340.0, 28.0), ""),
    FixtureElement("help", "AXLink", "LEARN MORE", "prefs.help", (398.0, 60.0, 108.0, 20.0)),
    FixtureElement("sync", "AXCheckBox", "SYNC", "prefs.sync.primary", (24.0, 120.0, 160.0, 22.0), "0"),
    FixtureElement("backup", "AXCheckBox", "SYNC", "prefs.sync.backup", (200.0, 120.0, 160.0, 22.0), "0"),
    FixtureElement("notify", "AXCheckBox", "NOTIFICATIONS", "prefs.notify", (24.0, 152.0, 200.0, 22.0), "1"),
    FixtureElement("save", "AXButton", "SAVE", "prefs.save", (24.0, 268.0, 116.0, 28.0)),
    FixtureElement("discard", "AXButton", "DISCARD", "prefs.discard", (158.0, 268.0, 116.0, 28.0)),
    FixtureElement("status", "AXStaticText", "READY", "prefs.status", (398.0, 300.0, 104.0, 18.0)),
)

_LAYOUTS = {"stacked": _STACKED, "split": _SPLIT}

_VARIANT_ORIGINS = {
    ("stacked", 1): (120.0, 80.0),
    ("stacked", 2): (120.0, 80.0),
    ("split", 1): (260.0, 150.0),
    ("split", 2): (260.0, 150.0),
}


@dataclass(frozen=True)
class GroundingVariant:
    name: str
    image_size: tuple[int, int]
    window_frame: Frame
    window: AxWindow
    id_to_path: dict[str, str]
    image_png: bytes

    @property
    def elements(self) -> tuple[AxElement, ...]:
        return self.window.elements


def _element_text(element: FixtureElement) -> str:
    if element.role == "AXCheckBox":
        mark = "[X]" if element.value == "1" else "[ ]"
        return f"{mark} {element.name}"
    if element.role == "AXTextField":
        return f"SEARCH: {element.value or '_'}"
    return element.name


def _render(specs: tuple[FixtureElement, ...], scale: int) -> bytes:
    width = int(WINDOW_SIZE[0]) * scale
    height = int(WINDOW_SIZE[1]) * scale
    rgb = bytearray(width * height * 3)
    _fill_rect(rgb, width, 0, 0, width, height, PAGE)
    font_scale = max(1, scale)
    for element in specs:
        x0 = int(element.rel_frame[0]) * scale
        y0 = int(element.rel_frame[1]) * scale
        x1 = x0 + int(element.rel_frame[2]) * scale
        y1 = y0 + int(element.rel_frame[3]) * scale
        colour = _FILL_COLORS.get(element.role, PANEL)
        _fill_rect(rgb, width, x0, y0, x1, y1, colour)
        _fill_rect(rgb, width, x0, y0, x1, y0 + scale, BORDER)
        text_colour = ACCENT if element.role == "AXLink" else TEXT
        rasterize_text(rgb, width, x0 + 4 * scale, y0 + 6 * scale, _element_text(element), font_scale, text_colour)
    return _encode_png(width, height, bytes(rgb))


def build_variant(layout: str, scale: int) -> GroundingVariant:
    specs = _LAYOUTS[layout]
    origin_x, origin_y = _VARIANT_ORIGINS[(layout, scale)]
    window_frame: Frame = (origin_x, origin_y, WINDOW_SIZE[0], WINDOW_SIZE[1])
    elements: list[AxElement] = []
    id_to_path: dict[str, str] = {}
    for index, spec in enumerate(specs):
        rel = spec.rel_frame
        abs_frame: Frame = (origin_x + rel[0], origin_y + rel[1], rel[2], rel[3])
        path = f"w0/{index}"
        id_to_path[spec.element_id] = path
        elements.append(
            AxElement(
                role=spec.role,
                subrole=None,
                title=spec.name,
                description=None,
                value=spec.value or None,
                identifier=spec.identifier,
                frame=abs_frame,
                enabled=True,
                focused=False,
                secure=False,
                depth=0,
                path=path,
            )
        )
    window = AxWindow(
        title="SETTINGS",
        frame=window_frame,
        focused=True,
        cg_window_id=None,
        elements=tuple(elements),
    )
    return GroundingVariant(
        name=f"{layout}-{scale}x",
        image_size=(int(WINDOW_SIZE[0]) * scale, int(WINDOW_SIZE[1]) * scale),
        window_frame=window_frame,
        window=window,
        id_to_path=id_to_path,
        image_png=_render(specs, scale),
    )


def all_variants() -> tuple[GroundingVariant, ...]:
    return (
        build_variant("stacked", 1),
        build_variant("stacked", 2),
        build_variant("split", 1),
        build_variant("split", 2),
    )


@dataclass(frozen=True)
class GroundingTask:
    task_id: str
    spec: TargetSpec
    expect: str  # "found" | "not_found" | "ambiguous"
    expected_id: str | None = None
    expected_value: str | None = None


FROZEN_TASKS: tuple[GroundingTask, ...] = (
    GroundingTask("resolve-search-field", TargetSpec("search field", role="textfield"), "found", "search"),
    GroundingTask("resolve-save-button", TargetSpec("save", role="button"), "found", "save"),
    GroundingTask("resolve-discard-button", TargetSpec("discard"), "found", "discard"),
    GroundingTask("resolve-learn-more", TargetSpec("learn more", role="link"), "found", "help"),
    GroundingTask("resolve-heading", TargetSpec("preferences"), "found", "title"),
    GroundingTask(
        "resolve-notifications-state",
        TargetSpec("notifications", role="checkbox"),
        "found",
        "notify",
        expected_value="1",
    ),
    GroundingTask(
        "resolve-sync-by-identifier",
        TargetSpec("sync", element_id="prefs.sync.primary"),
        "found",
        "sync",
        expected_value="0",
    ),
    GroundingTask("negative-delete", TargetSpec("DELETE"), "not_found"),
    GroundingTask("negative-save-all", TargetSpec("SAVE ALL"), "not_found"),
    GroundingTask("ambiguous-sync", TargetSpec("SYNC"), "ambiguous"),
)
