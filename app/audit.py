"""Run every check on a bill. Pure Python: no model is called here, and none may decide an outcome."""

import sqlite3
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.checks.codes import check_codes
from app.checks.dose import check_dose
from app.checks.drug_benchmark import check_drug_benchmark
from app.checks.duplicates import check_duplicates
from app.checks.eob import check_eob
from app.checks.gfe import check_gfe
from app.checks.units import check_units
from app.findings import Finding, total_dollars_at_stake
from app.schemas import EobReading, ExtractedLine

CHECK_ORDER = ("duplicate", "dose", "units", "gfe", "eob", "drug_benchmark", "code")


class AuditResult(BaseModel):
    findings: list[Finding]
    dollars_at_stake: Decimal  # the likely-error total: red findings, each line once, plus the EOB difference
    deadline: date | None  # Good Faith Estimate dispute deadline, when that check fired


def run_checks(
    lines: Sequence[ExtractedLine],
    *,
    ref: sqlite3.Connection,
    patient_type: str,
    gfe_total: Decimal | None = None,
    bill_date: date | None = None,
    amount_due: Decimal | None = None,
    eob: EobReading | None = None,
    today: date | None = None,
) -> AuditResult:
    insured = patient_type == "insured"
    dose = check_dose(lines, ref, insured=insured)
    findings = [
        *check_duplicates(lines),
        *dose,
        *check_units(lines, ref, insured=insured),
        *check_gfe(lines, patient_type=patient_type, gfe_total=gfe_total, bill_date=bill_date, today=today),
        *check_eob(amount_due, eob),
        *check_drug_benchmark(lines, ref, skip={n for f in dose for n in f.line_numbers}),
        *check_codes(lines, ref),
    ]
    deadline = next((f.deadline for f in findings if f.check == "gfe"), None)
    return AuditResult(
        findings=findings, dollars_at_stake=total_dollars_at_stake(findings, lines), deadline=deadline
    )
