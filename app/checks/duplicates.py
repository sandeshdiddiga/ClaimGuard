"""Duplicate charge: the same code, date, units and modifier billed more than once."""

from collections import defaultdict
from collections.abc import Sequence

from app.checks import wording
from app.checks.constants import DUPLICATE_SOURCE
from app.findings import Evidence, Finding, charges, evidence_lines
from app.schemas import ExtractedLine


def check_duplicates(lines: Sequence[ExtractedLine]) -> list[Finding]:
    groups: dict[tuple, list[int]] = defaultdict(list)
    for number, line in enumerate(lines, start=1):
        if line.service_date is None:
            continue  # cannot say it is the same day
        groups[(line.service_date, line.code, line.units, line.modifier)].append(number)

    findings = []
    for (day, code, units, modifier), numbers in groups.items():
        if len(numbers) < 2:
            continue
        repeats = numbers[1:]  # the first charge is legitimate; the rest are the extra
        extra = charges(lines, repeats)
        findings.append(
            Finding(
                check="duplicate", level="red", wording=wording.DUPLICATE, codes=[code],
                line_numbers=numbers, counted={n: lines[n - 1].charge for n in repeats}, dollars_at_stake=extra,
                evidence=Evidence(
                    bill_lines=evidence_lines(lines, numbers),
                    rule="The same code, date, units and modifier appear on more than one line.",
                    data_row={
                        "service_date": day.isoformat(), "code": code, "units": units,
                        "modifier": modifier, "occurrences": len(numbers),
                    },
                    computed={"repeats": len(repeats), "counted": f"{extra:.2f}"},
                    difference=extra, source_name=DUPLICATE_SOURCE,
                ),
            )
        )
    return findings
