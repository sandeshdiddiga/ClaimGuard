"""Code check: what ClaimGuard can say about each code on the bill. Context only.

A live Level II code with no drug payment limit shows its CMS description and says there is no public
Medicare rate for it (drug codes get a benchmark instead). A letter code not in the current HCPCS list says
so. A CPT-shaped code is shown as not checked, without any lookup. A line with no usable code gets nothing.
"""

import sqlite3
from collections.abc import Sequence

from app.checks import wording
from app.checks.constants import CPT_POLICY_SOURCE, HCPCS_SOURCE, HCPCS_URL
from app.codes import classify_code
from app.findings import Evidence, Finding, evidence_lines
from app.refdb import drug_limit, hcpcs_entry
from app.schemas import ExtractedLine

CPT_RULE = (
    "CPT codes and their descriptions are licensed by the American Medical Association. This demo holds none "
    "of them, so the code is shown as printed and not checked."
)
HCPCS_RULE = "Each code is looked up in CMS's current HCPCS Level II list."


def check_codes(lines: Sequence[ExtractedLine], ref: sqlite3.Connection) -> list[Finding]:
    by_code: dict[str, list[int]] = {}
    for number, line in enumerate(lines, start=1):
        by_code.setdefault(line.code, []).append(number)

    findings = []
    for code, numbers in by_code.items():
        code_class = classify_code(ref, code)
        if code_class == "missing":
            continue
        if code_class == "cpt_shaped":
            findings.append(_finding(lines, code, numbers, "not_checked", wording.CODE_NOT_CHECKED, CPT_RULE,
                                     {"code": code}, {"code_class": "cpt_shaped"}, CPT_POLICY_SOURCE, None))
            continue
        entry = hcpcs_entry(ref, code)
        data_row = {
            "code": code, "short_description": entry.short_description if entry else None,
            "long_description": entry.long_description if entry else None,
            "termination_date": entry.termination_date if entry else None,
        }
        if entry is None or entry.termination_date is not None:
            findings.append(_finding(lines, code, numbers, "unknown", wording.CODE_UNKNOWN, HCPCS_RULE, data_row,
                                     {"code_class": code_class, "in_current_list": False}, HCPCS_SOURCE, HCPCS_URL))
            continue
        if drug_limit(ref, code) is not None:
            continue  # a drug: the benchmark speaks for it
        text = wording.CODE_VALID.format(code=code, description=entry.long_description.rstrip("."))
        findings.append(_finding(lines, code, numbers, "valid_no_rate", text, HCPCS_RULE, data_row,
                                 {"code_class": code_class, "in_current_list": True, "has_payment_limit": False},
                                 HCPCS_SOURCE, HCPCS_URL))
    return findings


def _finding(lines, code, numbers, status, text, rule, data_row, computed, source, url) -> Finding:
    return Finding(
        check="code", level="grey", wording=text, codes=[code], line_numbers=numbers, code_status=status,
        evidence=Evidence(bill_lines=evidence_lines(lines, numbers), rule=rule, data_row=data_row,
                          computed=computed, source_name=source, source_url=url),
    )
