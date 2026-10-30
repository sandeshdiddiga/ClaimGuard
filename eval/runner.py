"""Run every sample through the real pipeline: read the documents, confirm the lines as read, run the checks and
the amber review, write the letters. It drives the same CaseService as the web app, so what is measured is what
ships. Nothing is tuned to the samples: the lines are confirmed exactly as the reader produced them."""

import base64
import io
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from app.api_models import ConfirmRequest, LineIn
from app.cases import CaseService
from app.config import MODEL_IDS, PRICE_SOURCE, PRICES, ROUTING, Role, Step, model_for
from app.extract import ExtractionError
from app.llm import LLMClient, LLMError, image_part
from app.refdb import open_reference
from app.schemas import ExpectedSample
from app.settings import Settings
from app.store import Store
from eval.run import CallRow, Run, SampleRun
from eval.score import score_extraction, score_findings


@dataclass(frozen=True)
class EvalCase:
    name: str
    sample: str  # the samples/ folder whose expected_flags.json scores it
    bill: str
    eob: str | None = None


# Every sample, plus Maya's bill again as a phone-style photo (same expected lines and findings).
CASES = [
    EvalCase("maya", "maya", "bill.pdf"),
    EvalCase("maya-photo", "maya", "bill_photo.jpg"),
    EvalCase("dev", "dev", "bill.pdf", "eob.pdf"),
    EvalCase("clean", "clean", "bill.pdf"),
]


@contextmanager
def models_env(overrides: dict[str, str]) -> Iterator[None]:
    """Point roles at other models for the duration of a run: {"WRITER": "<model id>"} sets MODEL_WRITER."""
    names = {f"MODEL_{role}": model for role, model in overrides.items()}
    before = {name: os.environ.get(name) for name in names}
    os.environ.update(names)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def ultra_reads_images(llm: LLMClient) -> bool:
    """Whether the model now set for the reader role accepts an image. Token Factory lists Nemotron 3 Ultra as
    text only; this checks it with one tiny call instead of assuming."""
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
    message = [{"role": "user", "content": [{"type": "text", "text": "Reply with OK."}, image_part(buffer.getvalue())]}]
    try:
        llm.complete_text(Step.READ_DOCUMENT, message, case_id="probe")
    except LLMError:
        return False
    return True


def _calls(store: Store, case_id: str) -> list[CallRow]:
    return [
        CallRow(step=c.step, model=c.model, latency_ms=c.latency_ms, prompt_tokens=c.prompt_tokens,
                completion_tokens=c.completion_tokens, ok=c.ok)
        for c in store.calls(case_id)
    ]


def run_case(
    case: EvalCase, *, reference_db: Path, samples_dir: Path, work_dir: Path, offline: bool = False
) -> SampleRun:
    sample = ExpectedSample.model_validate_json((samples_dir / case.sample / "expected_flags.json").read_text())
    folder = samples_dir / case.sample
    settings = Settings(
        reference_db=reference_db, state_db=work_dir / f"{case.name}.db", samples_dir=samples_dir,
        offline=offline, vision=True,
    )
    store, ref = Store(settings.state_db), open_reference(reference_db)
    service = CaseService(settings, store, ref)
    started = time.perf_counter()
    error: str | None = None
    lines, header, eob, findings = [], {}, None, []
    total, deadline, letters = Decimal("0.00"), None, 0
    case_id = ""
    try:
        case_id = service.create(
            sample.patient_type, sample.gfe_total, folder / case.bill, folder / case.eob if case.eob else None
        )
        view = service.view(case_id)
        lines, eob = view.lines, view.eob
        header = {"facility_name": view.facility_name, "bill_date": view.bill_date, "amount_due": view.amount_due}
        # The patient's confirm step: the lines go forward exactly as read, uncorrected.
        service.confirm(
            case_id,
            ConfirmRequest(
                lines=[LineIn(**line.model_dump()) for line in lines], bill_date=view.bill_date,
                amount_due=view.amount_due, gfe_total=view.gfe_total,
            ),
        )
        results = service.view(case_id).results
        assert results is not None
        findings, total, deadline = results.findings, results.dollars_at_stake, results.deadline
        letters = len(service.letters(case_id))
    except ExtractionError as exc:
        error = str(exc)
    except ValidationError:
        error = "a line could not be confirmed as read (malformed code, units or charge)"
    wall = time.perf_counter() - started
    tallies, expected_n, read_n = score_extraction(sample, lines, header, eob)
    calls = _calls(store, case_id) if case_id else []
    store.close()
    ref.close()
    return SampleRun(
        name=case.name, sample_id=case.sample, document=case.bill, wall_seconds=round(wall, 1),
        lines_expected=expected_n, lines_read=read_n, extraction=tallies,
        findings=score_findings(sample, findings, total, deadline), calls=calls, letters=letters, error=error,
    )


def run_cases(
    cases: list[EvalCase], *, mode: str, reference_db: Path, samples_dir: Path, work_dir: Path,
    offline: bool = False, notes: list[str] | None = None, progress: Callable[[str], None] = lambda _: None,
) -> Run:
    samples = []
    for case in cases:
        progress(f"running {case.name} ...")
        samples.append(run_case(case, reference_db=reference_db, samples_dir=samples_dir, work_dir=work_dir, offline=offline))
        progress(f"  done in {samples[-1].wall_seconds} s" + (f" (error: {samples[-1].error})" if samples[-1].error else ""))
    return Run(
        mode=mode,  # type: ignore[arg-type]
        finished_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        models={step.value: model_for(step) for step in ROUTING},
        prices={model: {"input": str(price.input), "output": str(price.output)} for model, price in PRICES.items()},
        price_source=PRICE_SOURCE, notes=notes or [], samples=samples,
    )


def all_ultra_overrides(llm: LLMClient | None = None) -> tuple[dict[str, str], list[str]]:
    """Roles to point at Nemotron 3 Ultra, and notes on anything that had to stay put. Ultra already judges; the
    cleaner and writer move to it. The reader moves only if Ultra accepts images."""
    ultra = MODEL_IDS[Role.JUDGE]
    overrides = {Role.CLEANER.name: ultra, Role.WRITER.name: ultra, Role.JUDGE.name: ultra}
    notes = []
    with models_env({Role.READER.name: ultra}):
        reads = ultra_reads_images(llm or LLMClient())
    if reads:
        overrides[Role.READER.name] = ultra
    else:
        notes.append(
            "The reading step stayed on Nemotron 3.5 Super VL: Nemotron 3 Ultra did not accept an image "
            "(Token Factory lists it as text only). Every other model step ran on Ultra."
        )
    return overrides, notes


def temp_work_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="claimguard-eval-")
