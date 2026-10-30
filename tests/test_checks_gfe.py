from datetime import date
from decimal import Decimal

import pytest

from app.checks.constants import GFE_DISPUTE_THRESHOLD, GFE_DISPUTE_URL, GFE_DISPUTE_WINDOW_DAYS
from app.checks.gfe import check_gfe
from tests.builders import bill_line

BILL_DATE = date(2026, 10, 5)
TODAY = date(2026, 10, 28)


def run(total: str, gfe: str = "1000.00", **overrides):
    args = dict(patient_type="self_pay", gfe_total=Decimal(gfe), bill_date=BILL_DATE, today=TODAY) | overrides
    return check_gfe([bill_line(charge=total)], **args)


def test_constants_match_the_federal_rule() -> None:
    assert GFE_DISPUTE_THRESHOLD == Decimal("400.00")
    assert GFE_DISPUTE_WINDOW_DAYS == 120
    assert GFE_DISPUTE_URL.endswith("understanding-good-faith-estimate-and-dispute-resolution-process.pdf")


@pytest.mark.parametrize(
    "total, flagged",
    [("1399.99", False), ("1400.00", True), ("1400.01", True), ("900.00", False), ("1000.00", False)],
)
def test_threshold_is_400_or_more_over(total: str, flagged: bool) -> None:
    assert bool(run(total)) is flagged


def test_flag_has_overage_deadline_and_the_spec_wording() -> None:
    (finding,) = run("4135.00", gfe="0.00")
    assert (finding.check, finding.level) == ("gfe", "red")
    assert finding.overage == Decimal("4135.00")
    assert finding.deadline == date(2027, 2, 2)
    assert finding.wording == (
        "You may be able to start a federal billing dispute. Deadline: February 2, 2027."
    )


def test_overage_is_shown_but_never_added_to_dollars_at_stake() -> None:
    (finding,) = run("5000.00")
    assert finding.dollars_at_stake == Decimal("0.00") and finding.counted == {}


def test_facility_total_is_the_sum_of_all_lines() -> None:
    lines = [bill_line(charge="700.00"), bill_line("J2250", "600.00")]
    (finding,) = check_gfe(lines, patient_type="self_pay", gfe_total=Decimal("900.00"), bill_date=BILL_DATE, today=TODAY)
    assert finding.overage == Decimal("400.00")


def test_evidence_shows_the_arithmetic_and_source() -> None:
    (finding,) = run("1500.00")
    evidence = finding.evidence
    assert evidence.data_row == {
        "facility_total": "1500.00", "good_faith_estimate": "1000.00", "threshold": "400.00",
        "bill_date": "2026-10-05", "window_days": 120, "deadline": "2027-02-02",
    }
    assert evidence.difference == Decimal("500.00")
    assert evidence.computed == {"overage": "500.00"}
    assert evidence.source_url == GFE_DISPUTE_URL
    assert len(evidence.bill_lines) == 1


@pytest.mark.parametrize(
    "bill_date, deadline",
    [
        (date(2026, 10, 5), date(2027, 2, 2)),
        (date(2027, 11, 1), date(2028, 2, 29)),  # crosses a leap day
        (date(2026, 12, 31), date(2027, 4, 30)),
    ],
)
def test_deadline_is_120_days_after_the_bill_date(bill_date: date, deadline: date) -> None:
    (finding,) = run("5000.00", bill_date=bill_date, today=bill_date)
    assert finding.deadline == deadline


def test_insured_patients_are_not_eligible() -> None:
    assert run("5000.00", patient_type="insured") == []


def test_no_estimate_means_nothing_to_compare() -> None:
    assert run("5000.00", gfe_total=None) == []


def test_missing_bill_date_still_flags_without_inventing_a_deadline() -> None:
    (finding,) = run("5000.00", bill_date=None)
    assert finding.deadline is None
    assert finding.wording == (
        "You may be able to start a federal billing dispute. Deadline: 120 days from the date on your bill."
    )


def test_deadline_day_itself_is_still_open() -> None:
    (finding,) = run("5000.00", today=date(2027, 2, 2))
    assert finding.wording.startswith("You may be able")


def test_a_passed_deadline_is_said_plainly() -> None:
    (finding,) = run("5000.00", today=date(2027, 2, 3))
    assert finding.level == "red"
    assert finding.wording == "The 120-day window to start a federal billing dispute ended on February 2, 2027."


def test_no_lines_no_finding() -> None:
    assert check_gfe([], patient_type="self_pay", gfe_total=Decimal("0"), bill_date=BILL_DATE, today=TODAY) == []
