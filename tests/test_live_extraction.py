"""Calls the real Token Factory. Run with: pytest -m live   (costs a few cents of credit)."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.config import ConfigError, Step, model_for
from app.extract import extract_bill, extract_eob
from app.llm import LLMClient
from app.refdb import open_reference
from app.schemas import ExpectedSample
from app.store import Store

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "claimguard.db"

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def require_live_setup() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("NEBIUS_API_KEY"):
        pytest.skip("NEBIUS_API_KEY not set")
    if not REAL_DB.exists():
        pytest.skip("run `python -m ingest` first")
    for step in (Step.READ_DOCUMENT, Step.CLEAN_CODES):
        try:
            model_for(step)
        except ConfigError as error:
            pytest.skip(str(error))


def extract_live(path: Path, tmp_path: Path, patient_type: str = "self_pay"):
    store = Store(tmp_path / "state.db")
    case_id = store.create_case(patient_type)
    ref = open_reference(REAL_DB)
    result = extract_bill(path, ref, llm=LLMClient(sink=store), case_id=case_id)
    return result, store.calls(case_id)


def assert_matches(result, expected: ExpectedSample) -> None:
    assert result.source == "vision"
    got = [(x.code, x.units, x.charge, x.dose_value, x.dose_unit) for x in result.lines]
    want = [(x.code, x.units, x.charge, x.dose_value, x.dose_unit) for x in expected.lines]
    assert got == want
    assert [x.code_class for x in result.lines] == ["hcpcs_level2"] * len(expected.lines)
    assert [x.status for x in result.lines] == ["ok"] * len(expected.lines)
    assert result.bill_date == expected.bill_date
    assert result.amount_due == expected.amount_due


@pytest.mark.parametrize("name", ["maya", "dev", "clean"])
def test_vision_reads_the_sample_bills(name: str, tmp_path: Path) -> None:
    expected = ExpectedSample.model_validate_json((ROOT / "samples" / name / "expected_flags.json").read_text())
    result, calls = extract_live(ROOT / "samples" / name / "bill.pdf", tmp_path)
    assert_matches(result, expected)
    assert [c.step for c in calls if c.ok] == ["read_document", "clean_codes"]  # doses ride on the Nano call
    assert all(c.latency_ms > 0 and c.prompt_tokens for c in calls if c.ok)


def test_vision_reads_every_line_of_the_phone_photo(tmp_path: Path) -> None:
    """The phone-style photo of Maya's bill: tilted, textured, shadowed. Every line, dose and total must match."""
    expected = ExpectedSample.model_validate_json((ROOT / "samples" / "maya" / "expected_flags.json").read_text())
    result, calls = extract_live(ROOT / "samples" / "maya" / "bill_photo.jpg", tmp_path)
    assert_matches(result, expected)
    assert [(c.step, c.model) for c in calls if c.ok] == [
        ("read_document", model_for(Step.READ_DOCUMENT)), ("clean_codes", model_for(Step.CLEAN_CODES)),
    ]
    assert model_for(Step.READ_DOCUMENT) == "nvidia/Nemotron-3.5-Super-VL"


def test_vision_reads_devs_eob(tmp_path: Path) -> None:
    expected = ExpectedSample.model_validate_json((ROOT / "samples" / "dev" / "expected_flags.json").read_text()).eob
    store = Store(tmp_path / "state.db")
    case_id = store.create_case("insured")
    result = extract_eob(ROOT / "samples" / "dev" / "eob.pdf", llm=LLMClient(sink=store), case_id=case_id)
    assert result.source == "vision"
    assert (result.billed, result.allowed, result.patient_responsibility) == (
        expected.billed, expected.allowed, expected.patient_responsibility,
    )
