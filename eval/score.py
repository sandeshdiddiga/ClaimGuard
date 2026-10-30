"""Scoring for the eval: compare what the pipeline produced with samples/<name>/expected_flags.json.

Pure functions, no I/O. The expected files are derived from the CMS data independently of the check code
(tests/test_samples.py), so they are the oracle for both extraction and findings.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.findings import Finding
from app.schemas import EobReading, ExpectedFlag, ExpectedLine, ExpectedSample, ExtractedLine

LINE_FIELDS = ("service_date", "code", "modifier", "description", "units", "charge", "dose_value", "dose_unit")
HEADER_FIELDS = ("facility_name", "bill_date", "amount_due")
EOB_FIELDS = ("billed", "allowed", "patient_responsibility")
MONEY_FIELDS = {"charge", "amount_due", "dose_value", "billed", "allowed", "patient_responsibility"}
SEEDED_LEVELS = {"red", "amber"}  # a seeded error is a Likely error or a Worth asking about
LEVEL_WORD = {"red": "Likely error", "amber": "Worth asking about", "grey": "For context"}


class Tally(BaseModel):
    ok: int = 0
    total: int = 0

    def add(self, correct: bool) -> None:
        self.total += 1
        self.ok += int(correct)

    @property
    def share(self) -> float | None:
        return self.ok / self.total if self.total else None


class FindingScore(BaseModel):
    expected_errors: int = 0  # red and amber flags the sample seeds
    caught: int = 0  # present at the expected level
    downgraded: int = 0  # amber flags Ultra moved to context: reviewed, counted as neither caught nor missed
    missed: list[str] = []
    false_likely: list[str] = []  # Likely-error findings no expected flag accounts for
    unexpected: list[str] = []  # any other finding no expected flag accounts for
    context_expected: int = 0
    context_found: int = 0
    expected_total: Decimal = Decimal("0.00")
    actual_total: Decimal = Decimal("0.00")
    total_ok: bool = True
    deadline_ok: bool = True


# --- extraction ------------------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _same(field: str, expected: Any, actual: Any) -> bool:
    if field in MONEY_FIELDS:
        if expected is None or actual is None:
            return expected is None and actual is None
        return Decimal(str(expected)) == Decimal(str(actual))
    if field in {"service_date", "bill_date", "units"}:
        return expected == actual
    return _text(expected) == _text(actual)


def _align(expected: list[ExpectedLine], read: list[ExtractedLine]) -> list[ExtractedLine | None]:
    """For each expected line, the line that was read for it: same code and charge, then same code, then the
    same position. Each line read is used once, so an extra or missing line does not shift the others."""
    used: set[int] = set()
    matched: list[ExtractedLine | None] = []
    for position, want in enumerate(expected):
        pick = next(
            (i for i, got in enumerate(read) if i not in used and got.code == want.code and got.charge == want.charge),
            None,
        )
        if pick is None:
            pick = next((i for i, got in enumerate(read) if i not in used and got.code == want.code), None)
        if pick is None and position < len(read) and position not in used:
            pick = position
        if pick is not None:
            used.add(pick)
        matched.append(None if pick is None else read[pick])
    return matched


def score_extraction(
    sample: ExpectedSample, lines: list[ExtractedLine], header: dict[str, Any], eob: EobReading | None
) -> tuple[dict[str, Tally], int, int]:
    """Per-field tallies (a missing line or EOB counts every field wrong), then lines expected and lines read."""
    tallies: dict[str, Tally] = {name: Tally() for name in (*LINE_FIELDS, *HEADER_FIELDS)}
    for want, got in zip(sample.lines, _align(sample.lines, lines)):
        for name in LINE_FIELDS:
            tallies[name].add(got is not None and _same(name, getattr(want, name), getattr(got, name)))
    for name in HEADER_FIELDS:
        tallies[name].add(_same(name, getattr(sample, name), header.get(name)))
    if sample.eob is not None:
        for name in EOB_FIELDS:
            tallies[f"eob_{name}"] = Tally()
            tallies[f"eob_{name}"].add(eob is not None and _same(name, getattr(sample.eob, name), getattr(eob, name)))
    return tallies, len(sample.lines), len(lines)


# --- findings --------------------------------------------------------------------------------------------


def _where(numbers: list[int]) -> str:
    if not numbers:
        return ""
    if len(numbers) == 1:
        return f", line {numbers[0]}"
    return ", lines " + ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"


def label(check: str, numbers: list[int]) -> str:
    return f"{check}{_where(numbers)}"


def _key(item: ExpectedFlag | Finding) -> tuple:
    return (item.check, tuple(item.line_numbers), tuple(item.codes))


def score_findings(
    sample: ExpectedSample, findings: list[Finding], actual_total: Decimal, actual_deadline: date | None
) -> FindingScore:
    """Match each finding to an expected flag by check, lines and codes. The likely-error total and the deadline
    are scored separately, not per flag."""
    score = FindingScore(
        expected_total=sample.likely_error_total, actual_total=actual_total,
        total_ok=actual_total == sample.likely_error_total, deadline_ok=actual_deadline == sample.deadline,
    )
    unmatched: dict[tuple, list[Finding]] = {}
    for found in findings:
        unmatched.setdefault(_key(found), []).append(found)

    for flag in sample.flags:
        seeded = flag.level in SEEDED_LEVELS
        score.expected_errors += int(seeded)
        score.context_expected += int(not seeded)
        candidates = unmatched.get(_key(flag), [])
        at_level = next((f for f in candidates if f.level == flag.level), None)
        downgraded = next((f for f in candidates if f.judge_decision == "downgrade" and flag.level == "amber"), None)
        if at_level is not None:
            candidates.remove(at_level)
            score.caught += int(seeded)
            score.context_found += int(not seeded)
        elif downgraded is not None:
            candidates.remove(downgraded)
            score.downgraded += 1
        elif seeded:
            score.missed.append(label(flag.check, flag.line_numbers))

    for leftover in (f for group in unmatched.values() for f in group):
        text = label(leftover.check, leftover.line_numbers)
        if leftover.level == "red":
            score.false_likely.append(text)
        else:
            score.unexpected.append(f"{text} ({LEVEL_WORD[leftover.level]})")
    return score
