"""Letters: Jinja2 templates filled from stored findings. Super writes one explanatory paragraph per letter.

Every fact in a letter (amounts, dates, codes, reasons) comes from a Finding. Super's paragraph is used only
if it adds no number the findings lack and no banned term; otherwise the template's own sentence is used.
"""

import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, field_validator

from app.checks import wording
from app.config import Step
from app.findings import Finding
from app.llm import LLMClient, LLMError
from app.textguard import has_banned_term, numbers_not_in

FOOTER = "Prepared with ClaimGuard. This is not legal advice."
MAX_PARAGRAPH_CHARS = 700
PLACEHOLDER_RECIPIENT = "[billing office name]"
PLACEHOLDER_ADDRESS = "[billing office address]"
MAX_RECIPIENT_CHARS = 200

LetterKind = Literal["correction_request", "gfe_dispute", "eob_mismatch"]

TITLES: dict[str, str] = {
    "correction_request": "Request for a corrected itemized bill and billing review",
    "gfe_dispute": "Good Faith Estimate dispute summary",
    "eob_mismatch": "Request to rebill the amount on my EOB",
}

env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["money"] = lambda value: f"${Decimal(str(value)):,.2f}"


class Recipient(BaseModel):
    """Where the letters go, from the hospital lookup (app/lookup.py) when it found one. Either part may be
    missing; the letter then shows a blank for the patient to fill in. Kept to one short line each."""

    name: str | None = None
    address: str | None = None

    @field_validator("name", "address", mode="before")
    @classmethod
    def _one_short_line(cls, value: object) -> str | None:
        text = " ".join(str(value).split())[:MAX_RECIPIENT_CHARS] if value is not None else ""
        return text or None


class Letter(BaseModel):
    kind: LetterKind
    title: str
    html: str
    text: str


class Explanation(BaseModel):
    paragraph: str


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self._skip = tag in {"style", "title"}
        if tag in {"p", "tr", "li", "h1", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "title"}:
            self._skip = False
        if tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


# --- what each letter says, from the findings --------------------------------------------------------


def _letter_findings(findings: list[Finding]) -> dict[str, list[Finding]]:
    return {
        "correction_request": [
            f for f in findings
            if f.check in {"duplicate", "dose", "units"} and f.level in {"red", "amber"} and not f.billing_review
        ],
        "gfe_dispute": [f for f in findings if f.check == "gfe"],
        "eob_mismatch": [f for f in findings if f.check == "eob"],
    }


def _money(value: object) -> Decimal:
    return Decimal(str(value))


def _context(kind: str, findings: list[Finding], today: date) -> tuple[dict, str, str]:
    """Template values, the plain facts Super may use, and the fallback paragraph."""
    if kind == "correction_request":
        items = []
        for f in findings:
            red = f.level == "red"
            items.append(
                {
                    "reason": f.wording,
                    "review_note": "I would like this reviewed." if f.level == "amber" else "",
                    "amount": f.dollars_at_stake if red and f.dollars_at_stake > 0 else None,
                    "source": f.evidence.source_name if f.evidence.source_url else "",
                    "source_url": f.evidence.source_url or "",
                    "lines": [
                        {
                            "number": line.line_number,
                            "date": line.service_date.isoformat() if line.service_date else "not shown",
                            "code": line.code, "description": line.description, "units": line.units,
                            "charge": line.charge,
                        }
                        for line in f.evidence.bill_lines
                    ],
                }
            )
        facts = "\n".join(
            f"- {item['reason']}"
            + (f" Amount in question ${item['amount']:,.2f}." if item["amount"] else "")
            + " Lines: "
            + "; ".join(
                f"line {l['number']}, code {l['code']}, {l['description']}, units {l['units']}, ${l['charge']:,.2f}"
                for l in item["lines"]
            )
            for item in items
        )
        fallback = (
            "I reviewed my itemized bill against public CMS data and found charges I would like "
            "you to look at. They are listed below with the reason for each."
        )
        return {"items": items}, facts, fallback

    f = findings[0]
    if kind == "gfe_dispute":
        row = f.evidence.data_row
        deadline = f.deadline
        context = {
            "estimate": _money(row["good_faith_estimate"]), "billed": _money(row["facility_total"]),
            "difference": f.overage, "bill_date": wording.date_text(date.fromisoformat(str(row["bill_date"])))
            if row.get("bill_date") else "not shown",
            "window_days": row["window_days"],
            "deadline": wording.date_text(deadline) if deadline else wording.GFE_DEADLINE_UNKNOWN,
            "window_ended": bool(deadline and today > deadline),
            "eligibility": f.wording,
        }
        facts = (
            f"Good Faith Estimate ${context['estimate']:,.2f}; amount billed ${context['billed']:,.2f}; "
            f"difference ${context['difference']:,.2f}; bill date {context['bill_date']}; "
            f"{context['window_days']}-day deadline {context['deadline']}."
        )
        fallback = (
            f"My bill is ${context['billed']:,.2f}, which is ${context['difference']:,.2f} more than the "
            f"Good Faith Estimate of ${context['estimate']:,.2f} I received. This summary lists the "
            "difference and the documents I will attach if I start a federal billing dispute."
        )
        return context, facts, fallback

    context = {
        "billed": f.amount_billed, "owed": f.patient_responsibility, "difference": f.evidence.difference,
    }
    facts = (
        f"Balance on the bill ${context['billed']:,.2f}; patient responsibility on the insurer's EOB "
        f"${context['owed']:,.2f}; difference ${context['difference']:,.2f}."
    )
    fallback = (
        f"Your bill asks me to pay ${context['billed']:,.2f}, but my insurer's Explanation of Benefits "
        f"says my responsibility is ${context['owed']:,.2f}. Please review and rebill the correct amount."
    )
    return context, facts, fallback


