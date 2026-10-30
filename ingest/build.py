"""Build the reference SQLite database from the three CMS public-use files."""

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

from ingest.parse_drug_limits import parse_drug_limits_text
from ingest.parse_hcpcs import parse_hcpcs_lines
from ingest.parse_mue import parse_mue_text

SCHEMA = Path(__file__).with_name("schema.sql")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())


def _text(path: Path) -> str:
    # CMS files are Windows-1252; latin-1 never fails to decode.
    return path.read_text(encoding="latin-1")


def insert_hcpcs(conn: sqlite3.Connection, rows) -> int:
    data = [
        (r.code, r.short_description, r.long_description, r.added_date, r.effective_date, r.termination_date)
        for r in rows
    ]
    conn.executemany(
        "INSERT INTO hcpcs (code, short_description, long_description, added_date, effective_date,"
        " termination_date) VALUES (?, ?, ?, ?, ?, ?)",
        data,
    )
    return len(data)


def insert_drug_limits(conn: sqlite3.Connection, rows) -> int:
    data = [
        (
            r.code, r.short_description, r.dosage,
            None if r.dose_value is None else str(r.dose_value), r.dose_unit,
            None if r.payment_limit is None else str(r.payment_limit),
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT INTO drug_limits (code, short_description, dosage, dose_value, dose_unit, payment_limit)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        data,
    )
    return len(data)


def insert_mue(conn: sqlite3.Connection, rows) -> int:
    data = [(r.code, r.mue_value, r.mai, r.rationale) for r in rows]
    conn.executemany("INSERT INTO mue (code, mue_value, mai, rationale) VALUES (?, ?, ?, ?)", data)
    return len(data)


def build_reference_db(
    out: Path, *, hcpcs_file: Path, drug_limits_file: Path, mue_file: Path, built_on: date | None = None
) -> dict[str, str]:
    """Build `out` atomically and return the meta rows. The same inputs and date give identical bytes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        create_schema(conn)
        counts = {
            "hcpcs_rows": insert_hcpcs(conn, parse_hcpcs_lines(_text(hcpcs_file).splitlines())),
            "drug_limits_rows": insert_drug_limits(conn, parse_drug_limits_text(_text(drug_limits_file))),
            "mue_rows": insert_mue(conn, parse_mue_text(_text(mue_file))),
        }
        meta = {
            "built_on": (built_on or date.today()).isoformat(),
            "hcpcs_file": f"{hcpcs_file.name}={sha256_of(hcpcs_file)}",
            "drug_limits_file": f"{drug_limits_file.name}={sha256_of(drug_limits_file)}",
            "mue_file": f"{mue_file.name}={sha256_of(mue_file)}",
            **{key: str(value) for key, value in counts.items()},
        }
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
        conn.commit()
        conn.execute("VACUUM")
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    tmp.replace(out)
    return meta
