"""The record of one eval run: what each sample scored and every model call it made. Saved as JSON so the report
can show the routed and the all-Ultra runs side by side. Holds scores, labels and token counts, no document text."""

from typing import Literal

from pydantic import BaseModel

from eval.score import FindingScore, Tally


class CallRow(BaseModel):
    step: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    ok: bool


class SampleRun(BaseModel):
    name: str  # "maya", "maya-photo", "dev", "clean"
    sample_id: str  # which expected_flags.json scored it
    document: str
    wall_seconds: float
    lines_expected: int
    lines_read: int
    extraction: dict[str, Tally]
    findings: FindingScore
    calls: list[CallRow]
    letters: int = 0
    error: str | None = None  # why the document could not be read or confirmed; the misses are scored


class Run(BaseModel):
    mode: Literal["routed", "all_ultra"]
    finished_at: str
    models: dict[str, str]  # step -> model ID actually used
    prices: dict[str, dict[str, str]]  # model ID -> {"input", "output"} USD per million tokens
    price_source: str
    notes: list[str]
    samples: list[SampleRun]
