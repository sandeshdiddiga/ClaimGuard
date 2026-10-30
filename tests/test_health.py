"""The app opens the bundled, read-only reference database: it refuses to start without it and /health says so."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.refdb as refdb
from app.main import create_app
from app.refdb import ReferenceDbError, reference_is_loaded
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        reference_db=tmp_path / "data" / "claimguard.db", state_db=tmp_path / "state.db",
        samples_dir=ROOT / "samples", offline=True,
    )


def install(tmp_path: Path, source: Path) -> None:
    target = tmp_path / "data" / "claimguard.db"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(source.read_bytes())


def test_there_is_no_download_path_or_download_setting_left() -> None:
    assert not hasattr(refdb, "ensure_reference_db")
    assert not hasattr(refdb, "MAX_DOWNLOAD_BYTES")
    fields = set(Settings.__dataclass_fields__)
    assert not fields & {"reference_db_url", "reference_db_sha256", "download_client"}


def test_env_example_no_longer_lists_the_download_variables() -> None:
    text = (ROOT / ".env.example").read_text()
    assert "REFERENCE_DB_URL" not in text and "REFERENCE_DB_SHA256" not in text


def test_the_app_refuses_to_start_when_the_database_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ReferenceDbError, match="python -m ingest"):
        with TestClient(create_app(settings_for(tmp_path))):
            pass


def test_the_app_refuses_to_start_when_the_file_is_not_a_reference_database(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    sqlite3.connect(tmp_path / "data" / "claimguard.db").close()
    with pytest.raises(ReferenceDbError):
        with TestClient(create_app(settings_for(tmp_path))):
            pass


def test_the_error_message_names_no_path(tmp_path: Path) -> None:
    with pytest.raises(ReferenceDbError) as error:
        with TestClient(create_app(settings_for(tmp_path))):
            pass
    assert str(tmp_path) not in str(error.value)


def test_health_is_503_when_the_database_is_not_loaded(tmp_path: Path) -> None:
    response = TestClient(create_app(settings_for(tmp_path))).get("/health")  # no startup, nothing on disk
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "reference database not loaded"}
    assert str(tmp_path) not in response.text


def test_health_is_503_for_an_old_style_database_without_the_new_tables(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "claimguard.db")
    conn.execute("CREATE TABLE ncci_ptp (column1 TEXT)")
    conn.execute("INSERT INTO ncci_ptp VALUES ('A0001')")
    conn.commit()
    conn.close()
    assert TestClient(create_app(settings_for(tmp_path))).get("/health").status_code == 503


def test_health_is_200_with_a_loaded_database_and_starts_cleanly(tmp_path: Path, reference_db_path: Path) -> None:
    install(tmp_path, reference_db_path)
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reference_is_loaded_needs_all_three_tables_to_have_rows(tmp_path: Path, reference_db_path: Path) -> None:
    install(tmp_path, reference_db_path)
    target = tmp_path / "data" / "claimguard.db"
    assert reference_is_loaded(target)
    conn = sqlite3.connect(target)
    conn.execute("DELETE FROM mue")
    conn.commit()
    conn.close()
    assert not reference_is_loaded(target)
    assert not reference_is_loaded(tmp_path / "nope.db")


def test_health_is_503_when_a_smoke_query_fails(tmp_path: Path, reference_db_path: Path) -> None:
    install(tmp_path, reference_db_path)
    conn = sqlite3.connect(tmp_path / "data" / "claimguard.db")
    conn.execute("UPDATE drug_limits SET dose_value = 'not a number' WHERE code = (SELECT min(code) FROM drug_limits)")
    conn.commit()
    conn.close()
    assert TestClient(create_app(settings_for(tmp_path))).get("/health").status_code == 503


def test_health_is_503_if_a_reference_row_starts_with_a_digit(tmp_path: Path) -> None:
    """The shipped schema refuses such a row; a file built without that constraint must still fail health."""
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "claimguard.db")
    conn.executescript(
        "CREATE TABLE hcpcs (code TEXT PRIMARY KEY, short_description TEXT, long_description TEXT, termination_date TEXT);"
        "CREATE TABLE drug_limits (code TEXT PRIMARY KEY, dosage TEXT, dose_value TEXT, dose_unit TEXT, payment_limit TEXT);"
        "CREATE TABLE mue (code TEXT PRIMARY KEY, mue_value INTEGER, mai INTEGER, rationale TEXT);"
        "INSERT INTO hcpcs VALUES ('A0001', 's', 'l', NULL), ('00000', 's', 'l', NULL);"
        "INSERT INTO drug_limits VALUES ('J0001', '1 MG', '1', 'MG', '1.00');"
        "INSERT INTO mue VALUES ('A0001', 1, 1, 'r');"
    )
    conn.commit()
    conn.close()
    assert TestClient(create_app(settings_for(tmp_path))).get("/health").status_code == 503


def test_the_shipped_database_passes_the_smoke_query() -> None:
    from app.refdb import reference_smoke

    assert reference_smoke(ROOT / "data" / "claimguard.db")
