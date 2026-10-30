"""Every bill code falls into exactly one class. CPT-shaped codes are shown but never looked up."""

import sqlite3
from pathlib import Path

import pytest

from app.codes import NOT_CHECKED_NOTE, UNKNOWN_NOTE, classify_code, normalize_code, repair_level2
from app.refdb import open_reference


@pytest.fixture
def ref(reference_db_path: Path):
    conn = open_reference(reference_db_path)
    yield conn
    conn.close()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("G0121", "hcpcs_level2"),
        ("J2250", "hcpcs_level2"),
        (" g0121 ", "hcpcs_level2"),  # normalized first
        ("J-2250", "hcpcs_level2"),
        ("Z9999", "unknown_level2"),  # a letter code that is not in the table
        ("D0120", "unknown_level2"),  # dental codes are not in the CMS Level II list we hold
        # CPT-shaped: five digits, or four digits plus F, T or U. Synthetic values, never looked up.
        ("00000", "cpt_shaped"),
        ("0000F", "cpt_shaped"),
        ("0000T", "cpt_shaped"),
        ("0000U", "cpt_shaped"),
        ("00 000", "cpt_shaped"),
        ("", "missing"),
        ("   ", "missing"),
        ("???", "missing"),
        ("garbage", "missing"),
        ("0000I", "missing"),  # looks like a misread, not a code
        ("1234", "missing"),
        ("123456", "missing"),
    ],
)
def test_classify_code(ref: sqlite3.Connection, raw: str, expected: str) -> None:
    assert classify_code(ref, raw) == expected


class SpyConnection:
    """Records every statement, so a test can prove nothing was looked up."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, *args):
        self.statements.append(sql)
        raise AssertionError("no query may run for this code")


@pytest.mark.parametrize("code", ["00000", "0000F", "0000T", "0000U"])
def test_a_cpt_shaped_code_is_never_looked_up(code: str) -> None:
    spy = SpyConnection()
    assert classify_code(spy, code) == "cpt_shaped"
    assert spy.statements == []


@pytest.mark.parametrize("code", ["", "???", "garbage"])
def test_a_missing_code_is_never_looked_up(code: str) -> None:
    spy = SpyConnection()
    assert classify_code(spy, code) == "missing"
    assert spy.statements == []


def test_a_level_ii_code_is_looked_up_exactly_once(ref: sqlite3.Connection) -> None:
    seen: list[str] = []
    ref.set_trace_callback(seen.append)
    try:
        classify_code(ref, "G0121")
    finally:
        ref.set_trace_callback(None)
    assert len(seen) == 1 and "hcpcs" in seen[0]


def test_the_two_notes_are_the_wording_the_spec_asks_for() -> None:
    assert NOT_CHECKED_NOTE == "Not checked: CPT codes need an AMA license, which this demo doesn't use."
    assert UNKNOWN_NOTE == "Not in CMS's current HCPCS list."


@pytest.mark.parametrize("raw, expected", [(" g0121 ", "G0121"), ("J-2250", "J2250"), ("00 000", "00000"), ("", "")])
def test_normalize_code(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


# --- OCR repair applies to Level II codes only: the first character is a letter and is never changed ----------


@pytest.mark.parametrize(
    "code, repaired",
    [
        ("J22SO", "J2250"),  # S -> 5, O -> 0
        ("G012I", "G0121"),
        ("J2250", None),  # nothing to repair
        ("L1000", None),  # a letter in first position stays a letter (L, S and B are real Level II prefixes)
        ("S0O12", "S0012"),
        ("0000I", None),  # digit-first codes are never repaired: they are never looked up
        ("ZZZZZ", None),  # five changes would be noise, not a misread
    ],
)
def test_repair_level_ii_only_fixes_the_four_digits(code: str, repaired: str | None) -> None:
    assert repair_level2(code) == repaired
