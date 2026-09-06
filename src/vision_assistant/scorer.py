from __future__ import annotations

import re

from .corpus import CorpusCase
from .ports import LabelledAnswer

_WORD = re.compile(r"[A-Za-z0-9.]+")


def _norm(text: str) -> str:
    return text.upper()


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in _WORD.findall(text):
        word = word.strip(".")
        if len(word) >= 3:
            out.add(word.lower())
    return out


def _ground(case: CorpusCase) -> tuple[frozenset[str], frozenset[str]]:
    """Return (exact evidence markers, evidence token set) for a case.

    A statement is grounded when it repeats an allowed/required/UI string
    verbatim OR shares meaningful tokens with them. This keeps natural-language
    prose that correctly describes the screen from being counted as an
    unsupported claim.
    """
    strings = (*case.allowed_evidence, *case.required_facts, *case.ui_strings)
    markers = frozenset(_norm(s) for s in strings)
    tokens: set[str] = set()
    for s in strings:
        tokens |= _tokens(s)
    return markers, frozenset(tokens)


def score(case: CorpusCase, answer: LabelledAnswer) -> dict:
    """Deterministically grade a labelled answer against a frozen case.

    A statement is "supported" when it names at least one allowed fact,
    required fact, or task-critical UI string. Unsupported factual claims,
    forbidden claims, missed required facts, and wrong abstention are all
    failures; a plausible guess unsupported by the screenshot does not pass.
    """
    statements = (*answer.visible, *answer.inferred)
    all_text = _norm(" ".join((*statements, *answer.unknown)))
    exact_markers, evidence_tokens = _ground(case)

    # Required-fact recall
    required = [_norm(f) for f in case.required_facts]
    found_required = sum(1 for fact in required if fact in all_text)
    recall = (found_required / len(required)) if required else 1.0

    # Unsupported factual claims: a statement is unsupported only when it names
    # neither an evidence string nor any of its meaningful tokens.
    def _grounded(statement: str) -> bool:
        norm = _norm(statement)
        if any(marker in norm for marker in exact_markers):
            return True
        return len(_tokens(statement) & evidence_tokens) >= 2

    unsupported = [s for s in statements if not _grounded(s)]
    claim_total = len(statements)
    unsupported_rate = (len(unsupported) / claim_total) if claim_total else 0.0

    # Forbidden claims
    forbidden_hits = sum(1 for claim in case.forbidden_claims if _norm(claim) in all_text)

    # Task-critical UI strings
    ui_total = len(case.ui_strings)
    ui_matched = sum(1 for s in case.ui_strings if _norm(s) in all_text)
    ui_match = (ui_matched / ui_total) if ui_total else 1.0

    # Abstention
    is_abstain_case = case.category == "insufficient_evidence" or not case.required_facts
    if is_abstain_case:
        # Correct abstention: no invented inference about a cause, and the
        # answer explicitly flags that the cause is not determined. It may
        # still observe what is plainly visible (e.g. a status readout).
        abstain_correct = (len(answer.inferred) == 0) and (len(answer.unknown) > 0)
    else:
        abstain_correct = True

    case_pass = (
        forbidden_hits == 0
        and recall >= 0.9
        and unsupported_rate <= 0.05
        and ui_match >= 0.9
        and abstain_correct
    )

    return {
        "case_id": case.case_id,
        "category": case.category,
        "split": case.split,
        "required_fact_recall": round(recall, 4),
        "unsupported_claim_rate": round(unsupported_rate, 4),
        "forbidden_claim_count": forbidden_hits,
        "ui_string_match": round(ui_match, 4),
        "abstain_correct": abstain_correct,
        "pass": case_pass,
        "unsupported_claims": list(unsupported),
        "forbidden_hits": [c for c in case.forbidden_claims if _norm(c) in all_text],
    }


def aggregate(scores: list[dict]) -> dict:
    """Aggregate per-case scores into corpus-level gate numbers."""
    total = len(scores)
    by_split: dict[str, list[dict]] = {"dev": [], "heldout": []}
    for s in scores:
        by_split.setdefault(s["split"], []).append(s)

    def _avg(key: str, rows: list[dict]) -> float:
        if not rows:
            return 1.0
        return sum(r[key] for r in rows) / len(rows)

    heldout = by_split["heldout"]
    dev = by_split["dev"]
    return {
        "cases": total,
        "dev_cases": len(dev),
        "heldout_cases": len(heldout),
        "required_fact_recall": round(_avg("required_fact_recall", scores), 4),
        "required_fact_recall_heldout": round(_avg("required_fact_recall", heldout), 4),
        "unsupported_claim_rate": round(_avg("unsupported_claim_rate", scores), 4),
        "unsupported_claim_rate_heldout": round(_avg("unsupported_claim_rate", heldout), 4),
        "forbidden_claims_heldout": sum(r["forbidden_claim_count"] for r in heldout),
        "ui_string_match": round(_avg("ui_string_match", scores), 4),
        "abstain_heldout_correct": round(_avg("abstain_correct", heldout), 4),
        "passes": sum(1 for s in scores if s["pass"]),
        "passes_heldout": sum(1 for s in heldout if s["pass"]),
    }
