import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.refdb import open_reference

from tests.fixtures.make_reference_db import FIXTURE_PATH


@pytest.fixture(scope="session")
def reference_db_path() -> Path:
    """The committed hand-written fixture, so tests never need the real CMS data."""
    assert FIXTURE_PATH.exists(), "run `python -m tests.fixtures.make_reference_db`"
    return FIXTURE_PATH


REAL_DB = Path(__file__).resolve().parent.parent / "data" / "claimguard.db"


@pytest.fixture
def ref(reference_db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = open_reference(reference_db_path)
    yield conn
    conn.close()


@pytest.fixture(params=["fixture", "real"])
def any_reference(request: pytest.FixtureRequest, reference_db_path: Path) -> Iterator[sqlite3.Connection]:
    """The hand-written fixture, and the real CMS data when it has been ingested locally."""
    if request.param == "real" and not REAL_DB.exists():
        pytest.skip("run `python -m ingest` first")
    conn = open_reference(reference_db_path if request.param == "fixture" else REAL_DB)
    yield conn
    conn.close()
