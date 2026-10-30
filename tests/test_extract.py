import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from app.extract import (
    EobExtraction,
    Extraction,
    ExtractionError,
    NotABillError,
    apply_nano,
    extract_bill,
    extract_eob,
    read_eob_with_pdfplumber,
    read_with_pdfplumber,
    resolve_codes,
)
from app.codes import NOT_CHECKED_NOTE, UNKNOWN_NOTE
from app.llm import LLMClient, LLMError
from app.refdb import open_reference
from app.schemas import ExpectedSample, ExtractedLine
from tests.fakes import FakeOpenAI, ListSink

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


@pytest.fixture
def ref(reference_db_path: Path):
    conn = open_reference(reference_db_path)
    yield conn
    conn.close()


def expected(name: str) -> ExpectedSample:
    return ExpectedSample.model_validate_json((SAMPLES / name / "expected_flags.json").read_text())


def line(code: str, charge: str = "10.00") -> ExtractedLine:
    return ExtractedLine(service_date="2026-09-14", code=code, description="x", units=1, charge=Decimal(charge))


def reading_json(*codes: str, description: str = "x") -> str:
    return json.dumps(
        {
            "bill_date": "2026-10-05",
            "lines": [
                {"service_date": "2026-09-14", "code": c, "description": description, "units": 1, "charge": "$1,980.00"}
                for c in codes
            ],
        }
    )


def gate_json(is_bill: bool = True, doses: dict | None = None, **fixes: tuple[str, bool]) -> str:
    return json.dumps(
        {
            "is_itemized_bill": is_bill,
            "reason": "" if is_bill else "this is a menu",
            "lines": [{"index": int(i), "code": c, "readable": r} for i, (c, r) in fixes.items()],
            "doses": [{"index": i, "dose_value": v, "dose_unit": u} for i, (v, u) in (doses or {}).items()],
        }
    )


# --- deterministic code cleanup ---------------------------------------------------------------------


def test_resolve_codes_statuses_and_classes(ref: sqlite3.Connection) -> None:
    lines, unresolved = resolve_codes(
        [line("G0121"), line("J22SO"), line("00000"), line("Z9999"), line("garbage"), line("0000F")], ref
    )
    assert [(x.code, x.status, x.code_class) for x in lines] == [
        ("G0121", "ok", "hcpcs_level2"),
        ("J2250", "corrected", "hcpcs_level2"),  # OCR repair on the four digits, accepted because it is in the table
        ("00000", "ok", "cpt_shaped"),  # shown unchanged, never looked up
        ("Z9999", "needs_review", "unknown_level2"),
        ("GARBAGE", "needs_review", "missing"),
        ("0000F", "ok", "cpt_shaped"),
    ]
    assert unresolved == [3, 4]
    assert lines[1].note == "read as 'J22SO'"
    assert lines[2].note == NOT_CHECKED_NOTE
    assert lines[3].note == UNKNOWN_NOTE


def test_a_cpt_shaped_code_is_not_repaired_or_queried(ref: sqlite3.Connection) -> None:
    class Spy:
        def execute(self, *args):
            raise AssertionError("looked up")

    lines, unresolved = resolve_codes([line("00000")], Spy())  # type: ignore[arg-type]
    assert lines[0].code_class == "cpt_shaped" and unresolved == []


def test_nano_suggestion_accepted_only_for_codes_in_the_hcpcs_table(ref: sqlite3.Connection) -> None:
    lines, unresolved = resolve_codes([line("J2Q50"), line("Z9998")], ref)
    merged = apply_nano(lines, unresolved, {0: ("J2250", True), 1: ("Z9999", True)}, ref)
    assert (merged[0].code, merged[0].status, merged[0].code_class) == ("J2250", "corrected", "hcpcs_level2")
    assert (merged[1].code, merged[1].status) == ("Z9998", "needs_review")  # suggestion not in the table


def test_nano_can_never_turn_a_line_into_a_cpt_shaped_code(ref: sqlite3.Connection) -> None:
    lines, unresolved = resolve_codes([line("garbage")], ref)
    merged = apply_nano(lines, unresolved, {0: ("00000", True)}, ref)
    assert (merged[0].code, merged[0].status) == ("GARBAGE", "needs_review")


def test_nano_cannot_touch_lines_the_deterministic_pass_resolved(ref: sqlite3.Connection) -> None:
    lines, unresolved = resolve_codes([line("G0121")], ref)
    assert apply_nano(lines, unresolved, {0: ("J2250", True)}, ref) == lines


def test_unreadable_nano_answer_leaves_line_for_review(ref: sqlite3.Connection) -> None:
    lines, unresolved = resolve_codes([line("???")], ref)
    merged = apply_nano(lines, unresolved, {0: ("G0121", False)}, ref)
    assert merged[0].status == "needs_review" and merged[0].code_class == "missing"


