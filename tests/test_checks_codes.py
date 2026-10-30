"""Code check: what ClaimGuard can say about each code. Context only."""

import sqlite3

from app.checks.codes import check_codes
from app.checks.constants import HCPCS_URL
from tests.builders import bill_line
from tests.spy import NoQueries


def test_a_valid_code_with_no_public_rate_shows_its_description(ref: sqlite3.Connection) -> None:
    (finding,) = check_codes([bill_line("G0121")], ref)
    assert (finding.check, finding.level, finding.code_status, finding.codes) == ("code", "grey", "valid_no_rate", ["G0121"])
    assert finding.wording == (
        "G0121: Screening colonoscopy for a patient at average risk. "
        "ClaimGuard has no public Medicare rate for this code."
    )
    assert finding.dollars_at_stake == 0 and finding.counted == {}
    assert finding.evidence.source_url == HCPCS_URL
    assert finding.evidence.data_row == {
        "code": "G0121", "short_description": "colonoscopy screening",
        "long_description": "Screening colonoscopy for a patient at average risk", "termination_date": None,
    }


def test_drug_codes_get_a_benchmark_instead(ref: sqlite3.Connection) -> None:
    assert check_codes([bill_line("J2250")], ref) == []


def test_an_unknown_letter_code(ref: sqlite3.Connection) -> None:
    (finding,) = check_codes([bill_line("Z9999")], ref)
    assert (finding.code_status, finding.wording) == ("unknown", "Not in CMS's current HCPCS list.")


def test_a_terminated_code_is_not_in_the_current_list(ref: sqlite3.Connection) -> None:
    (finding,) = check_codes([bill_line("J1170")], ref)
    assert (finding.code_status, finding.wording) == ("unknown", "Not in CMS's current HCPCS list.")
    assert finding.evidence.data_row["termination_date"] == "20240930"


def test_a_cpt_shaped_code_is_shown_as_not_checked_without_any_lookup() -> None:
    (finding,) = check_codes([bill_line("00000"), bill_line("0000F")][:1], NoQueries())
    assert (finding.code_status, finding.wording) == ("not_checked", "Not checked (CPT needs an AMA license).")
    assert finding.evidence.data_row == {"code": "00000"}
    assert finding.evidence.computed == {"code_class": "cpt_shaped"}


def test_one_finding_per_code_and_none_for_a_missing_code(ref: sqlite3.Connection) -> None:
    lines = [bill_line("G0121"), bill_line(""), bill_line("A4216"), bill_line("G0121")]
    assert [(f.codes, f.line_numbers) for f in check_codes(lines, ref)] == [(["G0121"], [1, 4]), (["A4216"], [3])]
