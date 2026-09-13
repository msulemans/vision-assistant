from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .fixture import SyntheticFixture, _encode_png, _fill_rect

# A tiny 5x7 bitmap font. Only uppercase letters, digits, and a small set of
# punctuation are stored; anything else is rendered as a space. Keeping the
# glyph table small keeps the dependency-free fixture generator readable.
FONT: dict[str, tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    ";": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x04, 0x08),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "/": (0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "[": (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),
    "]": (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),
    "'": (0x04, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),
    '"': (0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00),
    "!": (0x04, 0x04, 0x04, 0x04, 0x00, 0x04, 0x04),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    "%": (0x11, 0x12, 0x02, 0x04, 0x08, 0x09, 0x11),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "*": (0x00, 0x0A, 0x04, 0x1F, 0x04, 0x0A, 0x00),
}


def _glyph(ch: str) -> tuple[int, ...]:
    return FONT.get(ch.upper(), FONT[" "])


def rasterize_text(
    rgb: bytearray,
    width: int,
    x: int,
    y: int,
    text: str,
    scale: int,
    color: tuple[int, int, int],
) -> int:
    """Draw *text* with the embedded bitmap font, returning the next x position.

    Each glyph is 5x7, scaled by *scale* in both axes. Unknown characters are
    rendered as a space. This lets the synthetic fixtures carry real,
    human-readable strings without any image dependency.
    """
    cursor = x
    for ch in text:
        glyph = _glyph(ch)
        for row, bits in enumerate(glyph):
            for col in range(5):
                if bits & (1 << (4 - col)):
                    _fill_rect(
                        rgb,
                        width,
                        cursor + col * scale,
                        y + row * scale,
                        cursor + (col + 1) * scale,
                        y + (row + 1) * scale,
                        color,
                    )
        cursor += 6 * scale
    return cursor


def _text_width(text: str, scale: int) -> int:
    return len(text) * 6 * scale


