"""Nano's job on every upload: confirm it is an itemized bill, and fix codes the deterministic pass could not.

Only codes, descriptions and charges are sent. Names, addresses and account numbers never leave extraction.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator

from app.config import Step
from app.llm import LLMClient, LLMError
from app.schemas import ExtractedLine, parse_money

SYSTEM = (
    "You help clean up text read from an itemized medical bill. You never give medical or legal advice and "
    "you do not compute amounts. Decide whether the lines look like an itemized bill from a hospital or "
    "clinic. For each line listed under 'unresolved', give the most likely correct HCPCS Level II code (one "
    "letter followed by four digits) if the printed code was misread, or mark it unreadable. For every line, "
    "also return its dose in 'doses': the dose written in the line's description text (dose_value as a "
    "number, dose_unit such as mg, mcg or mL), copied exactly from the description. If the description "
    "states no dose, return null for both. Never calculate, convert or guess a dose, and never take it from "
    "the charge or the units."
)


class CleanedLine(BaseModel):
    index: int
    code: str = ""
    readable: bool
    note: str = ""


class LineDose(BaseModel):
    """The dose Nano read from one line's description. Python checks it against the text before it is kept."""

    index: int
    dose_value: Decimal | None = None
    dose_unit: str | None = None

    _number = field_validator("dose_value", mode="before")(parse_money)


class GateResult(BaseModel):
    is_itemized_bill: bool
    reason: str = ""
    lines: list[CleanedLine] = []
    doses: list[LineDose] = []


def review_lines(
    llm: LLMClient, case_id: str, lines: list[ExtractedLine], unresolved: list[int]
) -> GateResult:
    listing = "\n".join(
        f"{i}. code={line.code!r} description={line.description!r} charge={line.charge}"
        for i, line in enumerate(lines)
    )
    wanted = ", ".join(str(i) for i in unresolved) or "none"
    user = f"Lines:\n{listing}\n\nunresolved: {wanted}"
    return llm.complete_json(
        Step.CLEAN_CODES,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        GateResult,
        case_id=case_id,
    )


# --- scope gate for free-text questions -------------------------------------------------------------

MAX_QUESTION_CHARS = 1000

SCOPE_SYSTEM = (
    "You decide whether a message to a medical-bill checking tool is about the patient's bill or the "
    "findings on it. Answer with one category: 'billing' (the bill, its charges, codes, estimates, "
    "insurer statements or the letters), 'medical_advice' (diagnosis, symptoms, treatment, medication), "
    "'legal_advice' (suing, what the law requires, whether someone broke a law), or 'off_topic' "
    "(anything else). Do not answer the message."
)

REDIRECTS = {
    "medical_advice": (
        "ClaimGuard can't help with medical questions such as diagnosis or treatment. Please ask your "
        "clinician. I can check whether your bill matches public CMS rules."
    ),
    "legal_advice": (
        "ClaimGuard can't give legal advice. It explains what your bill shows and drafts letters for you "
        "to review and send yourself."
    ),
    "off_topic": (
        "ClaimGuard only checks medical bills against public CMS rules. Upload a bill, or ask what one "
        "of the findings means."
    ),
}


class Triage(BaseModel):
    category: Literal["billing", "medical_advice", "legal_advice", "off_topic"]


class ScopeDecision(BaseModel):
    allowed: bool
    message: str | None = None  # a fixed redirect, never text written by the model


def screen_question(llm: LLMClient, case_id: str, text: str) -> ScopeDecision:
    """Nano classifies; the redirect wording is ours. Anything unclear is redirected."""
    try:
        triage = llm.complete_json(
            Step.CLEAN_CODES,
            [
                {"role": "system", "content": SCOPE_SYSTEM},
                {"role": "user", "content": text[:MAX_QUESTION_CHARS]},
            ],
            Triage,
            case_id=case_id,
        )
    except LLMError:
        return ScopeDecision(allowed=False, message=REDIRECTS["off_topic"])
    if triage.category == "billing":
        return ScopeDecision(allowed=True)
    return ScopeDecision(allowed=False, message=REDIRECTS[triage.category])
