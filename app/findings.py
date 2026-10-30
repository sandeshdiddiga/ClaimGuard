"""A finding is one result of one check, with the evidence behind it. Money is Decimal throughout."""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas import CheckName, CodeStatus, ExtractedLine, Level

ZERO = Decimal("0.00")


class EvidenceLine(BaseModel):
    line_number: int  # 1-based position on the bill
    service_date: date | None
    code: str
    modifier: str | None
    description: str
    units: int
    charge: Decimal
    dose_value: Decimal | None = None  # the dose written on the line, when it states one
    dose_unit: str | None = None


class Evidence(BaseModel):
    bill_lines: list[EvidenceLine] = []
    rule: str
    data_row: dict[str, str | int | bool | None]  # the reference or EOB values the rule used
    computed: dict[str, str | int | bool | None] = {}  # the numbers the check worked out from them
    difference: Decimal | None = None  # the computed amount the finding rests on
    source_name: str
    source_url: str | None = None


class Finding(BaseModel):
    check: CheckName
    level: Level
    wording: str  # shown to the patient; the spec's exact text
    codes: list[str] = []
    line_numbers: list[int] = []
    # line number -> what that line adds to the likely-error total (red only). Each line counts once overall.
    counted: dict[int, Decimal] = {}
    dollars_at_stake: Decimal = ZERO  # this finding's own amount: the sum of `counted`, or the EOB difference
    billing_review: bool = False  # insured units/dose finding: "ask for a billing review", never in a letter
    expected_units: int | None = None  # dose
    mue_value: int | None = None  # units
    mai: int | None = None  # units
    overage: Decimal | None = None  # gfe: shown, never added to the likely-error total
    deadline: date | None = None  # gfe
    multiple: Decimal | None = None  # drug_benchmark
    code_status: CodeStatus | None = None  # code
    judge_decision: Literal["keep", "downgrade"] | None = None  # amber units/dose, set by app/judge.py
    judge_reason: str | None = None
    amount_billed: Decimal | None = None  # eob
    patient_responsibility: Decimal | None = None  # eob
    evidence: Evidence


def evidence_lines(lines: Sequence[ExtractedLine], numbers: Sequence[int]) -> list[EvidenceLine]:
    return [
        EvidenceLine(
            line_number=n, service_date=lines[n - 1].service_date, code=lines[n - 1].code,
            modifier=lines[n - 1].modifier, description=lines[n - 1].description,
            units=lines[n - 1].units, charge=lines[n - 1].charge,
            dose_value=lines[n - 1].dose_value, dose_unit=lines[n - 1].dose_unit,
        )
        for n in numbers
    ]


def charges(lines: Sequence[ExtractedLine], numbers: Sequence[int]) -> Decimal:
    return sum((lines[n - 1].charge for n in numbers), ZERO)


def total_dollars_at_stake(findings: Sequence[Finding], lines: Sequence[ExtractedLine]) -> Decimal:
    """The likely-error total: red findings only. A line flagged by several checks counts once, at its largest
    amount; the EOB difference counts as the larger of itself and the line amounts, never added to them. Amber, grey and the Good Faith
    Estimate overage add nothing. `lines` is accepted for callers that have them; amounts live on findings."""
    red = [f for f in findings if f.level == "red"]
    per_line: dict[int, Decimal] = {}
    for finding in red:
        for number, amount in finding.counted.items():
            per_line[number] = max(per_line.get(number, ZERO), amount)
    # The EOB difference is the whole gap between the balance asked and what the EOB says is owed, so it already
    # contains any duplicate or excess line inside that balance: take the larger of the two, never their sum.
    eob = sum((f.dollars_at_stake for f in red if f.check == "eob"), ZERO)
    other = sum((f.dollars_at_stake for f in red if not f.counted and f.check != "eob"), ZERO)
    return max(sum(per_line.values(), ZERO), eob) + other


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def excess_amount(line: ExtractedLine, excess_units: int) -> Decimal:
    """What `excess_units` of this line cost: excess units x the line's charge per unit, to the cent."""
    return money(line.charge * excess_units / line.units)
