"""The eval runner drives the same CaseService as the web app. Offline (no models) it must still produce a full
record, so the wiring is tested without spending credits; the live numbers come from `python -m eval`."""

import os
from pathlib import Path

import pytest

from eval.run import Run
from eval.runner import CASES, models_env, run_cases

ROOT = Path(__file__).resolve().parent.parent


def test_the_cases_are_every_sample_and_the_phone_photo() -> None:
    assert [(c.name, c.sample, c.bill, c.eob) for c in CASES] == [
        ("maya", "maya", "bill.pdf", None),
        ("maya-photo", "maya", "bill_photo.jpg", None),
        ("dev", "dev", "bill.pdf", "eob.pdf"),
        ("clean", "clean", "bill.pdf", None),
    ]
    for case in CASES:
        assert (ROOT / "samples" / case.sample / case.bill).is_file()


def test_an_offline_run_scores_every_pdf_sample(tmp_path: Path, reference_db_path: Path) -> None:
    run = run_cases(
        [c for c in CASES if c.bill.endswith(".pdf")], mode="routed", reference_db=reference_db_path,
        samples_dir=ROOT / "samples", work_dir=tmp_path, offline=True,
    )
    assert isinstance(run, Run) and [s.name for s in run.samples] == ["maya", "dev", "clean"]
    for s in run.samples:
        assert s.error is None and s.calls == []
        assert s.extraction["code"].total >= 1 and s.findings is not None
    clean = next(s for s in run.samples if s.name == "clean")
    assert clean.findings.false_likely == []


def test_a_document_that_cannot_be_read_is_a_scored_miss_not_a_crash(tmp_path: Path, reference_db_path: Path) -> None:
    run = run_cases(
        [c for c in CASES if c.name == "maya-photo"], mode="routed", reference_db=reference_db_path,
        samples_dir=ROOT / "samples", work_dir=tmp_path, offline=True,  # a photo needs the vision model
    )
    (photo,) = run.samples
    assert photo.error and photo.lines_read == 0
    assert photo.findings.caught == 0 and len(photo.findings.missed) == photo.findings.expected_errors > 0
    assert photo.extraction["code"].ok == 0


def test_model_overrides_are_set_for_the_run_and_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_WRITER", "keep/me")
    monkeypatch.delenv("MODEL_CLEANER", raising=False)
    with models_env({"WRITER": "x/y", "CLEANER": "x/z"}):
        assert os.environ["MODEL_WRITER"] == "x/y" and os.environ["MODEL_CLEANER"] == "x/z"
    assert os.environ["MODEL_WRITER"] == "keep/me" and "MODEL_CLEANER" not in os.environ


def test_the_image_probe_reports_whether_ultra_accepts_an_image() -> None:
    from app.llm import LLMClient
    from eval.runner import ultra_reads_images
    from tests.fakes import FakeOpenAI

    os.environ["MODEL_READER"] = "test/reader"
    try:
        assert ultra_reads_images(LLMClient(client=FakeOpenAI(["OK"]))) is True
        assert ultra_reads_images(LLMClient(client=FakeOpenAI([RuntimeError("400 images not supported")]))) is False
    finally:
        os.environ.pop("MODEL_READER", None)
