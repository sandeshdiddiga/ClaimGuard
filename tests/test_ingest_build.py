"""Building data/claimguard.db from the three CMS zips: schema, meta, atomic build, and the zero-AMA guarantees."""

import re
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import pytest

from ingest.__main__ import find_inputs, main
from ingest.build import build_reference_db, sha256_of
from tests.test_ingest_parse import DRUG_CSV, MUE_CSV, hcpcs_continuation, hcpcs_first_line

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "claimguard.db"
CPT_SHAPED = re.compile(r"(?<![\w$.,-])(\d{5}|\d{4}[FTU])(?!\w)")

HCPCS_LINES = [
    hcpcs_first_line("X0001", "Example injection, per 1 mg", "Example inj"),
    hcpcs_continuation("X0001", "second part"),
    hcpcs_first_line("X0002", "Ended code (list separately in addition to 00001)", "Ended", term="20231231"),
    hcpcs_first_line("12345", "Not Level II", "Dropped"),
    hcpcs_first_line("J0001", "Example sedative, per 1 mg", "Example sedative"),
]


@pytest.fixture
def raw(tmp_path: Path) -> dict[str, Path]:
    files = {
        "hcpcs": tmp_path / "HCPC_ANWEB.txt",
        "drug": tmp_path / "payment_limit.csv",
        "mue": tmp_path / "mue.csv",
    }
    files["hcpcs"].write_text("\n".join(HCPCS_LINES) + "\n", encoding="latin-1")
    files["drug"].write_text(DRUG_CSV, encoding="latin-1")
    files["mue"].write_text(MUE_CSV, encoding="latin-1")
    return files


def build(raw: dict[str, Path], out: Path, built_on: date = date(2026, 10, 30)) -> dict[str, str]:
    return build_reference_db(out, hcpcs_file=raw["hcpcs"], drug_limits_file=raw["drug"], mue_file=raw["mue"], built_on=built_on)


def rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# --- schema and contents ---------------------------------------------------------------------------------


