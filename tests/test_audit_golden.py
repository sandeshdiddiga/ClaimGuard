"""Golden tests: run every check on each sample bill and compare with samples/<name>/expected_flags.json.

The expected files are derived from the CMS data independently of the check code (tests/test_samples.py), so
they are the oracle. Findings are compared before any Ultra review of amber flags.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.audit import run_checks
from app.schemas import EobReading, ExpectedFlag, ExpectedSample, ExtractedLine

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
NAMES = ["maya", "dev", "clean"]
TODAY = date(2026, 10, 28)
FLAG_FIELDS = set(ExpectedFlag.model_fields)


def load(name: str) -> ExpectedSample:
    return ExpectedSample.model_validate_json((SAMPLES / name / "expected_flags.json").read_text())


def audit(name: str, ref: sqlite3.Connection):
    sample = load(name)
    lines = [ExtractedLine(**line.model_dump()) for line in sample.lines]
    eob = (
        EobReading(
            billed=sample.eob.billed, allowed=sample.eob.allowed,
            patient_responsibility=sample.eob.patient_responsibility,
        )
        if sample.eob
        else None
    )
    result = run_checks(
        lines, ref=ref, patient_type=sample.patient_type, gfe_total=sample.gfe_total,
        bill_date=sample.bill_date, amount_due=sample.amount_due, eob=eob, today=TODAY,
    )
    return sample, result


def key(flag: ExpectedFlag) -> tuple:
    return (flag.check, flag.level, flag.codes, flag.line_numbers)


@pytest.mark.parametrize("name", NAMES)
def test_findings_match_the_expected_flags_exactly(name: str, ref: sqlite3.Connection) -> None:
    sample, result = audit(name, ref)
    found = sorted((ExpectedFlag(**f.model_dump(include=FLAG_FIELDS)) for f in result.findings), key=key)
    assert found == sorted(sample.flags, key=key)


@pytest.mark.parametrize("name", NAMES)
def test_likely_error_total_matches(name: str, ref: sqlite3.Connection) -> None:
    sample, result = audit(name, ref)
    assert result.dollars_at_stake == sample.likely_error_total


def test_mayas_total_is_units_plus_duplicate_plus_dose(ref: sqlite3.Connection) -> None:
    _, result = audit("maya", ref)
    assert str(result.dollars_at_stake) == "3858.00"  # 2,800.00 + 68.00 + 990.00; the GFE overage is separate


def test_mayas_dispute_deadline_and_overage(ref: sqlite3.Connection) -> None:
    sample, result = audit("maya", ref)
    assert result.deadline == sample.deadline == date(2027, 2, 2)
    gfe = next(f for f in result.findings if f.check == "gfe")
    assert gfe.overage == sample.gfe_overage


def test_clean_bill_has_no_likely_errors_or_questions(ref: sqlite3.Connection) -> None:
    _, result = audit("clean", ref)
    assert not {f.level for f in result.findings} & {"red", "amber"}
    assert result.deadline is None  # $339.50 over the estimate is below the $400 threshold
    assert str(result.dollars_at_stake) == "0.00"


def test_insured_dev_gets_no_good_faith_estimate_check(ref: sqlite3.Connection) -> None:
    _, result = audit("dev", ref)
    assert "gfe" not in {f.check for f in result.findings}
    assert ("eob", "red") in {(f.check, f.level) for f in result.findings}


@pytest.mark.parametrize("name", NAMES)
def test_every_finding_carries_complete_evidence(name: str, ref: sqlite3.Connection) -> None:
    _, result = audit(name, ref)
    for finding in result.findings:
        assert finding.wording
        assert finding.evidence.rule and finding.evidence.source_name
        assert finding.evidence.data_row, finding.check
        if finding.line_numbers:
            assert [x.line_number for x in finding.evidence.bill_lines] == finding.line_numbers
        assert finding.evidence.computed, finding.check  # the numbers the finding rests on
        if finding.check in {"dose", "units", "drug_benchmark", "gfe", "code"}:
            assert finding.evidence.source_url and finding.evidence.source_url.startswith("https://www.cms.gov/")


@pytest.mark.parametrize("name", NAMES)
def test_findings_round_trip_through_json(name: str, ref: sqlite3.Connection) -> None:
    from app.findings import Finding

    _, result = audit(name, ref)
    for finding in result.findings:
        assert Finding.model_validate_json(finding.model_dump_json()) == finding


def test_every_wording_is_filled_in(ref: sqlite3.Connection) -> None:
    for name in NAMES:
        _, result = audit(name, ref)
        for finding in result.findings:
            assert "{" not in finding.wording and "[" not in finding.wording, finding.wording


def test_mayas_wording_for_each_finding(ref: sqlite3.Connection) -> None:
    _, result = audit("maya", ref)
    text = {(f.check, tuple(f.line_numbers)): f.wording for f in result.findings}
    assert text[("units", (1,))] == "CMS normally allows at most 1 units of this per day. 2 were billed."
    assert text[("dose", (5,))] == "Your bill says 200 mg, which is 20 billing units for this drug, but 200 units were charged."
    assert text[("drug_benchmark", (6,))] == "Charged 285.7× Medicare's payment limit for this drug. Not an error; useful when asking for a discount."
    assert text[("gfe", ())] == "You may be able to start a federal billing dispute. Deadline: February 2, 2027."


def test_devs_dose_finding_asks_for_a_billing_review(ref: sqlite3.Connection) -> None:
    _, result = audit("dev", ref)
    (dose,) = [f for f in result.findings if f.check == "dose"]
    assert dose.wording.endswith("Ask for a billing review.") and dose.dollars_at_stake == 0
