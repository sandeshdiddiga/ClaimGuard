"""Dose vs billing units: the dose written on a drug line divided by the drug's dose per billing unit.

Drug codes are billed per a fixed dose ("Injection, propofol, 10 mg"), so 200 mg of propofol is 20 units.
A clear mismatch is a likely error. A dose that cannot be converted to the billing unit (mL for a drug billed
per mg) or does not come to a whole number of units is worth asking about. CPT-shaped codes are never looked up.
"""

import sqlite3
from collections.abc import Sequence
from decimal import Decimal

from app.checks import wording
from app.checks.constants import ASP_SOURCE, ASP_URL
from app.codes import LEVEL_II_SHAPE
from app.findings import Evidence, Finding, evidence_lines, excess_amount, money
from app.refdb import DrugLimit, drug_limit, hcpcs_entry
from app.schemas import ExtractedLine

# Units that convert into one another: (family, size in the family's base unit).
FAMILY = {
    "MCG": ("mass", Decimal("0.001")), "MG": ("mass", Decimal(1)), "GM": ("mass", Decimal(1000)),
    "G": ("mass", Decimal(1000)), "ML": ("volume", Decimal(1)), "CC": ("volume", Decimal(1)),
    "UNIT": ("unit", Decimal(1)), "UNITS": ("unit", Decimal(1)), "IU": ("iu", Decimal(1)),
}
RULE = (
    "Drug codes are billed per a fixed dose (the HCPCS code dosage in CMS's Part B payment limit file). The dose "
    "written on the line divided by the dose per billing unit gives the number of units to bill."
)


def expected_units(line: ExtractedLine, limit: DrugLimit) -> int | None:
    """Whole billing units the written dose comes to, or None when it cannot be worked out."""
    written, per_unit = FAMILY.get(line.dose_unit or ""), FAMILY.get(limit.dose_unit or "")
    if written is None or per_unit is None or written[0] != per_unit[0]:
        return None
    units = line.dose_value * written[1] / (limit.dose_value * per_unit[1])
    return int(units) if units == units.to_integral_value() else None


def check_dose(lines: Sequence[ExtractedLine], ref: sqlite3.Connection, *, insured: bool) -> list[Finding]:
    findings = []
    for number, line in enumerate(lines, start=1):
        if line.dose_value is None or line.dose_unit is None or not LEVEL_II_SHAPE.fullmatch(line.code):
            continue
        limit = drug_limit(ref, line.code)
        if limit is None or limit.dose_value is None or limit.dose_unit is None:
            continue
        expected = expected_units(line, limit)
        if expected == line.units:
            continue
        stated = wording.dose_text(line.dose_value, line.dose_unit)
        per_unit = wording.dose_text(limit.dose_value, limit.dose_unit)
        entry = hcpcs_entry(ref, line.code)
        data_row = {"code": line.code, "dosage": limit.dosage,
                    "payment_limit": None if limit.payment_limit is None else str(limit.payment_limit),
                    "hcpcs_description": entry.long_description if entry else None}
        if expected is None:
            level, counted, amount = "amber", {}, Decimal("0.00")
            text = wording.DOSE_NEEDS_INTERPRETING.format(dose=stated, per_unit=per_unit, billed=line.units)
            computed: dict = {"stated_dose": stated, "dose_per_unit": per_unit, "billed_units": line.units}
            difference = None
        else:
            excess = max(line.units - expected, 0)
            amount = Decimal("0.00") if insured or excess == 0 else excess_amount(line, excess)
            level, counted = "red", ({number: amount} if amount > 0 else {})
            text = wording.DOSE.format(dose=stated, expected=expected, billed=line.units)
            computed = {
                "stated_dose": stated, "dose_per_unit": per_unit, "expected_units": expected,
                "billed_units": line.units, "excess_units": excess,
                "unit_charge": f"{money(line.charge / line.units):.2f}", "counted": f"{amount:.2f}",
            }
            difference = amount
        if insured:
            text = f"{text} {wording.BILLING_REVIEW}"
        findings.append(
            Finding(
                check="dose", level=level, wording=text, codes=[line.code], line_numbers=[number],
                counted=counted, dollars_at_stake=amount, expected_units=expected, billing_review=insured,
                evidence=Evidence(
                    bill_lines=evidence_lines(lines, [number]), rule=RULE, data_row=data_row, computed=computed,
                    difference=difference, source_name=ASP_SOURCE, source_url=ASP_URL,
                ),
            )
        )
    return findings
