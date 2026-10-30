import sqlite3
from pathlib import Path

import pytest

import app.refdb as refdb
from app.refdb import code_known, drug_limit, hcpcs_entry, mue_limit, open_reference

REAL_DB = Path("data/claimguard.db")


@pytest.fixture
def conn(reference_db_path: Path):
    connection = open_reference(reference_db_path)
    yield connection
    connection.close()


def test_connection_is_read_only(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM mue")


def test_missing_database_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="reference database not found"):
        open_reference(tmp_path / "nope.db")


def test_the_ncci_and_opps_lookups_are_gone() -> None:
    for name in ("ncci_edit", "opps_entry", "NcciEdit", "OppsEntry"):
        assert not hasattr(refdb, name)


def test_a_level_ii_code_is_known_from_the_hcpcs_table(conn: sqlite3.Connection) -> None:
    assert code_known(conn, "G0121") and code_known(conn, "J2250")
    assert not code_known(conn, "Z9999")


def test_hcpcs_entry(conn: sqlite3.Connection) -> None:
    entry = hcpcs_entry(conn, "J1170")
    assert (entry.code, entry.termination_date) == ("J1170", "20240930")
    assert hcpcs_entry(conn, "Z9999") is None


def test_drug_limit_has_exact_decimals(conn: sqlite3.Connection) -> None:
    from decimal import Decimal

    limit = drug_limit(conn, "J3010")
    assert (limit.dosage, limit.dose_value, limit.dose_unit, limit.payment_limit) == (
        "0.1 MG", Decimal("0.1"), "MG", Decimal("1.362"),
    )
    nodose = drug_limit(conn, "J9029")
    assert (nodose.dose_value, nodose.dose_unit) == (None, None)
    assert drug_limit(conn, "G0121") is None


def test_mue_limit(conn: sqlite3.Connection) -> None:
    limit = mue_limit(conn, "G0121")
    assert (limit.mue_value, limit.mai, limit.rationale) == (1, 2, "Anatomic Consideration")
    assert mue_limit(conn, "Z9999") is None


@pytest.mark.skipif(not REAL_DB.exists(), reason="run `python -m ingest` first")
def test_the_real_database_has_the_rows_the_samples_rely_on() -> None:
    real = open_reference(REAL_DB)
    try:
        assert code_known(real, "G0121") and not code_known(real, "Z9999")
        assert (mue_limit(real, "G0121").mue_value, mue_limit(real, "A4216").mai) == (1, 3)
        assert str(drug_limit(real, "J2704").payment_limit) == "0.093"
    finally:
        real.close()
