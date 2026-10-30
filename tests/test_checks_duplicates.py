from datetime import date
from decimal import Decimal

from app.checks.duplicates import check_duplicates
from tests.builders import bill_line

WORDING = "This charge appears twice on the same date. Ask the billing office to confirm or remove it."


def test_same_code_date_and_units_twice_is_a_red_flag() -> None:
    lines = [bill_line("J2250", "68.00"), bill_line("J3010", "54.00"), bill_line("J2250", "68.00")]
    (finding,) = check_duplicates(lines)
    assert (finding.check, finding.level, finding.codes) == ("duplicate", "red", ["J2250"])
    assert finding.line_numbers == [1, 3]
    assert finding.wording == WORDING


def test_only_the_repeat_counts_toward_dollars_at_stake() -> None:
    (finding,) = check_duplicates([bill_line(charge="1980.00"), bill_line(charge="1980.00")])
    assert finding.counted == {2: Decimal("1980.00")}  # the full line charge of the repeat
    assert finding.dollars_at_stake == Decimal("1980.00")


def test_three_copies_count_the_second_and_third() -> None:
    (finding,) = check_duplicates([bill_line(charge="50.00")] * 3)
    assert finding.line_numbers == [1, 2, 3]
    assert finding.counted == {2: Decimal("50.00"), 3: Decimal("50.00")}
    assert finding.dollars_at_stake == Decimal("100.00")


def test_evidence_lists_the_lines_the_rule_and_the_difference() -> None:
    (finding,) = check_duplicates([bill_line(charge="1980.00"), bill_line(charge="1980.00")])
    evidence = finding.evidence
    assert [(x.line_number, x.code, x.charge) for x in evidence.bill_lines] == [
        (1, "G0121", Decimal("1980.00")),
        (2, "G0121", Decimal("1980.00")),
    ]
    assert evidence.difference == Decimal("1980.00")
    assert "same code, date, units and modifier" in evidence.rule
    assert evidence.data_row == {"service_date": "2026-09-14", "code": "G0121", "units": 1, "modifier": None, "occurrences": 2}
    assert evidence.computed == {"repeats": 1, "counted": "1980.00"}
    assert evidence.source_url is None  # billing accuracy; no CMS rule behind it


def test_different_units_are_not_duplicates() -> None:
    assert check_duplicates([bill_line(units=1), bill_line(units=2)]) == []


def test_different_dates_are_not_duplicates() -> None:
    assert check_duplicates([bill_line(on=date(2026, 9, 14)), bill_line(on=date(2026, 9, 15))]) == []


def test_different_modifiers_are_not_duplicates() -> None:
    """Left and right (LT/RT) are separate procedures."""
    assert check_duplicates([bill_line(modifier="LT"), bill_line(modifier="RT")]) == []


def test_lines_without_a_service_date_are_never_flagged() -> None:
    assert check_duplicates([bill_line(on=None), bill_line(on=None)]) == []


def test_each_repeated_group_gets_its_own_finding() -> None:
    lines = [bill_line("J2250"), bill_line("J3010"), bill_line("J2250"), bill_line("J3010")]
    findings = check_duplicates(lines)
    assert [f.codes for f in findings] == [["J2250"], ["J3010"]]


def test_no_lines_no_findings() -> None:
    assert check_duplicates([]) == []
