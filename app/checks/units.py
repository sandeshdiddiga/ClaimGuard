"""Units over the CMS limit: Medically Unlikely Edits (MUEs) for facility outpatient hospital services.

MAI 1 is a per-line limit; MAI 2 (absolute) and MAI 3 (clinical judgment) are per code per day, adding up
every line on that day. MAI 1 or 2 over the limit is a likely error; MAI 3 is worth asking about (Ultra
reviews it). For insured patients every MUE finding is worth asking about: the limits are Medicare's.
Only the excess units count, taken from the last line(s) of the group at each line's own unit charge.
An MUE of 0 gives no limit to compare against and is skipped. CPT-shaped codes are never looked up.
"""

import sqlite3
from collections.abc import Sequence
from decimal import Decimal

from app.checks import wording
from app.checks.constants import MUE_SOURCE, MUE_URL
from app.codes import LEVEL_II_SHAPE
from app.findings import Evidence, Finding, evidence_lines, excess_amount
from app.refdb import MueLimit, hcpcs_entry, mue_limit
from app.schemas import ExtractedLine

MAI_MEANING = {1: "per line", 2: "per day, an absolute limit", 3: "per day, allowing clinical judgment"}


def _description(ref: sqlite3.Connection, code: str) -> str | None:
    entry = hcpcs_entry(ref, code)
    return entry.long_description if entry else None


def check_units(lines: Sequence[ExtractedLine], ref: sqlite3.Connection, *, insured: bool) -> list[Finding]:
    limits: dict[str, MueLimit | None] = {}
    groups: dict[tuple, list[int]] = {}
    for number, line in enumerate(lines, start=1):
        if not LEVEL_II_SHAPE.fullmatch(line.code):
            continue
        if line.code not in limits:
            limits[line.code] = mue_limit(ref, line.code)
        limit = limits[line.code]
        if limit is None or limit.mue_value == 0:
            continue
        per_line = limit.mai == 1 or line.service_date is None
        key = (line.code, "line", number) if per_line else (line.code, "day", line.service_date)
        groups.setdefault(key, []).append(number)

    findings = []
    for key, numbers in groups.items():
        code = key[0]
        limit = limits[code]
        billed = sum(lines[n - 1].units for n in numbers)
        if billed <= limit.mue_value:
            continue
        excess = billed - limit.mue_value
        red = limit.mai in (1, 2) and not insured
        counted: dict[int, Decimal] = {}
        if red:
            remaining = excess
            for n in reversed(numbers):
                take = min(remaining, lines[n - 1].units)
                if take == 0:
                    break
                counted[n] = excess_amount(lines[n - 1], take)
                remaining -= take
        amount = sum(counted.values(), Decimal("0.00"))
        text = wording.UNITS.format(limit=limit.mue_value, billed=billed)
        if insured:
            text = f"{text} {wording.BILLING_REVIEW}"
        findings.append(
            Finding(
                check="units", level="red" if red else "amber", wording=text, codes=[code], line_numbers=numbers,
                counted=counted, dollars_at_stake=amount, mue_value=limit.mue_value, mai=limit.mai,
                billing_review=insured,
                evidence=Evidence(
                    bill_lines=evidence_lines(lines, numbers),
                    rule=(
                        f"CMS's Medically Unlikely Edit for this code allows at most {limit.mue_value} units "
                        f"{MAI_MEANING[limit.mai]} (MUE adjudication indicator {limit.mai})."
                    ),
                    data_row={
                        "code": code, "mue_value": limit.mue_value, "mai": limit.mai, "rationale": limit.rationale,
                        "hcpcs_description": _description(ref, code),
                    },
                    computed={"billed_units": billed, "limit": limit.mue_value, "excess_units": excess, "counted": f"{amount:.2f}"},
                    difference=amount if red else None, source_name=MUE_SOURCE, source_url=MUE_URL,
                ),
            )
        )
    return findings
