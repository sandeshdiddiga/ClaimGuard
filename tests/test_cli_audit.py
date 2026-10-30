from pathlib import Path

import pytest

from app.cli import main

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def audit(capsys: pytest.CaptureFixture[str], reference_db_path: Path, *args: str) -> tuple[int, str, str]:
    code = main(["--reference-db", str(reference_db_path), "audit", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_maya_audit_prints_the_duplicate_and_the_deadline(capsys, reference_db_path: Path) -> None:
    code, out, _ = audit(capsys, reference_db_path, str(SAMPLES / "maya" / "bill.pdf"), "--self-pay", "--gfe", "3400")
    assert code == 0
    assert "[RED  ] duplicate lines [2, 3]" in out
    assert "Deadline: February 2, 2027." in out
    assert "dispute deadline: 2027-02-02" in out


def test_maya_audit_prints_every_finding_and_the_total(capsys, reference_db_path: Path) -> None:
    _, out, _ = audit(capsys, reference_db_path, str(SAMPLES / "maya" / "bill.pdf"), "--self-pay", "--gfe", "3400")
    assert "[RED  ] units lines [1]" in out
    assert "[AMBER] units lines [8]" in out
    assert "[RED  ] dose lines [5]" in out
    assert "dollars at stake (red findings only): $3,858.00" in out


def test_dev_audit_uses_the_eob(capsys, reference_db_path: Path) -> None:
    code, out, _ = audit(capsys, reference_db_path, str(SAMPLES / "dev" / "bill.pdf"), "--insured", "--eob", str(SAMPLES / "dev" / "eob.pdf"))
    assert code == 0
    assert "The hospital billed $1,460.00, but your insurer's EOB says you owe $410.00." in out
    assert "dollars at stake (red findings only): $1,050.00" in out
    assert "gfe" not in out


def test_clean_bill_has_no_red_lines(capsys, reference_db_path: Path) -> None:
    _, out, _ = audit(capsys, reference_db_path, str(SAMPLES / "clean" / "bill.pdf"), "--self-pay", "--gfe", "2750")
    assert "[RED" not in out and "[AMBER" not in out
    assert "dollars at stake (red findings only): $0.00" in out


def test_bad_inputs_exit_with_a_message(capsys, reference_db_path: Path, tmp_path: Path) -> None:
    doc = tmp_path / "bill.docx"
    doc.write_bytes(b"x")
    code, _, err = audit(capsys, reference_db_path, str(doc), "--self-pay")
    assert code == 1 and "unsupported" in err
    code, _, err = audit(capsys, reference_db_path, str(SAMPLES / "maya" / "bill.pdf"), "--self-pay", "--gfe", "abc")
    assert code == 1 and err.startswith("error:")
