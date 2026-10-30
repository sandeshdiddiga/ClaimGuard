"""Small constructors so each test states only what it cares about."""

from datetime import date
from decimal import Decimal

from app.schemas import ExtractedLine

DAY = date(2026, 9, 14)


def bill_line(
    code: str = "G0121",
    charge: str = "100.00",
    *,
    on: date | None = DAY,
    units: int = 1,
    modifier: str | None = None,
    description: str = "x",
    dose: tuple[str, str] | None = None,
) -> ExtractedLine:
    return ExtractedLine(
        service_date=on, code=code, modifier=modifier, description=description, units=units,
        charge=Decimal(charge), dose_value=Decimal(dose[0]) if dose else None, dose_unit=dose[1] if dose else None,
    )


def sample_audit(name: str, ref):
    """Run the checks on a sample's expected lines, as the app would after extraction."""
    from pathlib import Path

    from app.audit import run_checks
    from app.schemas import EobReading, ExpectedSample

    sample = ExpectedSample.model_validate_json(
        (Path(__file__).resolve().parent.parent / "samples" / name / "expected_flags.json").read_text()
    )
    lines = [ExtractedLine(**line.model_dump()) for line in sample.lines]
    eob = (
        EobReading(
            billed=sample.eob.billed, allowed=sample.eob.allowed,
            patient_responsibility=sample.eob.patient_responsibility,
        )
        if sample.eob
        else None
    )
    result = run_checks(
        lines, ref=ref, patient_type=sample.patient_type, gfe_total=sample.gfe_total,
        bill_date=sample.bill_date, amount_due=sample.amount_due, eob=eob, today=date(2026, 10, 28),
    )
    return sample, lines, result
