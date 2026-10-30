"""The committed fixture must match its source rows, hold only Level II codes and contain no real CMS text."""

import sqlite3
from pathlib import Path

from tests.fixtures.make_reference_db import FIXTURE_PATH, build
from tests.fixtures.reference_rows import DRUG_ROWS, HCPCS_ROWS, MUE_ROWS

NEW_TABLES = ("hcpcs", "drug_limits", "mue")


def contents(path: Path, tables: tuple[str, ...] = NEW_TABLES) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}
    finally:
        conn.close()


def test_committed_fixture_matches_a_fresh_build(tmp_path: Path) -> None:
    assert contents(FIXTURE_PATH) == contents(build(tmp_path / "fresh.db"))


def test_fixture_is_small_and_hand_written() -> None:
    data = contents(FIXTURE_PATH)
    assert len(data["hcpcs"]) == len(HCPCS_ROWS) <= 16
    assert len(data["drug_limits"]) == len(DRUG_ROWS) <= 16
    assert len(data["mue"]) == len(MUE_ROWS) <= 16


def test_fixture_codes_are_all_letter_first() -> None:
    conn = sqlite3.connect(FIXTURE_PATH)
    try:
        for table in NEW_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE code GLOB '[0-9]*'").fetchone() == (0,)
    finally:
        conn.close()


def test_fixture_covers_each_case_the_tests_rely_on() -> None:
    data = contents(FIXTURE_PATH)
    assert {row[2] for row in data["mue"]} == {1, 2, 3}  # an MAI 1, 2 and 3 code
    dosages = {row[0]: (row[3], row[4]) for row in data["drug_limits"]}
    assert dosages["J2250"] == ("1", "MG")  # a parsed per-1-mg drug
    assert any(value is None for value, _ in dosages.values())  # an unparseable dosage