def _draw_text_centered(rgb: bytearray, width: int, y: int, text: str, scale: int, color: tuple[int, int, int]) -> None:
    rasterize_text(rgb, width, (width - _text_width(text, scale)) // 2, y, text, scale, color)


# ---------------------------------------------------------------------------
# Category painting helpers
# ---------------------------------------------------------------------------


def _paint_terminal(rgb: bytearray, w: int, h: int, lines: list[str], *, error_line: str, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["bg"])
    y = 14
    for i, line in enumerate(lines):
        color = theme["error"] if line == error_line else theme["text"]
        rasterize_text(rgb, w, 14, y, line, 2, color)
        y += 22


def _paint_dialog(rgb: bytearray, w: int, h: int, title: str, body: str, note: str, *, warning: bool, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    _fill_rect(rgb, w, 20, 24, w - 20, h - 24, theme["panel"])
    _fill_rect(rgb, w, 20, 24, w - 20, 44, theme["titlebar"])
    rasterize_text(rgb, w, 34, 30, title, 2, theme["title"])
    rasterize_text(rgb, w, 34, 62, body, 2, theme["text"])
    if warning:
        _fill_rect(rgb, w, 34, 92, 190, 104, theme["warnbg"])
        rasterize_text(rgb, w, 40, 92, note, 1, theme["warn"])
    # Buttons
    _fill_rect(rgb, w, w // 2 - 60, h - 60, w // 2 + 10, h - 40, theme["primary"])
    _fill_rect(rgb, w, w // 2 + 24, h - 60, w // 2 + 84, h - 40, theme["button2"])


def _paint_form(rgb: bytearray, w: int, h: int, title: str, fields: list[str], *, invalid_field: str, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    rasterize_text(rgb, w, 30, 26, title, 2, theme["text"])
    y = 70
    for field in fields:
        color = theme["error"] if field == invalid_field else theme["text"]
        rasterize_text(rgb, w, 30, y, field, 2, color)
        _fill_rect(rgb, w, 30, y + 22, w - 30, y + 48, theme["input"])
        y += 66
    if invalid_field:
        _fill_rect(rgb, w, 30, y + 6, 200, y + 18, theme["warnbg"])
        rasterize_text(rgb, w, 36, y + 6, "REQUIRED", 1, theme["warn"])


def _paint_settings(rgb: bytearray, w: int, h: int, title: str, rows: list[str], *, active: str, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    rasterize_text(rgb, w, 26, 20, title, 2, theme["text"])
    y = 58
    for row in rows:
        _fill_rect(rgb, w, 26, y, w - 26, y + 34, theme["panel"])
        rasterize_text(rgb, w, 36, y + 11, row, 2, theme["text"] if row != active else theme["primary"])
        # toggle
        _fill_rect(rgb, w, w - 70, y + 9, w - 40, y + 25, theme["primary"] if row == active else theme["button2"])
        y += 46


def _wrap(text: str, width_chars: int) -> list[str]:
    """Word-wrap *text* to about *width_chars* characters per line."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width_chars:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _paint_dashboard(rgb: bytearray, w: int, h: int, stat: str, status_value: str, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    rasterize_text(rgb, w, 20, 16, "STATUS DASHBOARD", 2, theme["text"])
    # Prominent primary metric card.
    _fill_rect(rgb, w, 24, 56, w - 24, 150, theme["primary"])
    rasterize_text(rgb, w, 36, 92, stat, 3, theme["title"])
    # Decorative secondary cards.
    for i in range(3):
        x0 = 40 + i * 140
        _fill_rect(rgb, w, x0, 170, x0 + 120, 214, theme["panel"])
    # Status bar.
    _fill_rect(rgb, w, 24, 232, w - 24, 270, theme["ok"])
    rasterize_text(rgb, w, 40, 246, status_value, 2, theme["on_ok"])


def _paint_small_text(rgb: bytearray, w: int, h: int, lines: list[str], theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    y = 16
    for line in lines:
        for wrapped in _wrap(line, 38):
            rasterize_text(rgb, w, 12, y, wrapped, 2, theme["text"])
            y += 18


def _paint_insufficient(rgb: bytearray, w: int, h: int, title: str, note: str, theme: dict) -> None:
    _fill_rect(rgb, w, 0, 0, w, h, theme["page"])
    _draw_text_centered(rgb, w, 80, title, 2, theme["text"])
    rasterize_text(rgb, w, 60, 150, note, 1, theme["muted"])


# ---------------------------------------------------------------------------
# Corpus case model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    split: str  # "dev" | "heldout"
    question: str
    allowed_evidence: tuple[str, ...]
    required_facts: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    uncertainty: str  # what should be labelled unknown / abstain
    ui_strings: tuple[str, ...]  # task-critical strings expected verbatim


@dataclass(frozen=True)
class CorpusCase(Case):
    fixture: SyntheticFixture
    content_sha256: str
    width: int
    height: int

    def manifest_entry(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "split": self.split,
            "question": self.question,
            "allowed_evidence": list(self.allowed_evidence),
            "required_facts": list(self.required_facts),
            "forbidden_claims": list(self.forbidden_claims),
            "uncertainty": self.uncertainty,
            "ui_strings": list(self.ui_strings),
            "image": {
                "sha256": self.content_sha256,
                "width": self.width,
                "height": self.height,
                "fixture_id": self.fixture.id,
            },
        }


CATEGORIES = (
    "terminal",
    "dialog",
    "form",
    "settings",
    "dashboard",
    "small_text",
    "dark_mode",
    "insufficient_evidence",
)

LIGHT = {
    "page": (245, 246, 250),
    "panel": (255, 255, 255),
    "text": (40, 44, 52),
    "muted": (120, 126, 138),
    "input": (232, 235, 240),
    "primary": (57, 122, 202),
    "button2": (200, 202, 208),
    "titlebar": (70, 84, 112),
    "title": (245, 246, 250),
    "warnbg": (200, 82, 82),
    "warn": (255, 240, 240),
    "ok": (56, 142, 96),
    "on_ok": (255, 255, 255),
    "error": (180, 60, 60),
    "bg": (24, 26, 32),
}

DARK = {
    "page": (24, 26, 32),
    "panel": (40, 44, 52),
    "text": (224, 228, 236),
    "muted": (120, 126, 138),
    "input": (60, 64, 74),
    "primary": (70, 120, 210),
    "button2": (90, 96, 110),
    "titlebar": (40, 44, 58),
    "title": (230, 234, 240),
    "warnbg": (150, 64, 64),
    "warn": (250, 235, 235),
    "ok": (56, 142, 96),
    "on_ok": (255, 255, 255),
    "error": (220, 90, 80),
    "bg": (16, 18, 22),
}

_TERMINAL_ERRORS = [
    "CONNECTION REFUSED ON LOCALHOST:5432",
    "PERMISSION DENIED: /VAR/RUN/X.SOCK",
    "404 NOT FOUND: /API/STATUS",
    "TIMEOUT: NO RESPONSE FROM 10.0.0.7:443",
    "DISK FULL: NO SPACE LEFT ON DEVICE",
    "AUTH FAILED: INVALID CREDENTIALS",
    "SEGMENTATION FAULT AT 0X00A1",
    "SSL CERTIFICATE HAS EXPIRED",
    "CONFIG FILE MISSING: SETTINGS.TOML",
    "DATABASE LOCKED BY ANOTHER SESSION",
    "CONNECTION RESET BY PEER",
    "UNSUPPORTED FILE FORMAT: REPORT.CSV",
]
_DIALOGS = [
    ("CONNECT TO DATABASE", "ENTER THE PASSWORD TO CONTINUE"),
    ("UPDATE AVAILABLE", "RESTART NOW TO APPLY THE UPDATE"),
    ("DISK LOW", "FREE SPACE TO AVOID DATA LOSS"),
    ("NETWORK UNREACHABLE", "CHECK YOUR NETWORK CONNECTION"),
    ("LICENSE EXPIRED", "RENEW TO CONTINUE USING THIS APP"),
    ("SYNC CONFLICT", "CHOOSE WHICH VERSION TO KEEP"),
    ("UNSAVED CHANGES", "SAVE YOUR WORK BEFORE CLOSING"),
    ("LOW BATTERY", "PLUG IN TO KEEP WORKING"),
    ("MIGRATION COMPLETE", "REVIEW THE CHANGES TO CONTINUE"),
    ("RESTART REQUIRED", "CLOSE THE APP TO FINISH UPDATING"),
    ("CERTIFICATE WARNING", "CONTINUE ONLY IF YOU TRUST THIS SITE"),
    ("STORAGE ALMOST FULL", "REMOVE FILES TO FREE SPACE"),
]
_FORMS = [
    ("LOGIN", "PASSWORD"),
    ("SIGN UP", "EMAIL"),
    ("CONFIGURE", "HOST"),
    ("SETTINGS", "PORT"),
    ("CHECKOUT", "CARD NUMBER"),
    ("PROFILE", "PHONE"),
    ("RESET PASSWORD", "CONFIRM PASSWORD"),
    ("SHIPPING", "ZIP CODE"),
    ("PAYMENT", "EXPIRY DATE"),
    ("DELETE ACCOUNT", "CONFIRM EMAIL"),
    ("INVOICE", "TAX ID"),
    ("TRANSFER", "AMOUNT"),
]
_SETTINGS = [
    ("PREFERENCES", "AUTO-UPDATE"),
    ("PREFERENCES", "DARK MODE"),
    ("PREFERENCES", "TELEMETRY"),
    ("NOTIFICATIONS", "SOUND"),
    ("PRIVACY", "ICLOUD SYNC"),
    ("ACCOUNT", "TWO-FACTOR"),
    ("SECURITY", "FIREWALL"),
    ("DISPLAY", "NIGHT SHIFT"),
    ("ADVANCED", "BETA UPDATES"),
    ("NETWORK", "VPN"),
    ("SOUND", "NOISE CANCEL"),
    ("UPDATES", "AUTO RESTART"),
]
_DASHBOARDS = [
    ("CPU 78%", "ALL SYSTEMS NORMAL"),
    ("MEMORY 5.6G", "THRESHOLD WARNING"),
    ("ERRORS 3", "ACTION REQUIRED"),
    ("NET 1.2GB", "ALL SYSTEMS NORMAL"),
    ("UPTIME 42H", "DEGRADED"),
    ("LATENCY 210MS", "SLOW RESPONSE"),
    ("DISK 82%", "CLEANUP RECOMMENDED"),
    ("BATTERY 64%", "PLUGGED IN"),
    ("QUEUE 12", "PROCESSING"),
    ("MEMORY 91%", "PRESSURE HIGH"),
    ("SESSIONS 5", "ACTIVE"),
    ("RETRIES 2", "RECOVERING"),
]
_SMALL_TEXTS = [
    "END USER LICENSE AGREEMENT. BY CLICKING ACCEPT YOU AGREE TO THE TERMS BELOW.",
    "PRIVACY POLICY. WE COLLECT ONLY THE DATA NEEDED TO OPERATE THIS SERVICE.",
    "TERMS OF SERVICE. DO NOT REVERSE ENGINEER OR RESELL THIS APPLICATION.",
    "COOKIE NOTICE. YOU MAY DISABLE NON-ESSENTIAL COOKIES IN SETTINGS.",
    "SECURITY NOTICE. REPORT ANY SUSPECTED VULNERABILITY TO SECURITY@EXAMPLE.COM.",
    "DATA PROCESSING. TRANSFERS ARE ENCRYPTED AT REST AND IN TRANSIT.",
    "SERVICE AGREEMENT. USAGE IS MONITORED FOR QUALITY.",
    "BACKUP NOTICE. RESTORE POINTS ARE KEPT FOR 30 DAYS.",
    "ACCESSIBILITY. REDUCED MOTION CAN BE ENABLED IN SETTINGS.",
    "TRIAL NOTICE. YOUR TRIAL ENDS IN 7 DAYS.",
    "REMINDER. PASSWORD CHANGES TAKE EFFECT IMMEDIATELY.",
    "OFFLINE MODE. CHANGES SYNC WHEN CONNECTION RETURNS.",
]


def _spec(category: str, index: int) -> dict:
    """Return the authored evidence/facts/claims for one corpus case."""
    if index < 3:
        split = "dev"
    elif index < 9:
        # Inspected under corpus v1/v2 while tuning; diagnostics only, never
        # used to promote a candidate.
        split = "legacy"
    else:
        # Fresh held-out cases, authored and frozen before the candidate run.
        split = "heldout"
    common_forbidden = ("The screenshot proves the root cause", "The service is definitely stopped")
    if category == "terminal":
        error = _TERMINAL_ERRORS[index]
        return {
            "question": "Why is this application failing?",
            "allowed_evidence": (error, "./APP", "EXIT CODE 1"),
            "required_facts": (error,),
            "forbidden_claims": common_forbidden,
            "uncertainty": "Whether a service is stopped is not visible.",
            "ui_strings": (error,),
            "split": split,
            "error": error,
        }
    if category == "dialog":
        title, body = _DIALOGS[index]
        return {
            "question": "What does this dialog ask the user to do?",
            "allowed_evidence": (title, body),
            "required_facts": (title,),
            "forbidden_claims": common_forbidden,
            "uncertainty": "The underlying cause that raised the dialog is not visible.",
            "ui_strings": (title,),
            "split": split,
            "title": title,
            "body": body,
        }
    if category == "form":
        title, field = _FORMS[index]
        return {
            "question": "Which field is invalid?",
            "allowed_evidence": (title, field, "HOST", "PORT", "REQUIRED"),
            "required_facts": (field, "REQUIRED"),
            "forbidden_claims": common_forbidden + (f"The value of {field} is incorrect",),
            "uncertainty": "The exact offending value is not readable.",
            "ui_strings": (field, "REQUIRED"),
            "split": split,
            "title": title,
            "invalid": field,
        }
    if category == "settings":
        title, active = _SETTINGS[index]
        return {
            "question": "Which setting is currently enabled?",
            "allowed_evidence": (title, active, "AUTO-SAVE", "TELEMETRY"),
            "required_facts": (active,),
            "forbidden_claims": common_forbidden,
            "uncertainty": "What the setting affects outside this screen is not visible.",
            "ui_strings": (active,),
            "split": split,
            "title": title,
            "active": active,
        }
    if category == "dashboard":
        stat, status_value = _DASHBOARDS[index]
        return {
            "question": "Summarize the important status on this dashboard.",
            "allowed_evidence": (stat, status_value, "STATUS DASHBOARD"),
            "required_facts": (stat,),
            "forbidden_claims": common_forbidden,
            "uncertainty": "The meaning of the status beyond the shown value is not visible.",
            "ui_strings": (stat, status_value),
            "split": split,
            "stat": stat,
            "status_value": status_value,
        }
    if category == "small_text":
        text = _SMALL_TEXTS[index]
        return {
            "question": "What does this document require or state?",
            "allowed_evidence": (text,),
            "required_facts": (text,),
            "forbidden_claims": ("The document was accepted by the user",),
            "uncertainty": "User consent is not visible in this text.",
            "ui_strings": (text,),
            "split": split,
            "text": text,
        }
    if category == "dark_mode":
        title, body = _DIALOGS[index]
        return {
            "question": "What does this dialog ask the user to do?",
            "allowed_evidence": (title, body),
            "required_facts": (title,),
            "forbidden_claims": common_forbidden,
            "uncertainty": "The underlying cause that raised the dialog is not visible.",
            "ui_strings": (title,),
            "split": split,
            "title": title,
            "body": body,
            "dark": True,
        }
    # insufficient_evidence
    titles = (
        "NOTHING TO REPORT", "PROCESSING", "NO ERRORS", "WAITING", "EMPTY", "CHECKING",
        "ALL CLEAR", "STANDBY", "IDLE",
        "NO ISSUES FOUND", "COMPLETED", "MONITORING",
    )
    title = titles[index]
    return {
        "question": "What is wrong on this screen?",
        "allowed_evidence": (title, "NO CAUSE IS VISIBLE IN THIS SCREEN"),
        "required_facts": (),
        "forbidden_claims": ("The screen shows an error", "A service failed"),
        "uncertainty": "No cause is visible; the correct answer is to abstain.",
        "ui_strings": (title,),
        "split": split,
        "title": title,
        "abstain": True,
    }


def _build_fixture(case_id: str, category: str, spec: dict) -> SyntheticFixture:
    w, h = 480, 300
    theme = DARK if category in {"terminal", "dark_mode"} else LIGHT
    rgb = bytearray(w * h * 3)

    if category == "terminal":
        lines = [f"$ ./app", f"{spec['error']}", f"exit code 1"]
        _paint_terminal(rgb, w, h, lines, error_line=spec["error"], theme=theme)
    elif category == "dialog":
        _paint_dialog(rgb, w, h, spec["title"], spec["body"], "REQUIRED", warning=False, theme=theme)
    elif category == "form":
        fields = ("HOST", spec["invalid"], "PORT")
        _paint_form(rgb, w, h, spec["title"], list(fields), invalid_field=spec["invalid"], theme=theme)
    elif category == "settings":
        rows = (spec["active"], "AUTO-SAVE", "TELEMETRY")
        _paint_settings(rgb, w, h, spec["title"], list(rows), active=spec["active"], theme=theme)
    elif category == "dashboard":
        _paint_dashboard(rgb, w, h, spec["stat"], spec["status_value"], theme)
    elif category == "small_text":
        _paint_small_text(rgb, w, h, [spec["text"]], theme)
    elif category == "dark_mode":
        _paint_dialog(rgb, w, h, spec["title"], spec["body"], "REQUIRED", warning=False, theme=theme)
    else:  # insufficient_evidence
        _paint_insufficient(rgb, w, h, spec["title"], "NO CAUSE IS VISIBLE IN THIS SCREEN", theme)

    png = _encode_png(w, h, bytes(rgb))
    return SyntheticFixture(id=case_id, width=w, height=h, png_bytes=png, path=None)


def build_corpus(out_dir: Path | None = None) -> list[CorpusCase]:
    """Generate all 96 frozen cases (24 dev, 48 legacy, 24 fresh held-out) deterministically."""
    cases: list[CorpusCase] = []
    for category in CATEGORIES:
        for index in range(12):
            spec = _spec(category, index)
            case_id = f"m004-{category}-{index + 1:02d}"
            fixture = _build_fixture(case_id, category, spec)
            if out_dir is not None:
                fixture_path = out_dir / category / f"{case_id}.png"
                fixture_path.parent.mkdir(parents=True, exist_ok=True)
                fixture_path.write_bytes(fixture.png_bytes)
                fixture = SyntheticFixture(id=fixture.id, width=fixture.width, height=fixture.height, png_bytes=fixture.png_bytes, path=fixture_path)
            cases.append(
                CorpusCase(
                    case_id=case_id,
                    category=category,
                    split=spec["split"],
                    question=spec["question"],
                    allowed_evidence=spec["allowed_evidence"],
                    required_facts=spec["required_facts"],
                    forbidden_claims=spec["forbidden_claims"],
                    uncertainty=spec["uncertainty"],
                    ui_strings=spec["ui_strings"],
                    fixture=fixture,
                    content_sha256=hashlib.sha256(fixture.png_bytes).hexdigest(),
                    width=fixture.width,
                    height=fixture.height,
                )
            )
    return cases


def manifest(cases: list[CorpusCase]) -> dict:
    """Build the frozen corpus manifest (sorted so it is byte-stable)."""
    return {
        "corpus": "m004-screen-understanding",
        "schema_version": "1.0",
        "generated": "deterministic",
        "categories": list(CATEGORIES),
        "cases": [c.manifest_entry() for c in sorted(cases, key=lambda case: case.case_id)],
    }
