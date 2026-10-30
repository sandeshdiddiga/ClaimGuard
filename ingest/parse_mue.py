"""Parse the NCCI MUE table for facility outpatient hospital services (.csv).

The file opens with a notice, then a header whose first cell is "HCPCS/ CPT Code", then one row per code:
code, MUE value, MUE adjudication indicator ("3 Date of Service Edit: Clinical"), rationale. Only Level II
codes are kept. A value or indicator that cannot be read is an error, never a guess.
"""

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass

from ingest.codes import clean_code, is_level_ii

MAI_VALUES = {"1", "2", "3"}


@dataclass(frozen=True)
class MueRow:
    code: str
    mue_value: int
    mai: int  # 1 line edit, 2 absolute date-of-service edit, 3 clinical date-of-service edit
    rationale: str


def parse_mue_text(text: str) -> Iterator[MueRow]:
    in_table = False
    for row in csv.reader(io.StringIO(text)):
        if not in_table:
            in_table = bool(row) and row[0].strip().upper().startswith("HCPCS")
            continue
        if len(row) < 4 or not row[0].strip():
            continue
        code = clean_code(row[0])
        if not is_level_ii(code):
            continue
        value = row[1].strip()
        if not value.isdigit():
            raise ValueError(f"MUE value for {code} is not a whole number")
        indicator = row[2].strip()[:1]
        if indicator not in MAI_VALUES:
            raise ValueError(f"MAI for {code} is not 1, 2 or 3")
        yield MueRow(code, int(value), int(indicator), row[3].strip())
    if not in_table:
        raise ValueError("no header row found in the MUE table")