SYSTEM = (
    "You write one short paragraph (2 to 4 sentences, first person) for a letter from a patient to a "
    "hospital billing office, explaining why the patient is writing. Use only the facts given. Do not add "
    "any number, date, amount or code that is not in the facts. Say charges 'appear' or 'were flagged "
    "for review'; never say a charge is wrong or must be removed. Do not accuse anyone, give legal or "
    "medical advice, or use the words illegal, unlawful or fraud."
)


def _paragraph(llm: LLMClient | None, case_id: str, facts: str, fallback: str) -> str:
    if llm is None:
        return fallback
    try:
        reply = llm.complete_json(
            Step.DRAFT_LETTER,
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Facts:\n{facts}"}],
            Explanation,
            case_id=case_id,
        )
    except LLMError:
        return fallback
    text = " ".join(reply.paragraph.split())
    if (
        not text
        or len(text) > MAX_PARAGRAPH_CHARS
        or has_banned_term(text)
        or numbers_not_in(text, facts)
    ):
        return fallback
    return text


def build_letters(
    findings: list[Finding],
    *,
    facility_name: str | None,
    llm: LLMClient | None,
    case_id: str,
    today: date | None = None,
    recipient: Recipient | None = None,
) -> list[Letter]:
    """The letters the findings call for. `recipient` (the hospital lookup) addresses them; without it the
    facility name from the bill is used and the address is left blank for the patient."""
    today = today or date.today()
    to_name = (recipient.name if recipient else None) or facility_name or PLACEHOLDER_RECIPIENT
    to_address = (recipient.address if recipient else None) or PLACEHOLDER_ADDRESS
    letters = []
    for kind, relevant in _letter_findings(findings).items():
        if not relevant:
            continue
        context, facts, fallback = _context(kind, relevant, today)
        html = env.get_template(f"{kind}.html.j2").render(
            title=TITLES[kind], recipient=to_name, recipient_address=to_address, footer=FOOTER,
            paragraph=_paragraph(llm, case_id, facts, fallback), **context,
        )
        letters.append(Letter(kind=kind, title=TITLES[kind], html=html, text=html_to_text(html)))
    return letters


def render_pdf(letter: Letter) -> bytes:
    """PDF bytes. WeasyPrint needs pango (brew install pango locally; apt in the Docker image)."""
    from weasyprint import HTML

    try:  # WeasyPrint 68 and later
        from weasyprint.urls import URLFetcher

        fetcher = URLFetcher(allowed_protocols={"data"})
    except ImportError:  # older versions take a function

        def fetcher(url: str, *args: object, **kwargs: object) -> dict:
            raise ValueError("letters load no external resources")

    return HTML(string=letter.html, url_fetcher=fetcher).write_pdf()
