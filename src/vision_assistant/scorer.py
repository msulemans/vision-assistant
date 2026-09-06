from __future__ import annotations

from .corpus import CorpusCase
from .ports import LabelledAnswer


def _norm(text: str) -> str:
    return text.upper()


def _supported(case: CorpusCase) -> set[str]:
    return {_norm(s) for s in (*case.allowed_evidence, *case.required_facts, *case.ui_strings)}


def score(case: CorpusCase, answer: LabelledAnswer) -> dict:
    """Deterministically grade a labelled answer against a frozen case.

    A statement is "supported" when it names at least one allowed fact,
    required fact, or task-critical UI string. Unsupported factual claims,
    forbidden claims, missed required facts, and wrong abstention are all
    failures; a plausible guess unsupported by the screenshot does not pass.
    """
    statements = (*answer.visible, *answer.inferred)
    all_text = _norm(" ".join((*statements, *answer.unknown)))
    supported = _supported(case)

    # Required-fact recall
    required = [_norm(f) for f in case.required_facts]
    found_required = sum(1 for fact in required if fact in all_text)
    recall = (found_required / len(required)) if required else 1.0

    # Unsupported factual claims (statements that name nothing allowed/required/UI)
    unsupported = [s for s in statements if not any(marker in _norm(s) for marker in supported)]
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
