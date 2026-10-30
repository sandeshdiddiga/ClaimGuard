"""Medicare drug benchmark: charge per billing unit as a multiple of the Part B payment limit. Context only."""

import sqlite3
from decimal import Decimal

import pytest

from app.checks.constants import ASP_URL
from app.checks.drug_benchmark import check_drug_benchmark
from tests.builders import bill_line
from tests.spy import NoQueries

D = Decimal


def test_multiple_of_the_payment_limit_with_the_spec_wording(ref: sqlite3.Connection) -> None:
    (finding,) = check_drug_benchmark([bill_line("J2250", "68.00", units=2)], ref, skip=set())
    assert (finding.check, finding.level, finding.codes, finding.line_numbers) == ("drug_benchmark", "grey", ["J2250"], [1])
    assert finding.multiple == D("203.6")  # 34.00 a unit / 0.167
    assert finding.wording == "Charged 203.6× Medicare's payment limit for this drug. Not an error; useful when asking for a discount."


def test_benchmarks_never_count(ref: sqlite3.Connection) -> None:
    (finding,) = check_drug_benchmark([bill_line("J2250", "68.00", units=2)], ref, skip=set())
    assert finding.counted == {} and finding.dollars_at_stake == D("0.00")


def test_evidence(ref: sqlite3.Connection) -> None:
    (finding,) = check_drug_benchmark([bill_line("J2250", "68.00", units=2)], ref, skip=set())
    evidence = finding.evidence
    assert evidence.data_row == {"code": "J2250", "dosage": "1 MG", "payment_limit": "0.167"}
    assert evidence.computed == {"charge_per_unit": "34.00", "multiple": "203.6"}
    assert evidence.source_url == ASP_URL
    assert "not an error" in evidence.rule.lower()


def test_one_finding_per_code_covering_every_line(ref: sqlite3.Connection) -> None:
    lines = [bill_line("J2250", "68.00", units=2), bill_line("J3010", "54.00"), bill_line("J2250", "68.00", units=2)]
    findings = check_drug_benchmark(lines, ref, skip=set())
    assert [(f.codes, f.line_numbers) for f in findings] == [(["J2250"], [1, 3]), (["J3010"], [2])]


def test_a_line_with_a_dose_finding_is_skipped(ref: sqlite3.Connection) -> None:
    lines = [bill_line("J2704", "1100.00", units=200), bill_line("J2250", "68.00", units=2)]
    assert [f.codes for f in check_drug_benchmark(lines, ref, skip={1})] == [["J2250"]]


@pytest.mark.parametrize(
    "code",
    ["G0121", "J9029", "Z9999", "00000"],  # not a drug; no parsed dosage; unknown; CPT-shaped
)
def test_codes_without_a_usable_payment_limit_are_skipped(ref: sqlite3.Connection, code: str) -> None:
    assert check_drug_benchmark([bill_line(code, "100.00")], ref, skip=set()) == []


def test_a_cpt_shaped_code_is_never_looked_up() -> None:
    assert check_drug_benchmark([bill_line("00000", "100.00")], NoQueries(), skip=set()) == []
