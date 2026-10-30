"""Application state (data/state.db): cases, extracted lines and the per-call model log.

Kept apart from the read-only reference database so redeploys and downloads never touch case data.
"""

import sqlite3
import uuid
from decimal import Decimal
from pathlib import Path

from app.llm import CallRecord
from app.schemas import ExtractedLine

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id           TEXT PRIMARY KEY,
    patient_type TEXT NOT NULL CHECK (patient_type IN ('self_pay', 'insured')),
    gfe_total    TEXT,
    bill_date    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS lines (
    case_id      TEXT NOT NULL REFERENCES cases(id),
    position     INTEGER NOT NULL,
    service_date TEXT,
    code         TEXT NOT NULL,
    modifier     TEXT,
    description  TEXT NOT NULL,
    units        INTEGER NOT NULL,
    charge       TEXT NOT NULL,  -- Decimal as text, never a float
    status       TEXT NOT NULL,
    note         TEXT,
    PRIMARY KEY (case_id, position)
);
CREATE TABLE IF NOT EXISTS calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id           TEXT NOT NULL,
    step              TEXT NOT NULL,
    model             TEXT NOT NULL,
    latency_ms        INTEGER NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    ok                INTEGER NOT NULL,
    error             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    case_id  TEXT NOT NULL REFERENCES cases(id),
    position INTEGER NOT NULL,
    body     TEXT NOT NULL,  -- the Finding as JSON
    PRIMARY KEY (case_id, position)
);
CREATE TABLE IF NOT EXISTS letters (
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind    TEXT NOT NULL,
    body    TEXT NOT NULL,  -- the Letter as JSON
    PRIMARY KEY (case_id, kind)
);
"""

# Columns added after the first release; older state.db files get them on open.
CASE_COLUMNS = {
    "facility_name": "TEXT",
    "amount_due": "TEXT",
    "eob_json": "TEXT",
    "read_with": "TEXT",
    "stage": "TEXT NOT NULL DEFAULT 'confirm'",
    "lookup_json": "TEXT",  # the hospital lookup (app/lookup.py) as JSON
    "eob_note": "TEXT",  # why the EOB comparison was skipped, when it was
}
LINE_COLUMNS = {"dose_value": "TEXT", "dose_unit": "TEXT", "code_class": "TEXT"}
CASE_FIELDS = {"gfe_total", "bill_date", *CASE_COLUMNS}


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One request uses one Store, but FastAPI may run its dependency and its route in different threads.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA + EXTRA_SCHEMA)
        have = {row[1] for row in self._conn.execute("PRAGMA table_info(cases)")}
        for name, kind in CASE_COLUMNS.items():
            if name not in have:
                self._conn.execute(f"ALTER TABLE cases ADD COLUMN {name} {kind}")
        have = {row[1] for row in self._conn.execute("PRAGMA table_info(lines)")}
        for name, kind in LINE_COLUMNS.items():
            if name not in have:
                self._conn.execute(f"ALTER TABLE lines ADD COLUMN {name} {kind}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_case(self, patient_type: str, gfe_total: Decimal | None = None) -> str:
        case_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO cases (id, patient_type, gfe_total) VALUES (?, ?, ?)",
            (case_id, patient_type, None if gfe_total is None else str(gfe_total)),
        )
        self._conn.commit()
        return case_id

    def record_call(self, case_id: str, record: CallRecord) -> None:
        self._conn.execute(
            "INSERT INTO calls (case_id, step, model, latency_ms, prompt_tokens, completion_tokens, ok, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, record.step, record.model, record.latency_ms, record.prompt_tokens,
             record.completion_tokens, int(record.ok), record.error),
        )
        self._conn.commit()

    def calls(self, case_id: str) -> list[CallRecord]:
        rows = self._conn.execute(
            "SELECT step, model, latency_ms, prompt_tokens, completion_tokens, ok, error"
            " FROM calls WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        return [CallRecord(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6]) for r in rows]

    def save_lines(self, case_id: str, lines: list[ExtractedLine]) -> None:
        self._conn.execute("DELETE FROM lines WHERE case_id = ?", (case_id,))
        self._conn.executemany(
            "INSERT INTO lines (case_id, position, service_date, code, modifier, description, units,"
            " charge, status, note, dose_value, dose_unit, code_class)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (case_id, i, None if x.service_date is None else x.service_date.isoformat(), x.code,
                 x.modifier, x.description, x.units, str(x.charge), x.status, x.note,
                 None if x.dose_value is None else str(x.dose_value), x.dose_unit, x.code_class)
                for i, x in enumerate(lines, start=1)
            ],
        )
        self._conn.commit()

    def lines(self, case_id: str) -> list[ExtractedLine]:
        rows = self._conn.execute(
            "SELECT service_date, code, modifier, description, units, charge, status, note,"
            " dose_value, dose_unit, code_class FROM lines WHERE case_id = ? ORDER BY position",
            (case_id,),
        ).fetchall()
        return [
            ExtractedLine(service_date=r[0], code=r[1], modifier=r[2], description=r[3], units=r[4],
                          charge=Decimal(r[5]), status=r[6], note=r[7],
                          dose_value=None if r[8] is None else Decimal(r[8]), dose_unit=r[9], code_class=r[10])
            for r in rows
        ]

    # --- case fields, findings and letters --------------------------------------------------------

    def update_case(self, case_id: str, **fields: str | None) -> None:
        unknown = set(fields) - CASE_FIELDS
        if unknown:
            raise ValueError(f"unknown case fields: {sorted(unknown)}")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self._conn.execute(f"UPDATE cases SET {assignments} WHERE id = ?", (*fields.values(), case_id))
        self._conn.commit()

    def get_case(self, case_id: str) -> dict[str, str | None] | None:
        cursor = self._conn.execute(
            f"SELECT id, patient_type, {', '.join(['gfe_total', 'bill_date', *CASE_COLUMNS])} FROM cases WHERE id = ?",
            (case_id,),
        )
        row = cursor.fetchone()
        return None if row is None else dict(zip([c[0] for c in cursor.description], row))

    def save_findings(self, case_id: str, findings: list[str]) -> None:
        """`findings` are Finding.model_dump_json() strings."""
        self._conn.execute("DELETE FROM findings WHERE case_id = ?", (case_id,))
        self._conn.executemany(
            "INSERT INTO findings (case_id, position, body) VALUES (?, ?, ?)",
            [(case_id, i, body) for i, body in enumerate(findings, start=1)],
        )
        self._conn.commit()

    def findings(self, case_id: str) -> list[str]:
        rows = self._conn.execute("SELECT body FROM findings WHERE case_id = ? ORDER BY position", (case_id,))
        return [r[0] for r in rows]

    def save_letters(self, case_id: str, letters: dict[str, str]) -> None:
        self._conn.execute("DELETE FROM letters WHERE case_id = ?", (case_id,))
        self._conn.executemany(
            "INSERT INTO letters (case_id, kind, body) VALUES (?, ?, ?)",
            [(case_id, kind, body) for kind, body in letters.items()],
        )
        self._conn.commit()

    def letters(self, case_id: str) -> dict[str, str]:
        rows = self._conn.execute("SELECT kind, body FROM letters WHERE case_id = ? ORDER BY rowid", (case_id,))
        return dict(rows.fetchall())
