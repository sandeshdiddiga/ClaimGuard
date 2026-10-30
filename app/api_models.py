"""Request and response shapes for the web API."""

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.findings import Finding
from app.lookup import MAX_NAME_CHARS, HospitalLookup
from app.schemas import EobReading, ExtractedLine

CODE = re.compile(r"^(\d{5}|\d{4}[FTU]|[A-Z]\d{4})$")
MAX_LINES = 200
MAX_MONEY = Decimal("10000000")


class SampleView(BaseModel):
    id: str
    title: str
    patient_type: Literal["self_pay", "insured"]
    gfe_total: Decimal | None
    has_eob: bool


class LineIn(ExtractedLine):
    """A line as the patient confirmed it. The code must be well formed; the checks look it up."""

    description: str = Field(default="", max_length=200)
    units: int = Field(default=1, ge=1, le=1000)
    charge: Decimal = Field(ge=0, le=MAX_MONEY)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("code", mode="before")
    @classmethod
    def _well_formed_code(cls, value: object) -> str:
        code = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
        if not CODE.match(code):
            raise ValueError("not a well-formed code")
        return code

    @field_validator("modifier")
    @classmethod
    def _modifier(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9]{2}", value):
            raise ValueError("modifiers are two characters")
        return value.upper() if value else value


class ConfirmRequest(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)
    bill_date: date | None = None
    amount_due: Decimal | None = Field(default=None, ge=0, le=MAX_MONEY)
    gfe_total: Decimal | None = Field(default=None, ge=0, le=MAX_MONEY)


class CallView(BaseModel):
    """One row of the "How this was checked" panel: metadata only, never document text."""

    step: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    ok: bool


class ResultsView(BaseModel):
    findings: list[Finding]
    dollars_at_stake: Decimal  # the likely-error total: red findings, each line once, plus the EOB difference
    deadline: date | None
    # red findings, except the Good Faith Estimate (shown separately) and an insured patient's billing-review items
    likely_error_count: int = 0
    total_charges: Decimal = Decimal("0.00")
    gfe_overage: Decimal | None = None  # self-pay with an estimate: total minus estimate, even under $400


class CaseView(BaseModel):
    id: str
    patient_type: Literal["self_pay", "insured"]
    stage: Literal["confirm", "results"]
    read_with: str | None
    facility_name: str | None
    bill_date: date | None
    amount_due: Decimal | None
    gfe_total: Decimal | None
    eob: EobReading | None
    eob_note: str | None = None  # shown when an EOB was given but could not be used
    lines: list[ExtractedLine]
    results: ResultsView | None
    lookup: HospitalLookup | None = None
    calls: list[CallView]


class LookupRequest(BaseModel):
    """The demo toggle: look up this hospital instead of the one on the bill. Only a name is ever searched."""

    hospital_name: str | None = Field(default=None, max_length=MAX_NAME_CHARS)

    @field_validator("hospital_name")
    @classmethod
    def _plain_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(not char.isprintable() for char in value):
            raise ValueError("a hospital name is one line of plain text")
        return " ".join(value.split()) or None


class LetterView(BaseModel):
    kind: str
    title: str
    text: str  # plain text, for copying
    body_html: str = ""  # the letter's body markup (autoescaped template), for the on-screen preview
    pdf_url: str
