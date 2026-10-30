"""Parse the CMS HCPCS alpha-numeric file (fixed width, see HCPC2026_recordlayout.txt).

Record id 3 starts a code (long description in columns 12-91, short in 92-119, dates in 269-292); record id 4
lines continue the long description. Other record ids (modifier records) are ignored. Only Level II codes are
kept, and CPT-shaped tokens inside descriptions are replaced with "[CPT code]".
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ingest.codes import clean_code, is_level_ii, redact_cpt_codes

__all__ = ["HcpcsRow", "parse_hcpcs_lines", "redact_cpt_codes"]


@dataclass(frozen=True)
class HcpcsRow:
    code: str
    short_description: str
    long_description: str
    added_date: str | None
    effective_date: str | None
    termination_date: str | None  # None while the code is live


def _date(text: str) -> str | None:
    return text.strip() or None


def _row(first_line: str, continuations: list[str]) -> HcpcsRow:
    long_text = " ".join(part for part in [first_line[11:91].strip(), *continuations] if part)
    return HcpcsRow(
        code=clean_code(first_line[0:5]),
        short_description=redact_cpt_codes(first_line[91:119].strip()),
        long_description=redact_cpt_codes(long_text),
        added_date=_date(first_line[268:276]),
        effective_date=_date(first_line[276:284]),
        termination_date=_date(first_line[284:292]),
    )


def parse_hcpcs_lines(lines: Iterable[str]) -> Iterator[HcpcsRow]:
    first_line: str | None = None  # the record-id-3 line of the code being read; None when it is being dropped
    continuations: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        record = line[10:11]
        if record == "4":
            if first_line is not None and clean_code(line[0:5]) == clean_code(first_line[0:5]):
                continuations.append(line[11:91].strip())
            continue
        if first_line is not None:
            yield _row(first_line, continuations)
        first_line, continuations = None, []
        if record == "3" and is_level_ii(clean_code(line[0:5])):
            first_line = line
    if first_line is not None:
        yield _row(first_line, continuations)
