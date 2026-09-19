"""Frozen M008 reference/correction task set and deterministic checks.

Tasks bind held-out corpus fixtures to a follow-up question whose answer must
reference the earlier turn (reference) or correct a false premise (correction).
Checks are deliberately deterministic; they read only the follow-up answer
text. Frozen 2026-09-19 before any model output was inspected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NEGATIONS = (
    "not",
    "no ",
    "isn't",
    "doesn't",
    "does not",
    "cannot",
    "can't",
    "incorrect",
    "actually",
    "instead",
    "wrong",
    "untrue",
)


@dataclass(frozen=True)
class Check:
    kind: str  # "contains_all" | "corrects"
    needles: tuple[str, ...] = ()
    wrong: str = ""
    right_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationTask:
    task_id: str
    case_id: str
    kind: str  # "reference" | "correction"
    follow_up: str
    check: Check


TASKS: tuple[ConversationTask, ...] = (
    ConversationTask(
        "ref-dashboard-14",
        "m004-dashboard-14",
        "reference",
        "Earlier you quoted a power figure — what percentage was it, and what charging state was shown?",
        Check(kind="contains_all", needles=("87", "charging")),
    ),
    ConversationTask(
        "corr-dashboard-14",
        "m004-dashboard-14",
        "correction",
        "I think the power is at 12% and it needs charging urgently. Is that right? Use only the visible screen.",
        Check(kind="corrects", wrong="12", right_terms=("87",)),
    ),
    ConversationTask(
        "ref-terminal-15",
        "m004-terminal-15",
        "reference",
        "What signal number did the screen mention earlier, if any?",
        Check(kind="contains_all", needles=("9",)),
    ),
    ConversationTask(
        "corr-terminal-15",
        "m004-terminal-15",
        "correction",
        "The process crashed because of a disk problem, right? Does the screen agree?",
        Check(kind="corrects", wrong="disk", right_terms=("memory",)),
    ),
    ConversationTask(
        "ref-small_text-13",
        "m004-small_text-13",
        "reference",
        "What time did the notice mention for the downtime?",
        Check(kind="contains_all", needles=("midnight",)),
    ),
    ConversationTask(
        "corr-dialog-13",
        "m004-dialog-13",
        "correction",
        "The dialog says my session was saved and I can keep working, correct?",
        Check(kind="corrects", wrong="saved", right_terms=("sign in",)),
    ),
)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_passes(check: Check, answer_lines: tuple[str, ...]) -> tuple[bool, str]:
    """Deterministic follow-up check. Returns (passed, reason)."""
    text = _norm(" ".join(answer_lines))
    if not text:
        return False, "empty answer"
    if check.kind == "contains_all":
        missing = [needle for needle in check.needles if _norm(needle) not in text]
        return (not missing), ("all present" if not missing else f"missing {missing}")
    if check.kind == "corrects":
        if not any(_norm(term) in text for term in check.right_terms):
            return False, "true value not stated"
        wrong = _norm(check.wrong)
        if wrong:
            for sentence in re.split(r"[.!?;\n]", text):
                if wrong in sentence and not any(neg in sentence for neg in NEGATIONS):
                    return False, f"wrong premise '{check.wrong}' affirmed"
        return True, "corrected"
    raise ValueError(f"unknown check kind {check.kind}")