def test_a_missing_code_says_so(ref: sqlite3.Connection) -> None:
    (resolved,), _ = resolve_codes([line("")], ref)
    assert (resolved.code_class, resolved.status, resolved.note) == ("missing", "needs_review", "no recognizable code on this line")


# --- pdfplumber fallback ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["maya", "clean", "dev"])
def test_pdfplumber_reads_every_field_of_the_sample_bills(name: str) -> None:
    reading = read_with_pdfplumber(SAMPLES / name / "bill.pdf")
    want = expected(name)
    got = [(x.service_date, x.code, x.modifier, x.description, x.units, x.charge) for x in reading.lines]
    exp = [(x.service_date, x.code, x.modifier, x.description, x.units, x.charge) for x in want.lines]
    assert got == exp  # includes the rows the diagonal watermark crosses
    assert reading.bill_date == want.bill_date


# --- orchestration ----------------------------------------------------------------------------------


def run(replies: list, path: Path, ref: sqlite3.Connection) -> tuple[Extraction, ListSink, FakeOpenAI]:
    fake, sink = FakeOpenAI(replies), ListSink()
    llm = LLMClient(sink=sink, client=fake)
    return extract_bill(path, ref, llm=llm, case_id="c1"), sink, fake


def test_vision_then_nano_gate(ref: sqlite3.Connection) -> None:
    result, sink, fake = run([reading_json("G0121", "J2250"), gate_json()], SAMPLES / "clean" / "bill.pdf", ref)
    assert result.source == "vision"
    assert [x.code for x in result.lines] == ["G0121", "J2250"]
    assert result.lines[0].charge == Decimal("1980.00")  # "$1,980.00" parsed without float
    assert [r.step for _, r in sink.records] == ["read_document", "clean_codes"]
    vision_request = fake.completions.requests[0]
    assert vision_request["model"] == "test/reader"
    image_parts = [p for m in vision_request["messages"] for p in (m["content"] if isinstance(m["content"], list) else []) if p["type"] == "image_url"]
    assert len(image_parts) == 1


def test_misread_code_is_repaired_without_nano(ref: sqlite3.Connection) -> None:
    result, _, _ = run([reading_json("G012I"), gate_json()], SAMPLES / "clean" / "bill.pdf", ref)
    assert (result.lines[0].code, result.lines[0].status) == ("G0121", "corrected")


def test_nano_fixes_what_deterministic_repair_cannot(ref: sqlite3.Connection) -> None:
    result, _, _ = run([reading_json("JQ250"), gate_json(**{"0": ("J2250", True)})], SAMPLES / "clean" / "bill.pdf", ref)
    assert (result.lines[0].code, result.lines[0].status) == ("J2250", "corrected")


def test_non_bill_is_rejected_by_the_gate(ref: sqlite3.Connection) -> None:
    with pytest.raises(NotABillError, match="menu"):
        run([reading_json("G0121"), gate_json(is_bill=False)], SAMPLES / "clean" / "bill.pdf", ref)


def test_vision_failure_falls_back_to_pdfplumber(ref: sqlite3.Connection) -> None:
    result, sink, _ = run(
        [ConnectionError("down"), gate_json()], SAMPLES / "maya" / "bill.pdf", ref
    )
    assert result.source == "pdfplumber"
    assert len(result.lines) == len(expected("maya").lines) == 8
    assert [(r.step, r.ok) for _, r in sink.records] == [("read_document", False), ("clean_codes", True)]


def test_image_without_vision_fails_clearly(tmp_path: Path, ref: sqlite3.Connection) -> None:
    from PIL import Image

    photo = tmp_path / "bill.png"
    Image.new("RGB", (50, 50), "white").save(photo)
    with pytest.raises(ExtractionError, match="photo"):
        run([ConnectionError("down")], photo, ref)
    with pytest.raises(ExtractionError, match="vision"):
        extract_bill(photo, ref, llm=None, case_id="c")


def test_offline_mode_makes_no_model_calls(ref: sqlite3.Connection) -> None:
    result = extract_bill(SAMPLES / "maya" / "bill.pdf", ref, llm=None, case_id="c")
    assert result.source == "pdfplumber"
    assert [x.code for x in result.lines] == [x.code for x in expected("maya").lines]
    assert [x.code for x in result.lines] == ["G0121", "J2250", "J2250", "J3010", "J2704", "J2405", "J7120", "A4216"]
    assert {x.status for x in result.lines} == {"ok"}


