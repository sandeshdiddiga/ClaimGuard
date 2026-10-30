"""Classify every code on a bill. Pure Python: a model never decides what a code is.

hcpcs_level2   a letter code that is in the CMS HCPCS table
unknown_level2 a letter code that is not in the table ("Not in CMS's current HCPCS list.")
cpt_shaped     five digits, or four digits plus F, T or U. Shown unchanged and NEVER looked up: CPT codes
               and descriptions belong to the AMA, and this demo holds none of them
missing        no usable code on the line (empty, or text that cannot be a code)
"""

import re
import sqlite3
from typing import Literal

CodeClass = Literal["hcpcs_level2", "unknown_level2", "cpt_shaped", "missing"]

CPT_SHAPED = re.compile(r"\d{5}|\d{4}[FTU]")
LEVEL_II_SHAPE = re.compile(r"[A-Z]\d{4}")
OCR_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})

NOT_CHECKED_NOTE = "Not checked: CPT codes need an AMA license, which this demo doesn't use."
UNKNOWN_NOTE = "Not in CMS's current HCPCS list."
MISSING_NOTE = "no recognizable code on this line"


def normalize_code(raw: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", raw).upper()


def classify_code(conn: sqlite3.Connection, raw: str) -> CodeClass:
    """The class of a code. Only a Level II-shaped code reaches the database, and only once."""
    code = normalize_code(raw)
    if CPT_SHAPED.fullmatch(code):
        return "cpt_shaped"
    if LEVEL_II_SHAPE.fullmatch(code):
        found = conn.execute("SELECT 1 FROM hcpcs WHERE code = ?", (code,)).fetchone()
        return "hcpcs_level2" if found else "unknown_level2"
    return "missing"


def class_note(code_class: CodeClass) -> str | None:
    return {"cpt_shaped": NOT_CHECKED_NOTE, "unknown_level2": UNKNOWN_NOTE, "missing": MISSING_NOTE}.get(code_class)


def repair_level2(code: str) -> str | None:
    """Fix OCR letter/digit confusions in the four digits of a Level II-shaped code.

    The first character is a letter and is never changed (L, S and B are real prefixes). Only one or two
    characters may change; a string that needs more is noise, not a misread. Digit-first codes are not
    repaired: they are never looked up, so there would be nothing to check a repair against."""
    if not re.fullmatch(r"[A-Z][0-9A-Z]{4}", code):
        return None
    fixed = code[0] + code[1:].translate(OCR_CONFUSIONS)
    changed = sum(a != b for a, b in zip(code, fixed))
    return fixed if 0 < changed <= 2 and LEVEL_II_SHAPE.fullmatch(fixed) else None
