"""Read-only access to the reference database (CMS public-use Level II data).

The database is bundled with the app: data/claimguard.db holds hcpcs, drug_limits and mue (and meta), all
HCPCS Level II. Money and doses are stored as exact decimal text and come back as Decimal.
"""

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REQUIRED_TABLES = ("hcpcs", "drug_limits", "mue")


class ReferenceDbError(RuntimeError):
    """The reference database is missing or empty. The app must not start."""


@dataclass(frozen=True)
class HcpcsEntry:
    code: str
    short_description: str
    long_description: str
    termination_date: str | None  # YYYYMMDD; None while the code is live


@dataclass(frozen=True)
class DrugLimit:
    code: str
    dosage: str  # as CMS wrote it, e.g. "10 MG"
    dose_value: Decimal | None  # parsed; None when the dosage is not one amount and one unit
    dose_unit: str | None
    payment_limit: Decimal | None  # dollars per billing unit


@dataclass(frozen=True)
class MueLimit:
    code: str
    mue_value: int
    mai: int  # 1 per line, 2 per day (absolute), 3 per day (clinical judgment)
    rationale: str


def open_reference(path: Path) -> sqlite3.Connection:
    """Open read-only so nothing in the app can modify or lock the downloaded file."""
    if not path.exists():
        raise FileNotFoundError(f"reference database not found: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)


def code_known(conn: sqlite3.Connection, code: str) -> bool:
    """True if the code is in the CMS HCPCS (Level II) table."""
    return conn.execute("SELECT 1 FROM hcpcs WHERE code = ?", (code,)).fetchone() is not None


def hcpcs_entry(conn: sqlite3.Connection, code: str) -> HcpcsEntry | None:
    row = conn.execute(
        "SELECT code, short_description, long_description, termination_date FROM hcpcs WHERE code = ?", (code,)
    ).fetchone()
    return HcpcsEntry(*row) if row else None


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def drug_limit(conn: sqlite3.Connection, code: str) -> DrugLimit | None:
    row = conn.execute(
        "SELECT code, dosage, dose_value, dose_unit, payment_limit FROM drug_limits WHERE code = ?", (code,)
    ).fetchone()
    return DrugLimit(row[0], row[1], _decimal(row[2]), row[3], _decimal(row[4])) if row else None


def mue_limit(conn: sqlite3.Connection, code: str) -> MueLimit | None:
    row = conn.execute("SELECT code, mue_value, mai, rationale FROM mue WHERE code = ?", (code,)).fetchone()
    return MueLimit(*row) if row else None


def reference_is_loaded(path: Path) -> bool:
    """True when `path` opens as a reference database whose three tables all have rows (cheap: no counting)."""
    try:
        conn = open_reference(path)
    except (FileNotFoundError, sqlite3.Error):
        return False
    try:
        return all(
            conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None for table in REQUIRED_TABLES
        )
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def reference_smoke(path: Path) -> bool:
    """The /health check: the file opens read-only and the real lookups work on a row from each table.

    Goes further than `reference_is_loaded`: it reads one code from each table back through the same functions
    the checks use, so a truncated, wrong-schema or corrupted file fails here and not on a patient's bill. It also
    fails if any code starts with a digit (Zero AMA: reference rows are Level II letter codes only)."""
    try:
        conn = open_reference(path)
    except (FileNotFoundError, sqlite3.Error):
        return False
    try:
        for table, lookup in (("hcpcs", hcpcs_entry), ("drug_limits", drug_limit), ("mue", mue_limit)):
            row = conn.execute(f"SELECT code FROM {table} LIMIT 1").fetchone()
            if row is None or lookup(conn, row[0]) is None:
                return False
            if conn.execute(f"SELECT 1 FROM {table} WHERE substr(code, 1, 1) NOT BETWEEN 'A' AND 'Z' LIMIT 1").fetchone():
                return False
        return True
    except (sqlite3.Error, ArithmeticError, ValueError):
        return False
    finally:
        conn.close()