def test_empty_reading_is_an_error(ref: sqlite3.Connection) -> None:
    with pytest.raises(ExtractionError, match="no charge lines"):
        run([json.dumps({"lines": []})], SAMPLES / "clean" / "bill.pdf", ref)


def test_unsupported_file_type(tmp_path: Path, ref: sqlite3.Connection) -> None:
    doc = tmp_path / "bill.docx"
    doc.write_bytes(b"x")
    with pytest.raises(ExtractionError, match="unsupported"):
        extract_bill(doc, ref, llm=None, case_id="c")


# --- balance due and the EOB ------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["maya", "clean", "dev"])
def test_pdfplumber_reads_the_balance_due(name: str) -> None:
    assert read_with_pdfplumber(SAMPLES / name / "bill.pdf").amount_due == expected(name).amount_due


def test_dev_bill_lines_and_balance_due_offline(ref: sqlite3.Connection) -> None:
    result = extract_bill(SAMPLES / "dev" / "bill.pdf", ref, llm=None, case_id="c")
    assert [(x.code, x.units, x.charge) for x in result.lines] == [
        ("G0121", 1, Decimal("2800.00")), ("J2704", 20, Decimal("110.00")),
        ("J2405", 8, Decimal("192.00")), ("J7120", 1, Decimal("142.00")),
    ]
    assert result.amount_due == Decimal("1460.00")


def test_pdfplumber_reads_the_eob() -> None:
    eob = expected("dev").eob
    reading = read_eob_with_pdfplumber(SAMPLES / "dev" / "eob.pdf")
    assert (reading.billed, reading.allowed, reading.patient_responsibility) == (
        eob.billed, eob.allowed, eob.patient_responsibility,
    )


def eob_json(**overrides: object) -> str:
    return json.dumps(
        {"insurer_name": "Sample plan", "billed": "$2,265.00", "allowed": 1140, "patient_responsibility": 410.0} | overrides
    )


def test_vision_reads_the_eob_into_exact_decimals() -> None:
    fake, sink = FakeOpenAI([eob_json()]), ListSink()
    result = extract_eob(SAMPLES / "dev" / "eob.pdf", llm=LLMClient(sink=sink, client=fake), case_id="c1")
    assert isinstance(result, EobExtraction) and result.source == "vision"
    assert (result.billed, result.allowed, result.patient_responsibility) == (
        Decimal("2265.00"), Decimal("1140"), Decimal("410.0"),
    )
    assert [(r.step, r.model) for _, r in sink.records] == [("read_document", "test/reader")]


def test_eob_invalid_json_is_retried_once() -> None:
    fake, sink = FakeOpenAI(["sorry, I cannot", eob_json()]), ListSink()
    result = extract_eob(SAMPLES / "dev" / "eob.pdf", llm=LLMClient(sink=sink, client=fake), case_id="c")
    assert result.source == "vision"
    assert [r.ok for _, r in sink.records] == [False, True]


def test_eob_missing_amount_is_rejected_then_falls_back_to_pdfplumber() -> None:
    bad = json.dumps({"billed": "2265.00", "allowed": "1140.00"})  # no patient responsibility, twice
    fake = FakeOpenAI([bad, bad])
    result = extract_eob(SAMPLES / "dev" / "eob.pdf", llm=LLMClient(client=fake), case_id="c")
    assert result.source == "pdfplumber"
    assert result.patient_responsibility == Decimal("410.00")


def test_eob_offline_and_unsupported_inputs(tmp_path: Path) -> None:
    assert extract_eob(SAMPLES / "dev" / "eob.pdf", llm=None, case_id="c").source == "pdfplumber"
    doc = tmp_path / "eob.docx"
    doc.write_bytes(b"x")
    with pytest.raises(ExtractionError, match="unsupported"):
        extract_eob(doc, llm=None, case_id="c")
    with pytest.raises(ExtractionError, match="no amounts"):
        extract_eob(SAMPLES / "maya" / "bill.pdf", llm=None, case_id="c")  # a bill is not an EOB


def test_amounts_read_as_numbers_are_shown_with_cents() -> None:
    from decimal import Decimal

    from app.schemas import BillReading, ExtractedLine

    line = ExtractedLine(code="G0121", charge=1980.0)  # a model replied with a JSON number
    assert str(line.charge) == "1980.00" and str(ExtractedLine(code="G0121", charge="285").charge) == "285.00"
    assert BillReading(lines=[line], amount_due=7235.0).amount_due == Decimal("7235.00")
    assert str(ExtractedLine(code="G0121", charge="1.005").charge) == "1.005"  # never rounded


# --- doses through the whole extraction -------------------------------------------------------------


