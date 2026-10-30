"""Parsers for the three CMS public-use files, on tiny snippets in the real layouts.

Every parser keeps only codes whose first character is a letter (HCPCS Level II) and drops the rest.
"""

from decimal import Decimal

import pytest

from ingest.parse_drug_limits import DrugLimitRow, parse_dosage, parse_drug_limits_text
from ingest.parse_hcpcs import HcpcsRow, parse_hcpcs_lines, redact_cpt_codes
from ingest.parse_mue import MueRow, parse_mue_text

# --- dosage per billing unit -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value, unit",
    [
        ("1 MG", Decimal("1"), "MG"),
        ("0.1 MG", Decimal("0.1"), "MG"),
        ("10 MG", Decimal("10"), "MG"),
        ("1000 CC", Decimal("1000"), "CC"),
        ("1 mg", Decimal("1"), "MG"),  # CMS mixes cases
        ("  5 ML ", Decimal("5"), "ML"),
        ("150 IU", Decimal("150"), "IU"),
        (".625 GM", Decimal("0.625"), "GM"),
        ("100,000 UNITS", Decimal("100000"), "UNITS"),
    ],
)
def test_dosage_that_states_one_amount_and_one_unit_is_parsed(text: str, value: Decimal, unit: str) -> None:
    assert parse_dosage(text) == (value, unit)


@pytest.mark.parametrize(
    "text",
    [
        "Per Therapeutic Dose",
        "per dose",
        "10 MG/3MG",
        "3 MG & 3 MG",
        "UP TO 120MG",
        "Less than or equal to 7 days of therapy",
        "75mg (50mg cft/25mg taz)",
        "",
        "   ",
    ],
)
def test_dosage_that_cannot_be_read_as_one_amount_is_null(text: str) -> None:
    assert parse_dosage(text) == (None, None)


def test_dose_value_is_exact_decimal_never_float() -> None:
    value, _ = parse_dosage("0.1 MG")
    assert isinstance(value, Decimal) and str(value) == "0.1"


# --- Part B payment limit file (csv with a preamble) -----------------------------------------------------

DRUG_CSV = (
    "Payment Allowance Limits for Medicare Part B Drugs,,,,,,,,,,,,\n"
    ",,,,,,,,,,,,\n"
    "Note 1: Payment allowance limits are based on 2Q26 ASP data.,,,,,,,,,,,,\n"
    "HCPCS Code,Short Description,HCPCS Code Dosage,Payment Limit,Co-insurance Percentage,Vaccine AWP%,"
    "Vaccine Limit,Blood AWP%,Blood limit,Clotting Factor,Notes,,\n"
    "J0001,Example sedative inj,1 MG,0.167,20.000,,,,,,,,\n"
    'J0002,"Example drug, dose varies",Per Therapeutic Dose,12.500,20.000,,,,,,Added October 2026,,\n'
    "J0003,Example blood product,10 MG/3MG,N/A,20.000,,,,,,,,\n"
    "Q0001,Example contrast,1 ML,0.186,20.000,,,,,,,,\n"
    "00003,Example vaccine,1 ML,138.229,20.000,,,,,,,,\n"
    "0000U,Example lab panel,1 ML,5.000,20.000,,,,,,,,\n"
)


def test_drug_limits_keep_letter_codes_only() -> None:
    rows = list(parse_drug_limits_text(DRUG_CSV))
    assert [r.code for r in rows] == ["J0001", "J0002", "J0003", "Q0001"]


def test_drug_limit_row_keeps_dosage_as_written_and_parses_it() -> None:
    row = next(parse_drug_limits_text(DRUG_CSV))
    assert row == DrugLimitRow(
        code="J0001", short_description="Example sedative inj", dosage="1 MG",
        dose_value=Decimal("1"), dose_unit="MG", payment_limit=Decimal("0.167"),
    )


def test_an_unparseable_dosage_is_kept_as_written_with_null_dose() -> None:
    rows = {r.code: r for r in parse_drug_limits_text(DRUG_CSV)}
    assert rows["J0002"].dosage == "Per Therapeutic Dose"
    assert rows["J0002"].dose_value is None and rows["J0002"].dose_unit is None
    assert rows["J0002"].short_description == "Example drug, dose varies"  # quoted comma survives


def test_a_payment_limit_that_is_not_a_number_is_null() -> None:
    rows = {r.code: r for r in parse_drug_limits_text(DRUG_CSV)}
    assert rows["J0003"].payment_limit is None
    assert rows["Q0001"].payment_limit == Decimal("0.186")


def test_a_file_with_no_header_row_is_an_error() -> None:
    with pytest.raises(ValueError, match="header"):
        list(parse_drug_limits_text("a,b,c\n1,2,3\n"))


# --- MUE table (csv; first line is a notice, header cell contains a newline) -------------------------------

MUE_CSV = (
    '"Notice line one.\n\nNotice line two.",,,\n'
    '"HCPCS/\nCPT Code",Outpatient Hospital Services MUE Values,MUE Adjudication Indicator,MUE Rationale\n'
    "A0001,100,3 Date of Service Edit: Clinical,Prescribing Information\n"
    "G0001,1,2 Date of Service Edit: Policy,Anatomic Consideration\n"
    "J0001,30,1 Line Edit,CMS Policy\n"
    "00003,2,3 Date of Service Edit: Clinical,Nature of Analyte\n"
    "0002U,1,2 Date of Service Edit: Policy,Code Descriptor\n"
)


def test_mue_keeps_letter_codes_only() -> None:
    assert [r.code for r in parse_mue_text(MUE_CSV)] == ["A0001", "G0001", "J0001"]


