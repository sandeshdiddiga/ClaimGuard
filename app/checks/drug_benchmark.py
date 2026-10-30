"""Medicare drug benchmark: charge per billing unit as a multiple of the Part B payment limit. Context only.

One finding per drug code with a payment limit and a parsed dosage, over its lines. Lines with a dose finding
are skipped: their per-unit price is distorted. Never counted. CPT-shaped codes are never looked up.
"""

import sqlite3
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.checks import wording
from app.checks.constants import ASP_SOURCE, ASP_URL
from app.codes import LEVEL_II_SHAPE
from app.findings import Evidence, Finding, evidence_lines
from app.refdb import drug_limit
from app.schemas import ExtractedLine

RULE = (
    "Charge per billing unit compared with Medicare's national Part B payment limit per unit for this drug. "
    "Context only: charging above Medicare is not an error."
)


def check_drug_benchmark(lines: Sequence[ExtractedLine], ref: sqlite3.Connection, *, skip: set[int]) -> list[Finding]:
    by_code: dict[str, list[int]] = {}
    for number, line in enumerate(lines, start=1):
        if number not in skip and LEVEL_II_SHAPE.fullmatch(line.code):
            by_code.setdefault(line.code, []).append(number)

    findings = []
    for code, numbers in by_code.items():
        limit = drug_limit(ref, code)
        if limit is None or limit.dose_value is None or not limit.payment_limit:
            continue
        first = lines[numbers[0] - 1]
        per_unit = first.charge / first.units
        multiple = (per_unit / limit.payment_limit).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        findings.append(
            Finding(
                check="drug_benchmark", level="grey", wording=wording.DRUG_BENCHMARK.format(multiple=multiple),
                codes=[code], line_numbers=numbers, multiple=multiple,
                evidence=Evidence(
                    bill_lines=evidence_lines(lines, numbers), rule=RULE,
                    data_row={"code": code, "dosage": limit.dosage, "payment_limit": str(limit.payment_limit)},
                    computed={"charge_per_unit": f"{per_unit.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}", "multiple": str(multiple)},
                    source_name=ASP_SOURCE, source_url=ASP_URL,
                ),
            )
        )
    return findings