def test_doses_from_the_nano_call_are_attached_when_the_text_states_them(ref: sqlite3.Connection) -> None:
    reading = reading_json("J2250", description="Rev 0636 Midazolam HCl inj 2 mg")
    result, sink, _ = run([reading, gate_json(doses={0: ("2", "mg")})], SAMPLES / "clean" / "bill.pdf", ref)
    assert (result.lines[0].dose_value, result.lines[0].dose_unit) == (Decimal("2"), "MG")
    assert [r.step for _, r in sink.records] == ["read_document", "clean_codes"]  # doses ride on the one Nano call


def test_a_dose_nano_invents_is_dropped(ref: sqlite3.Connection) -> None:
    reading = reading_json("G0121", description="Rev 0750 Screening colonoscopy, average risk")
    result, _, _ = run([reading, gate_json(doses={0: ("5", "mg")})], SAMPLES / "clean" / "bill.pdf", ref)
    assert (result.lines[0].dose_value, result.lines[0].dose_unit) == (None, None)


def test_offline_extraction_reads_doses_with_the_deterministic_parser(ref: sqlite3.Connection) -> None:
    result = extract_bill(SAMPLES / "maya" / "bill.pdf", ref, llm=None, case_id="c")
    got = [(x.code, x.dose_value, x.dose_unit) for x in result.lines]
    want = [(x.code, x.dose_value, x.dose_unit) for x in expected("maya").lines]
    assert got == want
    assert [x.code_class for x in result.lines] == ["hcpcs_level2"] * 8


def test_a_failed_nano_call_still_fails_the_extraction(ref: sqlite3.Connection) -> None:
    """The Nano call also confirms the upload is a bill, so its failure is not papered over with regex doses."""
    reading = reading_json("J2250", description="Rev 0636 Midazolam HCl inj 2 mg")
    with pytest.raises(LLMError):
        run([reading, "not json", "still not json"], SAMPLES / "clean" / "bill.pdf", ref)


def test_the_facility_name_the_vision_model_reads_is_kept(ref: sqlite3.Connection) -> None:
    reading = json.loads(reading_json("G0121"))
    reading["facility_name"] = "Riverbend Community Hospital"
    result, _, _ = run([json.dumps(reading), gate_json()], SAMPLES / "clean" / "bill.pdf", ref)
    assert result.facility_name == "Riverbend Community Hospital"


# --- label variants on an EOB -----------------------------------------------------------------------


def eob_text(billed: str, allowed: str, owed: str) -> str:
    return f"Explanation of Benefits\n{billed} $2,265.00\n{allowed} $1,140.00\n{owed} $410.00\nThis is not a bill."


@pytest.mark.parametrize(
    "owed",
    ["Patient responsibility", "patient responsibility", "Member responsibility", "Your share", "You owe",
     "Amount you owe", "What you owe", "Amount you owe:"],
)
def test_the_eob_reader_accepts_each_patient_responsibility_label(
    owed: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.extract.unrotated_text", lambda path: eob_text("Amount billed", "Allowed amount", owed))
    reading = read_eob_with_pdfplumber(tmp_path / "x.pdf")
    assert (reading.billed, reading.allowed, reading.patient_responsibility) == (
        Decimal("2265.00"), Decimal("1140.00"), Decimal("410.00"),
    )


@pytest.mark.parametrize("allowed", ["Allowed amount", "Allowed Amount", "Plan allowed", "Plan allowed amount"])
def test_the_eob_reader_accepts_each_allowed_label(allowed: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.extract.unrotated_text", lambda path: eob_text("Amount billed by provider", allowed, "You owe"))
    assert read_eob_with_pdfplumber(tmp_path / "x.pdf").allowed == Decimal("1140.00")


def test_an_eob_missing_one_label_is_still_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.extract.unrotated_text", lambda path: "Amount billed $10.00\nYou owe $5.00")
    with pytest.raises(ExtractionError, match="no amounts"):
        read_eob_with_pdfplumber(tmp_path / "x.pdf")


def test_an_eob_whose_label_repeats_with_different_amounts_is_not_guessed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = "Amount billed $2,265.00\nAllowed amount $1,140.00\nYour share $20.00\nYour share $390.00"
    monkeypatch.setattr("app.extract.unrotated_text", lambda path: text)
    with pytest.raises(ExtractionError, match="no amounts"):
        read_eob_with_pdfplumber(tmp_path / "x.pdf")


def test_inconsistent_eob_amounts_from_the_model_are_refused() -> None:
    bad = eob_json(billed="100.00", allowed="900.00", patient_responsibility="50.00")  # allowed above billed
    fake = FakeOpenAI([bad, bad])
    with pytest.raises(ExtractionError, match="do not look like an EOB"):
        extract_eob(SAMPLES / "maya" / "bill.pdf", llm=LLMClient(client=fake), case_id="c")
