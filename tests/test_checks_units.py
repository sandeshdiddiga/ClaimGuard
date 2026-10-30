"""Units over the CMS daily limit (MUE). MAI 1 is a per-line limit; MAI 2 and 3 are per day."""

import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app.checks.constants import MUE_URL
from app.checks.units import check_units
from tests.builders import bill_line
from tests.spy import NoQueries

D = Decimal


def test_mai_2_over_the_limit_is_a_likely_error_with_the_spec_wording(ref: sqlite3.Connection) -> None:
    (finding,) = check_units([bill_line("G0121", "5600.00", units=2)], ref, insured=False)
    assert (finding.check, finding.level, finding.codes, finding.line_numbers) == ("units", "red", ["G0121"], [1])
    assert finding.billing_review is False
    assert (finding.mue_value, finding.mai) == (1, 2)
    assert finding.wording == "CMS normally allows at most 1 units of this per day. 2 were billed."
    assert finding.counted == {1: D("2800.00")}  # one excess unit at 2,800.00 a unit
    assert finding.dollars_at_stake == D("2800.00")


def test_evidence_has_the_cms_row_the_arithmetic_and_the_source(ref: sqlite3.Connection) -> None:
    (finding,) = check_units([bill_line("G0121", "5600.00", units=2)], ref, insured=False)
    evidence = finding.evidence
    assert evidence.data_row == {
        "code": "G0121", "mue_value": 1, "mai": 2, "rationale": "Anatomic Consideration",
        "hcpcs_description": "Screening colonoscopy for a patient at average risk",
    }
    assert evidence.computed == {"billed_units": 2, "limit": 1, "excess_units": 1, "counted": "2800.00"}
    assert evidence.source_url == MUE_URL
    assert [x.line_number for x in evidence.bill_lines] == [1]
    assert "per day" in evidence.rule


def test_mai_2_adds_up_every_line_on_the_same_day(ref: sqlite3.Connection) -> None:
    lines = [bill_line("G0121", "2800.00"), bill_line("J2250"), bill_line("G0121", "2800.00")]
    (finding,) = check_units(lines, ref, insured=False)
    assert finding.line_numbers == [1, 3]
    assert finding.counted == {3: D("2800.00")}  # the excess is taken from the last line(s) of the day


def test_different_days_are_not_added_together(ref: sqlite3.Connection) -> None:
    lines = [bill_line("G0121", on=date(2026, 9, 14)), bill_line("G0121", on=date(2026, 9, 15))]
    assert check_units(lines, ref, insured=False) == []


def test_mai_1_is_checked_per_line(ref: sqlite3.Connection) -> None:
    # J0716: limit 4 per line. Two lines of 3 are fine; one line of 6 is not.
    assert check_units([bill_line("J0716", units=3), bill_line("J0716", units=3)], ref, insured=False) == []
    (finding,) = check_units([bill_line("J0716", "600.00", units=6)], ref, insured=False)
    assert (finding.level, finding.mai, finding.line_numbers) == ("red", 1, [1])
    assert finding.counted == {1: D("200.00")}


def test_mai_3_is_worth_asking_about_and_counts_nothing(ref: sqlite3.Connection) -> None:
    (finding,) = check_units([bill_line("A4216", "255.00", units=30)], ref, insured=False)
    assert (finding.level, finding.mue_value, finding.mai) == ("amber", 25, 3)
    assert finding.wording == "CMS normally allows at most 25 units of this per day. 30 were billed."
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")


@pytest.mark.parametrize("units, flagged", [(25, False), (26, True)])
def test_the_limit_itself_is_allowed(ref: sqlite3.Connection, units: int, flagged: bool) -> None:
    assert bool(check_units([bill_line("A4216", units=units)], ref, insured=False)) is flagged


def test_insured_patients_are_asked_to_request_a_billing_review(ref: sqlite3.Connection) -> None:
    (finding,) = check_units([bill_line("G0121", "5600.00", units=2)], ref, insured=True)
    assert finding.level == "amber"  # MUEs are Medicare's: a reason to ask, not proof of an error
    assert finding.wording.endswith("2 were billed. Ask for a billing review.")
    assert finding.billing_review is True
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")


@pytest.mark.parametrize(
    "line",
    [
        bill_line("A4927", units=5),  # an MUE of 0 gives no limit to compare against
        bill_line("Z9999", units=99),  # not in the MUE table
        bill_line("00000", units=99),  # CPT-shaped: never looked up
        bill_line("", units=99),
    ],
)
def test_lines_with_no_usable_limit_are_skipped(ref: sqlite3.Connection, line) -> None:
    assert check_units([line], ref, insured=False) == []


def test_a_cpt_shaped_code_is_never_looked_up() -> None:
    assert check_units([bill_line("00000", units=99), bill_line("0000F", units=99)], NoQueries(), insured=False) == []


def test_a_line_without_a_date_is_its_own_day(ref: sqlite3.Connection) -> None:
    lines = [bill_line("G0121", on=None), bill_line("G0121", on=None)]
    assert check_units(lines, ref, insured=False) == []
