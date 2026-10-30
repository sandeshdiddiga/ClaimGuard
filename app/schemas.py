"""Shared data models. Money is always Decimal, never float."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.codes import CodeClass

Level = Literal["red", "amber", "grey"]
CheckName = Literal["duplicate", "dose", "units", "gfe", "eob", "drug_benchmark", "code"]
CodeStatus = Literal["valid_no_rate", "unknown", "not_checked"]
LineStatus = Literal["ok", "corrected", "needs_review"]


def parse_money(value: Any) -> Any:
    """Accept "$1,980.00", 1980, or 1980.5 from a model reply; never route money through float math."""
    if isinstance(value, str):
        return value.replace("$", "").replace(",", "").strip()
    if isinstance(value, float):
        return str(value)
    return value


def to_cents(value: Any) -> Any:
    """1980.0 -> 1980.00. Amounts with more than two decimals are left alone rather than rounded."""
    if isinstance(value, Decimal) and value.as_tuple().exponent >= -2:  # type: ignore[operator]
        return value.quantize(Decimal("0.01"))
    return value


class ExtractedLine(BaseModel):
    """One bill line as read from a document (before the patient confirms it)."""

    service_date: date | None = None
    code: str
    modifier: str | None = None
    description: str = ""
    units: int = Field(default=1, ge=1)
    charge: Decimal
    status: LineStatus = "ok"  # corrected: code repaired; needs_review: patient must check it
    note: str | None = None
    dose_value: Decimal | None = None  # the dose the description states ("2 mg" -> 2, "MG"); never invented
    dose_unit: str | None = None
    code_class: CodeClass | None = None  # set by extraction and on confirm; None = not classified yet

    _money = field_validator("charge", "dose_value", mode="before")(parse_money)
    _cents = field_validator("charge", mode="after")(to_cents)

    @field_validator("modifier", mode="before")
    @classmethod
    def _blank_modifier(cls, value: Any) -> Any:
        return value or None

    @field_validator("units", mode="before")
    @classmethod
    def _whole_units(cls, value: Any) -> Any:
        return int(value) if isinstance(value, (float, str)) and str(value).strip() else value


class BillReading(BaseModel):
    """What the vision model returns for a bill. No patient name, address or account number."""

    facility_name: str | None = None
    bill_date: date | None = None
    amount_due: Decimal | None = None  # "balance due from patient": what the hospital is asking the patient to pay
    lines: list[ExtractedLine]

    _money = field_validator("amount_due", mode="before")(parse_money)
    _cents = field_validator("amount_due", mode="after")(to_cents)


class EobReading(BaseModel):
    """What the vision model returns for an Explanation of Benefits. Amounts only, no member details."""

    insurer_name: str | None = None
    billed: Decimal
    allowed: Decimal
    patient_responsibility: Decimal

    _money = field_validator("billed", "allowed", "patient_responsibility", mode="before")(parse_money)


class ExpectedLine(BaseModel):
    """A bill line as it should be extracted. Scores per-field extraction accuracy in the eval."""

    model_config = ConfigDict(frozen=True)

    service_date: date
    code: str
    modifier: str | None = None
    description: str
    units: int = Field(ge=1)
    charge: Decimal
    dose_value: Decimal | None = None  # the dose written in the description ("2 mg" -> 2, "MG")
    dose_unit: str | None = None


class ExpectedFlag(BaseModel):
    """A finding the checks must produce (before Ultra reviews amber flags)."""

    model_config = ConfigDict(frozen=True)

    check: CheckName
    level: Level
    codes: list[str] = []
    line_numbers: list[int] = []  # 1-based positions in `lines`
    # What this finding adds to the likely-error total: red findings only, each line counted once overall.
    dollars_at_stake: Decimal = Decimal("0.00")
    expected_units: int | None = None  # dose: units the written dose works out to
    mue_value: int | None = None  # units: CMS's daily limit for the code
    mai: int | None = None  # units: 1 or 2 absolute, 3 clinical judgment
    overage: Decimal | None = None  # gfe: shown separately, never added to the likely-error total
    deadline: date | None = None  # gfe
    amount_billed: Decimal | None = None  # eob: the bill's balance due from the patient
    patient_responsibility: Decimal | None = None  # eob: what the insurer's EOB says the patient owes
    multiple: Decimal | None = None  # drug_benchmark: charge per unit / Medicare payment limit, 1 decimal
    code_status: CodeStatus | None = None  # code


class ExpectedEob(BaseModel):
    """The EOB document that accompanies an insured sample. `plan_paid` is printed but not extracted."""

    insurer: str
    billed: Decimal
    allowed: Decimal
    plan_paid: Decimal
    patient_responsibility: Decimal


class ExpectedSample(BaseModel):
    """Contents of samples/<name>/expected_flags.json."""

    sample_id: str
    description: str
    patient_type: Literal["self_pay", "insured"]
    facility_name: str
    bill_date: date
    payer: str
    amount_due: Decimal  # balance due from patient, as printed on the bill
    gfe_total: Decimal | None = None
    eob: ExpectedEob | None = None
    lines: list[ExpectedLine]
    flags: list[ExpectedFlag]
    likely_error_total: Decimal  # each line counted once, plus the EOB difference; never the GFE overage
    gfe_overage: Decimal | None = None  # shown separately
    deadline: date | None = None  # Good Faith Estimate dispute deadline
