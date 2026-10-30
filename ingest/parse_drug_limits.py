"""Parse the Medicare Part B payment limit file (the section 508 .csv; it starts with a few notice rows).

Only Level II drug codes are kept. The dosage per billing unit is stored as CMS wrote it and also parsed into
a number and a unit when it is one amount and one unit ("1 MG", "0.1 MG"); anything else ("Per Therapeutic
Dose", "10 MG/3MG") parses to nothing, because a guessed dose would produce a wrong finding.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

from ingest.codes import clean_code, is_level_ii, redact_cpt_codes

HEADER_FIRST_CELL = "HCPCS Code"
DOSAGE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)\s*([A-Za-z]+)")
MONEY = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class DrugLimitRow:
    code: str
    short_description: str
    dosage: str
    dose_value: Decimal | None
    dose_unit: str | None
    payment_limit: Decimal | None  # dollars per billing unit


def parse_dosage(text: str) -> tuple[Decimal | None, str | None]:
    match = DOSAGE.fullmatch(text.strip())
    if match is None:
        return None, None
    return Decimal(match.group(1).replace(",", "")), match.group(2).upper()


def parse_drug_limits_text(text: str) -> Iterator[DrugLimitRow]:
    rows = csv.reader(io.StringIO(text))
    index: dict[str, int] | None = None
    for row in rows:
        if index is None:
            if row and row[0].strip() == HEADER_FIRST_CELL:
                names = [cell.strip() for cell in row]
                index = {
                    key: names.index(label)
                    for key, label in (
                        ("code", "HCPCS Code"), ("short", "Short Description"),
                        ("dosage", "HCPCS Code Dosage"), ("limit", "Payment Limit"),
                    )
                }
            continue
        if len(row) <= max(index.values()):
            continue
        code = clean_code(row[index["code"]])
        if not is_level_ii(code):
            continue
        dosage = row[index["dosage"]].strip()
        value, unit = parse_dosage(dosage)
        limit = row[index["limit"]].strip()
        yield DrugLimitRow(
            code=code,
            short_description=redact_cpt_codes(row[index["short"]].strip()),
            dosage=dosage,
            dose_value=value,
            dose_unit=unit,
            payment_limit=Decimal(limit) if MONEY.fullmatch(limit) else None,
        )
    if index is None:
        raise ValueError(f"no '{HEADER_FIRST_CELL}' header row found in the payment limit file")
