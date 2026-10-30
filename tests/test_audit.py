import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal

from app.audit import CHECK_ORDER, run_checks
from app.findings import total_dollars_at_stake
from app.schemas import EobReading
from tests.builders import bill_line

D = Decimal


def run(lines, ref, **overrides):
    args = dict(ref=ref, patient_type="self_pay", gfe_total=None, bill_date=date(2026, 10, 5), today=date(2026, 10, 28))
    return run_checks(lines, **(args | overrides))


def test_a_line_flagged_twice_is_counted_once_at_its_largest_amount(ref: sqlite3.Connection) -> None:
    """Two identical colonoscopy lines of 2 units: duplicate (line 2 in full) and 4 units against a limit of 1."""
    lines = [bill_line("G0121", "5600.00", units=2), bill_line("G0121", "5600.00", units=2)]
    result = run(lines, ref)
    assert {f.check for f in result.findings if f.level == "red"} == {"duplicate", "units"}
    # duplicate: line 2 = 5,600.00. units: 3 excess units, taken from line 2 (2 units, 5,600.00) then line 1
    # (1 unit, 2,800.00). Line 2 counts once at 5,600.00; line 1 at 2,800.00.
    assert result.dollars_at_stake == D("8400.00")


def test_amber_and_grey_findings_add_nothing(ref: sqlite3.Connection) -> None:
    result = run([bill_line("A4216", "255.00", units=30), bill_line("J2250", "68.00", units=2, dose=("2", "MG"))], ref)
    assert {f.level for f in result.findings} == {"amber", "grey"}
    assert result.dollars_at_stake == D("0.00")


def test_insured_line_findings_add_nothing_and_the_eob_difference_counts(ref: sqlite3.Connection) -> None:
    eob = EobReading(billed=D("3244.00"), allowed=D("1460.00"), patient_responsibility=D("410.00"))
    lines = [bill_line("J2405", "192.00", units=8, dose=("4", "MG")), bill_line("G0121", "5600.00", units=2)]
    result = run(lines, ref, patient_type="insured", amount_due=D("1460.00"), eob=eob)
    assert {(f.check, f.level) for f in result.findings if f.check in {"dose", "units", "eob"}} == {
        ("dose", "red"), ("units", "amber"), ("eob", "red"),
    }
    assert result.dollars_at_stake == D("1050.00")


def test_the_gfe_overage_is_shown_separately(ref: sqlite3.Connection) -> None:
    result = run([bill_line(charge="5000.00")], ref, gfe_total=D("1000.00"))
    (gfe,) = [f for f in result.findings if f.check == "gfe"]
    assert gfe.overage == D("4000.00") and result.dollars_at_stake == D("0.00")
    assert result.deadline == date(2027, 2, 2)
    assert run([bill_line(charge="5000.00")], ref, patient_type="insured", gfe_total=D("1000.00")).deadline is None


def test_a_dose_mismatch_line_gets_no_benchmark(ref: sqlite3.Connection) -> None:
    lines = [bill_line("J2704", "1100.00", units=200, dose=("200", "MG")), bill_line("J2704", "110.00", units=20, dose=("200", "MG"))]
    result = run(lines, ref)
    (bench,) = [f for f in result.findings if f.check == "drug_benchmark"]
    assert bench.line_numbers == [2] and bench.multiple == D("59.1")


def test_findings_come_in_a_stable_check_order(ref: sqlite3.Connection) -> None:
    lines = [
        bill_line("G0121", "5600.00", units=2), bill_line("J2250", "68.00", units=2, dose=("2", "MG")),
        bill_line("J2250", "68.00", units=2, dose=("2", "MG")), bill_line("J2704", "1100.00", units=200, dose=("200", "MG")),
        bill_line("A4216", "255.00", units=30),
    ]
    order = [f.check for f in run(lines, ref, gfe_total=D("100.00")).findings]
    assert order == sorted(order, key=CHECK_ORDER.index)
    assert set(order) == set(CHECK_ORDER) - {"eob"}
    assert CHECK_ORDER == ("duplicate", "dose", "units", "gfe", "eob", "drug_benchmark", "code")


def test_total_dollars_helper_counts_each_line_once(ref: sqlite3.Connection) -> None:
    lines = [bill_line("G0121", "100.00"), bill_line("G0121", "100.00")]
    result = run(lines, ref)
    # duplicate counts line 2 (100.00); units counts 1 excess unit from line 2 (100.00): line 2 once
    assert total_dollars_at_stake(result.findings, lines) == D("100.00")


def test_running_checks_makes_no_model_calls() -> None:
    """The checks are pure Python: importing and running them must not load the model client."""
    code = (
        "import sys\n"
        "import app.audit, app.checks.duplicates, app.checks.dose, app.checks.units, app.checks.gfe, app.checks.eob\n"
        "import app.checks.drug_benchmark, app.checks.codes\n"
        "assert 'openai' not in sys.modules, 'openai was imported'\n"
        "assert 'app.llm' not in sys.modules, 'app.llm was imported'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_the_old_ncci_and_opps_checks_are_gone() -> None:
    import importlib.util

    assert importlib.util.find_spec("app.checks.ncci") is None
    assert importlib.util.find_spec("app.checks.benchmark") is None


def test_the_eob_difference_is_not_added_to_a_duplicate_inside_the_same_balance() -> None:
    from decimal import Decimal

    from app.findings import Evidence, Finding, total_dollars_at_stake

    evidence = Evidence(rule="r", data_row={}, source_name="s")
    duplicate = Finding(check="duplicate", level="red", wording="w", counted={2: Decimal("300.00")},
                        dollars_at_stake=Decimal("300.00"), evidence=evidence)
    eob = Finding(check="eob", level="red", wording="w", dollars_at_stake=Decimal("1050.00"), evidence=evidence)
    assert total_dollars_at_stake([duplicate, eob], []) == Decimal("1050.00")
    small = eob.model_copy(update={"dollars_at_stake": Decimal("100.00")})
    assert total_dollars_at_stake([duplicate, small], []) == Decimal("300.00")
