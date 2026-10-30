"""Build tests/fixtures/reference.db from the hand-written rows, so tests never need the real CMS data.

Run: python -m tests.fixtures.make_reference_db
The rows (with our own short descriptions) live in tests/fixtures/reference_rows.py.
"""

import sqlite3
from pathlib import Path

from ingest.build import create_schema, insert_drug_limits, insert_hcpcs, insert_mue
from tests.fixtures.reference_rows import DRUG_ROWS, HCPCS_ROWS, MUE_ROWS

FIXTURE_PATH = Path(__file__).with_name("reference.db")

def build(path: Path = FIXTURE_PATH) -> Path:
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    try:
        create_schema(conn)
        insert_hcpcs(conn, HCPCS_ROWS)
        insert_drug_limits(conn, DRUG_ROWS)
        insert_mue(conn, MUE_ROWS)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return path


if __name__ == "__main__":
    print(f"wrote {build()}")
