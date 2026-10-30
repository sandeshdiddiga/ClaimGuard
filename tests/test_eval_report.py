"""The eval scorecard: cost arithmetic, aggregation and the markdown that eval/results.md is made of."""

from decimal import Decimal

import pytest

from app.config import MODEL_IDS, PRICE_SOURCE, PRICES, Role, cost_usd
from eval.report import render_report, summarize
from eval.run import CallRow, Run, SampleRun
from eval.score import FindingScore, Tally

NANO, ULTRA, SUPER = MODEL_IDS[Role.CLEANER], MODEL_IDS[Role.JUDGE], MODEL_IDS[Role.WRITER]


def call(step: str, model: str, prompt: int, completion: int, ms: int = 1000, ok: bool = True) -> CallRow:
    return CallRow(step=step, model=model, latency_ms=ms, prompt_tokens=prompt, completion_tokens=completion, ok=ok)


def sample(name: str = "maya", *, caught: int = 4, expected: int = 5, false: list[str] | None = None, calls=None) -> SampleRun:
    return SampleRun(
        name=name, sample_id=name, document="bill.pdf", wall_seconds=12.5, lines_expected=8, lines_read=8,
        extraction={"code": Tally(ok=8, total=8), "charge": Tally(ok=7, total=8)},
        findings=FindingScore(
            expected_errors=expected, caught=caught, downgraded=0,
            missed=["duplicate, lines 2 and 3"] if caught < expected else [], false_likely=false or [],
        ),
        calls=calls if calls is not None else [call("clean_codes", NANO, 1000, 200), call("draft_letter", SUPER, 2000, 400)],
    )


def run(mode: str = "routed", samples: list[SampleRun] | None = None) -> Run:
    return Run(
        mode=mode, finished_at="2026-10-30T12:00:00Z", models={"clean_codes": NANO}, notes=[],
        prices={m: {"input": str(p.input), "output": str(p.output)} for m, p in PRICES.items()},
        price_source=PRICE_SOURCE, samples=samples if samples is not None else [sample()],
    )


def test_cost_is_tokens_times_the_listed_price() -> None:
    assert cost_usd(ULTRA, 1_000_000, 1_000_000) == Decimal("4.00")  # $1.00 in, $3.00 out per million
    assert cost_usd(NANO, 1_000_000, 0) == Decimal("0.06")


def test_an_unpriced_model_has_no_cost_and_missing_tokens_count_as_zero() -> None:
    assert cost_usd("someone/else", 10, 10) is None
    assert cost_usd(NANO, None, None) == Decimal("0")


def test_every_routed_model_has_a_price() -> None:
    assert set(MODEL_IDS.values()) <= set(PRICES)


def test_summary_adds_up_across_samples() -> None:
    s = summarize(run(samples=[sample("maya", caught=4, expected=5), sample("dev", caught=1, expected=1, false=["duplicate, line 1"])]))
    assert (s.caught, s.expected_errors) == (5, 6)
    assert len(s.missed) == 1 and s.false_likely == ["dev: duplicate, line 1"]
    assert s.prompt_tokens == 6000 and s.completion_tokens == 1200
    assert s.latency_ms == 4000
    assert s.cost == cost_usd(NANO, 2000, 400) + cost_usd(SUPER, 4000, 800)


def test_summary_groups_by_step_and_model() -> None:
    s = summarize(run())
    steps = {row.step: row for row in s.steps}
    assert steps["clean_codes"].calls == 1 and steps["clean_codes"].model == NANO
    assert steps["draft_letter"].cost == cost_usd(SUPER, 2000, 400)


def test_failed_calls_are_counted() -> None:
    s = summarize(run(samples=[sample(calls=[call("judge_amber", ULTRA, 100, 0, ok=False), call("judge_amber", ULTRA, 100, 50)])]))
    assert s.steps[0].calls == 2 and s.steps[0].failed == 1


def test_extraction_accuracy_is_pooled_per_field() -> None:
    s = summarize(run(samples=[sample("a"), sample("b")]))
    assert s.fields["charge"].ok == 14 and s.fields["charge"].total == 16
    assert round(s.extraction_share, 3) == round(30 / 32, 3)


def test_a_sample_that_failed_to_read_counts_all_its_expected_errors_as_missed() -> None:
    failed = SampleRun(name="x", sample_id="x", document="d", wall_seconds=1, lines_expected=3, lines_read=0,
                       extraction={"code": Tally(ok=0, total=3)}, findings=FindingScore(expected_errors=2, missed=["a", "b"]),
                       calls=[], error="could not read this document")
    s = summarize(run(samples=[failed]))
    assert s.caught == 0 and s.expected_errors == 2 and s.errors == ["x: could not read this document"]


def test_the_report_has_the_scorecard_sections_and_prices_with_their_source() -> None:
    text = render_report(run(), None)
    for heading in ("# ClaimGuard eval", "## Scorecard", "## Findings by sample", "## Extraction accuracy", "## Cost and latency by step", "## Prices used"):
        assert heading in text
    assert PRICE_SOURCE in text and "estimates" in text.lower()
    assert "$0.06" in text and "$1.00" in text  # per-million prices are shown


def test_the_report_says_when_the_all_ultra_run_is_missing() -> None:
    assert "python -m eval --all-ultra" in render_report(run(), None)


def test_the_report_compares_the_two_runs() -> None:
    routed = run(samples=[sample(calls=[call("clean_codes", NANO, 1_000_000, 0)])])
    ultra = run("all_ultra", [sample(calls=[call("clean_codes", ULTRA, 1_000_000, 0)])])
    text = render_report(routed, ultra)
    assert "Routed" in text and "Ultra for every step" in text
    assert "16.7" in text or "16.6" in text  # $1.00 / $0.06


def test_report_notes_are_shown_and_hold_no_document_text() -> None:
    r = run("all_ultra")
    r.notes = ["The reader stayed on Super VL: Ultra does not accept images."]
    assert "Ultra does not accept images" in render_report(None, r)


@pytest.mark.parametrize("routed,ultra", [(None, None)])
def test_nothing_to_report_is_an_error(routed, ultra) -> None:
    with pytest.raises(ValueError):
        render_report(routed, ultra)
