"""Dose vs billing units: the dose written on the line divided by the dose per billing unit (drug_limits)."""

import sqlite3
from decimal import Decimal

import pytest

from app.checks.constants import ASP_URL
from app.checks.dose import check_dose
from tests.builders import bill_line
from tests.spy import NoQueries

D = Decimal


def propofol(units: int = 200, charge: str = "1100.00"):
    return bill_line("J2704", charge, units=units, description="Rev 0636 Propofol inj 200 mg", dose=("200", "MG"))


def test_a_clear_mismatch_is_a_likely_error_with_the_spec_wording(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([propofol()], ref, insured=False)
    assert (finding.check, finding.level, finding.codes, finding.line_numbers) == ("dose", "red", ["J2704"], [1])
    assert finding.expected_units == 20
    assert finding.wording == "Your bill says 200 mg, which is 20 billing units for this drug, but 200 units were charged."


def test_only_the_excess_units_count(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([propofol()], ref, insured=False)
    assert finding.counted == {1: D("990.00")}  # 1,100.00 / 200 units x 180 excess units
    assert finding.dollars_at_stake == D("990.00")


def test_evidence_has_the_line_the_cms_row_the_arithmetic_and_the_source(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([propofol()], ref, insured=False)
    evidence = finding.evidence
    assert [x.line_number for x in evidence.bill_lines] == [1]
    assert evidence.data_row == {
        "code": "J2704", "dosage": "10 MG", "payment_limit": "0.093",
        "hcpcs_description": "Injection of an anesthetic, per 10 mg",
    }
    assert evidence.computed == {
        "stated_dose": "200 mg", "dose_per_unit": "10 mg", "expected_units": 20, "billed_units": 200,
        "excess_units": 180, "unit_charge": "5.50", "counted": "990.00",
    }
    assert evidence.difference == D("990.00")
    assert evidence.source_url == ASP_URL


@pytest.mark.parametrize(
    "code, dose, units",
    [
        ("J2250", ("2", "MG"), 2),  # 2 mg at 1 mg per unit
        ("J3010", ("100", "MCG"), 1),  # 100 mcg is 0.1 mg, one unit
        ("J7120", ("1000", "ML"), 1),  # 1000 mL against "1000 CC"
        ("J2704", ("200", "MG"), 20),
    ],
)
def test_a_matching_dose_is_not_flagged(ref: sqlite3.Connection, code: str, dose: tuple[str, str], units: int) -> None:
    assert check_dose([bill_line(code, units=units, dose=dose)], ref, insured=False) == []


def test_micrograms_convert_to_milligrams(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([bill_line("J3010", "540.00", units=10, dose=("100", "MCG"))], ref, insured=False)
    assert (finding.level, finding.expected_units, finding.dollars_at_stake) == ("red", 1, D("486.00"))


def test_billing_fewer_units_than_the_dose_is_a_mismatch_that_costs_the_patient_nothing(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([bill_line("J2250", "34.00", units=1, dose=("2", "MG"))], ref, insured=False)
    assert (finding.level, finding.expected_units) == ("red", 2)
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")


@pytest.mark.parametrize(
    "code, dose",
    [
        ("J2250", ("2", "ML")),  # billed per mg; a volume needs the concentration to convert
        ("J2704", ("25", "MG")),  # 2.5 billing units: not a whole number of units
    ],
)
def test_a_dose_that_needs_interpreting_is_worth_asking_about(ref: sqlite3.Connection, code: str, dose: tuple[str, str]) -> None:
    (finding,) = check_dose([bill_line(code, "50.00", units=3, dose=dose)], ref, insured=False)
    assert (finding.check, finding.level, finding.expected_units) == ("dose", "amber", None)
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")
    assert "can't be worked out from the bill alone" in finding.wording


@pytest.mark.parametrize(
    "line",
    [
        bill_line("J2250", units=2),  # no dose written on the line
        bill_line("J9029", dose=("1", "MG")),  # CMS's dosage ("per therapeutic dose") has no number to divide by
        bill_line("G0121", dose=("2", "MG")),  # not a drug in the payment limit file
        bill_line("00000", dose=("2", "MG")),  # CPT-shaped: never looked up
    ],
)
def test_lines_without_a_comparable_dose_are_skipped(ref: sqlite3.Connection, line) -> None:
    assert check_dose([line], ref, insured=False) == []


def test_a_cpt_shaped_code_is_never_looked_up() -> None:
    assert check_dose([bill_line("00000", dose=("2", "MG"))], NoQueries(), insured=False) == []


def test_insured_patients_are_asked_to_request_a_billing_review_and_nothing_is_counted(ref: sqlite3.Connection) -> None:
    (finding,) = check_dose([bill_line("J2405", "192.00", units=8, dose=("4", "MG"))], ref, insured=True)
    assert (finding.level, finding.expected_units) == ("red", 4)
    assert finding.wording == (
        "Your bill says 4 mg, which is 4 billing units for this drug, but 8 units were charged. Ask for a billing review."
    )
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")  # the EOB sets what an insured patient owes
    assert finding.billing_review is True


def test_each_line_is_checked_on_its_own(ref: sqlite3.Connection) -> None:
    lines = [propofol(), bill_line("J2250", units=2, dose=("2", "MG")), propofol(units=20, charge="110.00")]
    assert [f.line_numbers for f in check_dose(lines, ref, insured=False)] == [[1]]