def test_only_the_reference_tables_exist(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    tables = {r[0] for r in rows(out, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"hcpcs", "drug_limits", "mue", "meta"}


def test_hcpcs_table(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    got = rows(out, "SELECT code, short_description, long_description, termination_date FROM hcpcs ORDER BY code")
    assert got == [
        ("J0001", "Example sedative", "Example sedative, per 1 mg", None),
        ("X0001", "Example inj", "Example injection, per 1 mg second part", None),
        ("X0002", "Ended", "Ended code (list separately in addition to [CPT code])", "20231231"),
    ]


def test_drug_limits_table_keeps_dosage_as_written_plus_parsed_dose(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    got = rows(out, "SELECT code, dosage, dose_value, dose_unit, payment_limit FROM drug_limits ORDER BY code")
    assert got == [
        ("J0001", "1 MG", "1", "MG", "0.167"),
        ("J0002", "Per Therapeutic Dose", None, None, "12.500"),
        ("J0003", "10 MG/3MG", None, None, None),
        ("Q0001", "1 ML", "1", "ML", "0.186"),
    ]


def test_mue_table(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    assert rows(out, "SELECT code, mue_value, mai, rationale FROM mue ORDER BY code") == [
        ("A0001", 100, 3, "Prescribing Information"),
        ("G0001", 1, 2, "Anatomic Consideration"),
        ("J0001", 30, 1, "CMS Policy"),
    ]


def test_no_reference_row_has_a_code_starting_with_a_digit(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    for table in ("hcpcs", "drug_limits", "mue"):
        assert rows(out, f"SELECT COUNT(*) FROM {table} WHERE code GLOB '[0-9]*'") == [(0,)], table
        assert rows(out, f"SELECT COUNT(*) FROM {table}")[0][0] > 0, table


def test_the_schema_itself_refuses_a_digit_first_code_or_a_bad_mai(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    conn = sqlite3.connect(out)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO hcpcs (code, short_description, long_description, added_date, effective_date) VALUES ('12345', 'x', 'x', '20260101', '20260101')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO mue (code, mue_value, mai, rationale) VALUES ('A9999', 1, 4, 'x')")
    finally:
        conn.close()


def test_mai_values_are_only_1_2_or_3(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    build(raw, out)
    assert {r[0] for r in rows(out, "SELECT DISTINCT mai FROM mue")} <= {1, 2, 3}


# --- meta ------------------------------------------------------------------------------------------------


def test_meta_records_source_names_hashes_row_counts_and_build_date(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    returned = build(raw, out)
    meta = dict(rows(out, "SELECT key, value FROM meta"))
    assert meta == returned
    assert meta["built_on"] == "2026-10-30"
    assert meta["hcpcs_file"] == f"HCPC_ANWEB.txt={sha256_of(raw['hcpcs'])}"
    assert meta["drug_limits_file"] == f"payment_limit.csv={sha256_of(raw['drug'])}"
    assert meta["mue_file"] == f"mue.csv={sha256_of(raw['mue'])}"
    assert (meta["hcpcs_rows"], meta["drug_limits_rows"], meta["mue_rows"]) == ("3", "4", "3")
    assert re.fullmatch(r"[0-9a-f]{64}", sha256_of(raw["hcpcs"]))


# --- the build itself ------------------------------------------------------------------------------------


def test_build_is_atomic_and_replaces_an_existing_file(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "data" / "claimguard.db"
    out.parent.mkdir()
    out.write_bytes(b"old database")
    build(raw, out)
    assert [p.name for p in out.parent.iterdir()] == ["claimguard.db"]  # no .tmp left behind
    assert rows(out, "SELECT COUNT(*) FROM hcpcs") == [(3,)]


def test_a_failed_build_leaves_the_existing_database_untouched(raw: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "claimguard.db"
    out.write_bytes(b"old database")
    raw["mue"].write_text(MUE_CSV + "V0001,1,9 Bogus,CMS Policy\n", encoding="latin-1")
    with pytest.raises(ValueError):
        build(raw, out)
    assert out.read_bytes() == b"old database"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("claimguard")] == ["claimguard.db"]


def test_same_inputs_and_date_give_identical_bytes(raw: dict[str, Path], tmp_path: Path) -> None:
    build(raw, tmp_path / "a.db")
    build(raw, tmp_path / "b.db")
    assert (tmp_path / "a.db").read_bytes() == (tmp_path / "b.db").read_bytes()


# --- python -m ingest: finding the zips and reading the right member -------------------------------------


def make_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text.encode("latin-1"))
    return path


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "raw"
    directory.mkdir()
    make_zip(directory / "hcpc2026_oct_anweb_09232026 (1).zip", {
        "HCPC2026_OCT_ANWEB_09232026.txt": "\n".join(HCPCS_LINES) + "\n",
        "HCPC2026_recordlayout.txt": "not the data file",
        "proc_notes_OCT2026.txt": "not the data file",
        "HCPC2026_OCT_ANWEB_Transaction Report_09262026.xlsx": "binary",
    })
    make_zip(directory / "october_2026_medicare_part_b_payment_limit_file_091626-final_file.zip", {
        "section 508 version of October 2026 Medicare Part B Payment Limit File 091626.csv": DRUG_CSV,
        "section 508 version of October 2026 Drugs Not Payable Under Part B 091426.csv": "HCPCS Code,x\nJ9999,y\n",
        "October 2026 Medicare Part B Payment Limit File 091626.xls": "binary",
    })
    make_zip(directory / "facilityoutpatienthospitalservicesmuetable-effective-10-01-2026.zip", {
        "MCR_MUE_OutpatientHospitalServices_Eff_10-01-2026.csv": MUE_CSV,
        "MCR_MUE_OutpatientHospitalServices_Eff_10-01-2026.xlsx": "binary",
    })
    return directory


def test_main_builds_the_database_from_the_three_zips(raw_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out" / "claimguard.db"
    assert main(["--raw-dir", str(raw_dir), "--out", str(out)]) == 0
    assert rows(out, "SELECT COUNT(*) FROM hcpcs") == [(3,)]
    assert rows(out, "SELECT COUNT(*) FROM drug_limits") == [(4,)]
    assert rows(out, "SELECT COUNT(*) FROM mue") == [(3,)]
    meta = dict(rows(out, "SELECT key, value FROM meta"))
    assert meta["hcpcs_file"].startswith("HCPC2026_OCT_ANWEB_09232026.txt=")
    assert meta["drug_limits_file"].startswith("section 508 version of October 2026 Medicare Part B Payment Limit File 091626.csv=")
    assert meta["mue_file"].startswith("MCR_MUE_OutpatientHospitalServices_Eff_10-01-2026.csv=")
    printed = capsys.readouterr().out
    assert "hcpcs" in printed and "drug_limits" in printed and "mue" in printed


@pytest.mark.parametrize("missing", ["hcpc", "payment_limit", "mue"])
def test_a_missing_zip_is_a_clear_error(raw_dir: Path, missing: str) -> None:
    next(p for p in raw_dir.iterdir() if missing in p.name.lower()).unlink()
    with pytest.raises(SystemExit, match=missing):
        find_inputs(raw_dir)


def test_a_zip_member_over_the_size_cap_is_refused(raw_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.__main__.MAX_MEMBER_BYTES", 100)
    with pytest.raises(SystemExit, match="too large"):
        main(["--raw-dir", str(raw_dir), "--out", str(tmp_path / "claimguard.db")])


# --- the real database, when it has been built locally --------------------------------------------------

real = pytest.mark.skipif(not REAL_DB.exists(), reason="run `python -m ingest` first")


@real
def test_real_database_has_only_the_reference_tables_and_no_old_cms_tables() -> None:
    tables = {r[0] for r in rows(REAL_DB, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"hcpcs", "drug_limits", "mue", "meta"}


@real
@pytest.mark.parametrize("table", ["hcpcs", "drug_limits", "mue"])
def test_real_database_rows_never_start_with_a_digit(table: str) -> None:
    assert rows(REAL_DB, f"SELECT COUNT(*) FROM {table}")[0][0] > 0
    assert rows(REAL_DB, f"SELECT COUNT(*) FROM {table} WHERE code GLOB '[0-9]*'") == [(0,)]


@real
def test_real_database_mai_values_are_1_2_or_3() -> None:
    assert {r[0] for r in rows(REAL_DB, "SELECT DISTINCT mai FROM mue")} <= {1, 2, 3}


@real
def test_real_database_descriptions_carry_no_cpt_shaped_code() -> None:
    for text, in rows(REAL_DB, "SELECT short_description || ' ' || long_description FROM hcpcs"):
        assert not CPT_SHAPED.search(text), text
    for text, in rows(REAL_DB, "SELECT short_description FROM drug_limits"):
        assert not CPT_SHAPED.search(text), text


@real
def test_real_database_meta_row_counts_match_the_tables() -> None:
    meta = dict(rows(REAL_DB, "SELECT key, value FROM meta"))
    for table in ("hcpcs", "drug_limits", "mue"):
        assert meta[f"{table}_rows"] == str(rows(REAL_DB, f"SELECT COUNT(*) FROM {table}")[0][0])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["built_on"])


@real
def test_real_database_has_the_codes_the_demo_will_need() -> None:
    assert rows(REAL_DB, "SELECT dose_value, dose_unit, payment_limit FROM drug_limits WHERE code = 'J2250'") == [("1", "MG", "0.167")]
    assert rows(REAL_DB, "SELECT mue_value, mai FROM mue WHERE code = 'G0121'") == [(1, 2)]
    assert rows(REAL_DB, "SELECT COUNT(*) FROM hcpcs WHERE code = 'G0121' AND termination_date IS NULL") == [(1,)]
