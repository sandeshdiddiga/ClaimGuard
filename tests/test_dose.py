"""The dose written on a bill line: Nano reads it from the description text only, and Python checks the text.

A dose that the description does not contain is dropped, so a model can never invent one.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.dose import dose_candidates, normalize_unit, settle_dose
from app.llm import LLMClient
from app.safety import review_lines
from app.schemas import ExpectedSample, ExtractedLine
from tests.fakes import FakeOpenAI, ListSink

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
D = Decimal


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


# --- every sample description, read by the deterministic parser ---------------------------------------------


@pytest.mark.parametrize("name", ["maya", "dev", "clean"])
def test_the_sample_descriptions_give_the_expected_doses(name: str) -> None:
    sample = ExpectedSample.model_validate_json((SAMPLES / name / "expected_flags.json").read_text())
    for item in sample.lines:
        assert settle_dose(item.description, None, None) == (item.dose_value, item.dose_unit), item.description


@pytest.mark.parametrize(
    "description, expected",
    [
        ("Rev 0636 Midazolam HCl inj 2 mg", [(D("2"), "MG")]),
        ("Rev 0636 Fentanyl citrate inj 100 mcg", [(D("100"), "MCG")]),
        ("Rev 0258 Lactated Ringer's IV 1000 mL", [(D("1000"), "ML")]),
        ("Rev 0636 Propofol inj 200 mg", [(D("200"), "MG")]),
        ("Rev 0750 Screening colonoscopy, average risk", []),
        ("Rev 0636 Ondansetron inj 0.5mg", [(D("0.5"), "MG")]),  # no space
        ("Sedative 2 MG and 50 mcg", [(D("2"), "MG"), (D("50"), "MCG")]),
        ("Drug 1 mg/mL vial", []),  # a concentration, not a dose
        ("Rev 0636 inj .25 mg", [(D("0.25"), "MG")]),
        ("Saline 1,000 mL bag", [(D("1000"), "ML")]),
        ("Drug 5 ug", [(D("5"), "MCG")]),
        ("Powder 2 g", [(D("2"), "GM")]),
        ("Rev 0636 drug", []),  # the revenue code alone is not a dose
        ("Rev 0270 supply, 10 units", [(D("10"), "UNITS")]),
    ],
)
def test_dose_candidates(description: str, expected: list[tuple[Decimal, str]]) -> None:
    assert dose_candidates(description) == expected


@pytest.mark.parametrize("raw, unit", [("mg", "MG"), ("Mg", "MG"), ("ug", "MCG"), ("MCG", "MCG"), ("g", "GM"), ("gm", "GM"), ("cc", "CC"), ("mL", "ML")])
def test_normalize_unit(raw: str, unit: str) -> None:
    assert normalize_unit(raw) == unit


# --- Nano's answer is accepted only when the text contains it -----------------------------------------------


def test_nanos_dose_is_accepted_when_the_description_states_it() -> None:
    assert settle_dose("Midazolam HCl inj 2 mg", D("2"), "mg") == (D("2"), "MG")


def test_a_dose_the_description_does_not_state_is_dropped() -> None:
    assert settle_dose("Midazolam HCl inj 2 mg", D("5"), "MG") == (D("2"), "MG")  # falls back to the one stated dose
    assert settle_dose("Screening colonoscopy, average risk", D("2"), "MG") == (None, None)


def test_a_dose_with_the_wrong_unit_is_dropped() -> None:
    assert settle_dose("Fentanyl citrate inj 100 mcg", D("100"), "MG") == (D("100"), "MCG")


def test_with_two_candidates_nano_chooses_and_python_verifies() -> None:
    text = "Sedative 2 mg given, vial 10 mg"
    assert settle_dose(text, D("2"), "MG") == (D("2"), "MG")
    assert settle_dose(text, D("10"), "MG") == (D("10"), "MG")
    assert settle_dose(text, D("7"), "MG") == (None, None)  # not stated, and no single candidate to fall back on
    assert settle_dose(text, None, None) == (None, None)  # ambiguous and no answer: leave it empty


def test_numbers_compare_by_value_not_text() -> None:
    assert settle_dose("Drug 2.0 mg", D("2"), "MG") == (D("2.0"), "MG")


def test_a_number_inside_another_number_is_not_a_match() -> None:
    assert settle_dose("Drug 12 mg", D("2"), "MG") == (D("12"), "MG")


# --- through the Nano call -----------------------------------------------------------------------------------


def line(code: str, description: str) -> ExtractedLine:
    return ExtractedLine(service_date="2026-09-14", code=code, description=description, units=1, charge=D("10.00"))


def run_gate(reply: dict, lines: list[ExtractedLine]):
    fake, sink = FakeOpenAI([json.dumps(reply)]), ListSink()
    gate = review_lines(LLMClient(sink=sink, client=fake), "c1", lines, unresolved=[])
    return gate, fake, sink


def test_the_nano_call_returns_a_dose_per_line_and_is_logged_once() -> None:
    lines = [line("J2250", "Midazolam HCl inj 2 mg"), line("G0121", "Screening colonoscopy")]
    gate, _, sink = run_gate(
        {"is_itemized_bill": True, "doses": [
            {"index": 0, "dose_value": "2", "dose_unit": "mg"}, {"index": 1, "dose_value": None, "dose_unit": None},
        ]},
        lines,
    )
    assert [(d.index, d.dose_value, d.dose_unit) for d in gate.doses] == [(0, D("2"), "mg"), (1, None, None)]
    assert [(r.step, r.ok) for _, r in sink.records] == [("clean_codes", True)]


def test_nano_may_answer_with_json_numbers() -> None:
    gate, _, _ = run_gate({"is_itemized_bill": True, "doses": [{"index": 0, "dose_value": 0.1, "dose_unit": "MG"}]}, [line("J3010", "Fentanyl 0.1 mg")])
    assert gate.doses[0].dose_value == D("0.1")


def test_the_prompt_tells_nano_to_use_the_description_only_and_sends_no_personal_data() -> None:
    _, fake, _ = run_gate({"is_itemized_bill": True}, [line("J2250", "Midazolam HCl inj 2 mg")])
    messages = fake.completions.requests[0]["messages"]
    text = " ".join(m["content"] for m in messages)
    assert "description" in text and "null" in text.lower()
    assert "never" in text.lower() or "only" in text.lower()
    assert "Midazolam HCl inj 2 mg" in text
