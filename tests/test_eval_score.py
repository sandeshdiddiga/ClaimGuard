"""Eval scoring: pure functions that compare what the pipeline produced with samples/<name>/expected_flags.json."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.findings import Evidence, Finding
from app.schemas import EobReading, ExpectedSample, ExtractedLine
from eval.score import score_extraction, score_findings

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def sample(name: str = "maya") -> ExpectedSample:
    return ExpectedSample.model_validate_json((SAMPLES / name / "expected_flags.json").read_text())


def lines_of(s: ExpectedSample) -> list[ExtractedLine]:
    return [ExtractedLine(**line.model_dump()) for line in s.lines]


def header(s: ExpectedSample, **over) -> dict:
    return {"facility_name": s.facility_name, "bill_date": s.bill_date, "amount_due": s.amount_due, **over}


def finding(check, level, line_numbers=(), codes=(), **kw) -> Finding:
    return Finding(
        check=check, level=level, wording="w", codes=list(codes), line_numbers=list(line_numbers),
        evidence=Evidence(rule="r", data_row={}, source_name="s"), **kw,
    )


def expected_findings(s: ExpectedSample) -> list[Finding]:
    return [
        finding(f.check, f.level, f.line_numbers, f.codes, dollars_at_stake=f.dollars_at_stake) for f in s.flags
    ]


# --- extraction ------------------------------------------------------------------------------------------


def test_a_perfect_reading_scores_every_field() -> None:
    s = sample()
    tallies, expected_n, read_n = score_extraction(s, lines_of(s), header(s), None)
    assert expected_n == read_n == len(s.lines)
    assert all(t.ok == t.total for t in tallies.values())
    assert tallies["charge"].total == len(s.lines) and tallies["facility_name"].total == 1


def test_a_wrong_charge_costs_only_that_field() -> None:
    s = sample()
    lines = lines_of(s)
    lines[3] = lines[3].model_copy(update={"charge": Decimal("55.00")})
    tallies, _, _ = score_extraction(s, lines, header(s), None)
    assert tallies["charge"].ok == tallies["charge"].total - 1
    assert tallies["code"].ok == tallies["code"].total


def test_money_compares_by_value_and_text_ignores_case_and_spacing() -> None:
    s = sample()
    lines = lines_of(s)
    lines[0] = lines[0].model_copy(update={"charge": Decimal("5600.0"), "description": "  rev 0750  screening   COLONOSCOPY, average risk"})
    tallies, _, _ = score_extraction(s, lines, header(s), None)
    assert tallies["charge"].ok == tallies["charge"].total and tallies["description"].ok == tallies["description"].total


def test_a_missing_line_counts_all_its_fields_as_wrong() -> None:
    s = sample()
    lines = lines_of(s)[:-1]
    tallies, expected_n, read_n = score_extraction(s, lines, header(s), None)
    assert (expected_n, read_n) == (len(s.lines), len(s.lines) - 1)
    assert tallies["code"].ok == tallies["code"].total - 1 and tallies["code"].total == len(s.lines)


def test_lines_are_matched_by_code_and_charge_not_only_position() -> None:
    s = sample()
    lines = lines_of(s)
    lines.insert(0, ExtractedLine(service_date=date(2026, 9, 14), code="A9999", description="x", units=1, charge=Decimal("1.00")))
    tallies, _, read_n = score_extraction(s, lines, header(s), None)
    assert read_n == len(s.lines) + 1
    assert tallies["code"].ok == tallies["code"].total  # the extra line is not charged against the others


def test_header_and_eob_fields_are_scored() -> None:
    s = sample("dev")
    eob = EobReading(billed=s.eob.billed, allowed=s.eob.allowed, patient_responsibility=Decimal("999.00"))
    tallies, _, _ = score_extraction(s, lines_of(s), header(s, facility_name="Other Hospital"), eob)
    assert tallies["facility_name"].ok == 0 and tallies["amount_due"].ok == 1
    assert tallies["eob_billed"].ok == 1 and tallies["eob_patient_responsibility"].ok == 0


def test_no_eob_fields_when_the_sample_has_none() -> None:
    s = sample()
    tallies, _, _ = score_extraction(s, lines_of(s), header(s), None)
    assert "eob_billed" not in tallies


def test_dose_fields_are_scored_on_every_line_so_an_invented_dose_counts() -> None:
    s = sample()
    tallies, _, _ = score_extraction(s, lines_of(s), header(s), None)
    with_dose = sum(1 for line in s.lines if line.dose_value is not None)
    assert tallies["dose_value"].total == len(s.lines) and with_dose < len(s.lines)  # a missing dose must be null too


# --- findings --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["maya", "dev", "clean"])
def test_the_expected_findings_score_perfectly(name: str) -> None:
    s = sample(name)
    score = score_findings(s, expected_findings(s), s.likely_error_total, s.deadline)
    assert score.caught == score.expected_errors and score.missed == [] and score.false_likely == []
    assert score.total_ok and score.deadline_ok


def test_mayas_seeded_errors_are_the_red_and_amber_flags() -> None:
    s = sample()
    score = score_findings(s, expected_findings(s), s.likely_error_total, s.deadline)
    assert score.expected_errors == sum(1 for f in s.flags if f.level in {"red", "amber"})


def test_a_missed_error_is_listed_and_not_caught() -> None:
    s = sample()
    found = [f for f in expected_findings(s) if f.check != "duplicate"]
    score = score_findings(s, found, s.likely_error_total, s.deadline)
    assert score.caught == score.expected_errors - 1
    assert score.missed == ["duplicate, lines 2 and 3"]


def test_a_likely_error_nobody_expected_is_a_false_flag() -> None:
    s = sample("clean")
    found = expected_findings(s) + [finding("duplicate", "red", [1, 2], ["J2250"])]
    score = score_findings(s, found, Decimal("0.00"), None)
    assert score.false_likely == ["duplicate, lines 1 and 2"]


def test_a_grey_or_amber_extra_is_not_a_false_likely_error() -> None:
    s = sample("clean")
    found = expected_findings(s) + [finding("units", "amber", [2], ["J2250"], mai=3)]
    score = score_findings(s, found, Decimal("0.00"), None)
    assert score.false_likely == [] and score.unexpected == ["units, line 2 (Worth asking about)"]


def test_an_error_found_at_a_weaker_level_is_not_caught() -> None:
    s = sample()
    found = [finding(f.check, "amber" if f.check == "duplicate" else f.level, f.line_numbers, f.codes) for f in s.flags]
    score = score_findings(s, found, s.likely_error_total, s.deadline)
    assert "duplicate, lines 2 and 3" in score.missed


def test_ultra_downgrading_an_amber_flag_is_counted_apart_from_misses() -> None:
    s = sample()
    found = [
        finding(f.check, "grey" if f.level == "amber" else f.level, f.line_numbers, f.codes,
                judge_decision="downgrade" if f.level == "amber" else None)
        for f in s.flags
    ]
    score = score_findings(s, found, s.likely_error_total, s.deadline)
    assert score.downgraded == 1 and score.missed == [] and score.caught == score.expected_errors - 1


def test_a_wrong_total_or_deadline_is_reported() -> None:
    s = sample()
    score = score_findings(s, expected_findings(s), Decimal("1.00"), date(2027, 1, 1))
    assert not score.total_ok and not score.deadline_ok
    assert score.actual_total == Decimal("1.00") and score.expected_total == s.likely_error_total


def test_context_notes_are_counted_separately_from_errors() -> None:
    s = sample()
    found = [f for f in expected_findings(s) if f.level != "grey"]
    score = score_findings(s, found, s.likely_error_total, s.deadline)
    assert score.context_found == 0 and score.context_expected == sum(1 for f in s.flags if f.level == "grey")
    assert score.caught == score.expected_errors