def test_mue_row_fields() -> None:
    assert next(parse_mue_text(MUE_CSV)) == MueRow("A0001", 100, 3, "Prescribing Information")


def test_mai_is_read_from_the_first_character_and_is_1_2_or_3() -> None:
    assert {r.code: r.mai for r in parse_mue_text(MUE_CSV)} == {"A0001": 3, "G0001": 2, "J0001": 1}


def test_an_unknown_mai_is_an_error_not_a_guess() -> None:
    bad = MUE_CSV + "V0001,1,4 Something New,CMS Policy\n"
    with pytest.raises(ValueError, match="MAI"):
        list(parse_mue_text(bad))


def test_a_mue_value_that_is_not_a_whole_number_is_an_error() -> None:
    bad = MUE_CSV + "V0002,many,3 Date of Service Edit: Clinical,CMS Policy\n"
    with pytest.raises(ValueError, match="MUE"):
        list(parse_mue_text(bad))


# --- HCPCS alpha-numeric file (fixed width) --------------------------------------------------------------


def hcpcs_first_line(code: str, long: str, short: str, added: str = "20080101", eff: str = "20080101", term: str = "") -> str:
    """A record-id 3 line laid out like HCPC2026_recordlayout.txt: code 1-5, sequence 6-10, record id 11,
    long description 12-91, short description 92-119, dates at 269-292, action code at 293."""
    line = f"{code:<5}00100" + "3" + f"{long:<80}" + f"{short:<28}"
    return line.ljust(268) + f"{added:<8}{eff:<8}{term:<8}" + "N"


def hcpcs_continuation(code: str, text: str, seq: int = 200) -> str:
    return f"{code:<5}{seq:05d}4{text}"


def test_hcpcs_first_line_fields() -> None:
    line = hcpcs_first_line("X0001", "Example injection, per 1 mg", "Example inj", "19960101", "19970101")
    assert list(parse_hcpcs_lines([line])) == [
        HcpcsRow("X0001", "Example inj", "Example injection, per 1 mg", "19960101", "19970101", None)
    ]


def test_a_blank_termination_date_is_none_and_a_set_one_is_kept() -> None:
    rows = list(parse_hcpcs_lines([
        hcpcs_first_line("X0001", "Live code", "Live"),
        hcpcs_first_line("X0002", "Ended code", "Ended", term="20231231"),
    ]))
    assert [r.termination_date for r in rows] == [None, "20231231"]


def test_continuation_lines_extend_the_long_description() -> None:
    lines = [
        hcpcs_first_line("X0001", "Example screening procedure on individual not meeting criteria for", "Example scrn"),
        hcpcs_continuation("X0001", "high risk"),
    ]
    row = next(parse_hcpcs_lines(lines))
    assert row.long_description == "Example screening procedure on individual not meeting criteria for high risk"


def test_continuations_attach_to_their_own_code_in_file_order() -> None:
    lines = [
        hcpcs_first_line("X0001", "First long text,", "First"),
        hcpcs_continuation("X0001", "continued one"),
        hcpcs_first_line("X0002", "Second long text,", "Second"),
        hcpcs_continuation("X0002", "continued two"),
    ]
    assert [r.long_description for r in parse_hcpcs_lines(lines)] == [
        "First long text, continued one", "Second long text, continued two",
    ]


def test_digit_first_codes_and_modifier_records_are_dropped() -> None:
    modifier = "   A1" + "00100" + "7" + "Dressing for one wound".ljust(80) + "Dressing".ljust(28)
    lines = [
        hcpcs_first_line("12345", "Not a Level II code", "Nope"),
        modifier,
        "",
        hcpcs_first_line("X0001", "Kept", "Kept"),
    ]
    assert [r.code for r in parse_hcpcs_lines(lines)] == ["X0001"]


def test_continuation_of_a_dropped_code_is_dropped_too() -> None:
    lines = [hcpcs_first_line("12345", "Dropped", "Dropped"), hcpcs_continuation("12345", "more"), hcpcs_first_line("X0001", "Kept", "Kept")]
    rows = list(parse_hcpcs_lines(lines))
    assert [r.code for r in rows] == ["X0001"] and rows[0].long_description == "Kept"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("add-on (list separately in addition to 00001 or 00002)", "add-on (list separately in addition to [CPT code] or [CPT code])"),
        ("category III code 0000T applies", "category III code [CPT code] applies"),
        ("quality code 0000F applies", "quality code [CPT code] applies"),
        # CMS lowercases some long descriptions, so a suffix F or T can be lowercase. A lowercase u is a unit
        # ("per 1000u"), so only an uppercase U counts as a code suffix.
        ("do not use in conjunction with 0000t)", "do not use in conjunction with [CPT code])"),
        ("quality code 0000f applies", "quality code [CPT code] applies"),
        ("heparin sodium per 1000u", "heparin sodium per 1000u"),
        ("no codes here, 12 units of 5 mg", "no codes here, 12 units of 5 mg"),
        ("account 123456 stays", "account 123456 stays"),  # six digits is not a CPT-shaped token
    ],
)
def test_cpt_shaped_tokens_in_descriptions_are_redacted(text: str, expected: str) -> None:
    assert redact_cpt_codes(text) == expected


def test_hcpcs_descriptions_never_carry_a_cpt_shaped_code() -> None:
    line = hcpcs_first_line("X0001", "Add-on to primary service (list separately in addition to 00001)", "Add-on 00001")
    row = next(parse_hcpcs_lines([line]))
    assert "00001" not in row.long_description and "00001" not in row.short_description
    assert "[CPT code]" in row.long_description
