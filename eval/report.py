"""Turn eval runs into eval/results.md: the scorecard, findings and extraction detail, and cost and latency by step.

Costs are estimates: token counts from the call log times the list prices saved with the run."""

from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel

from app.config import MODEL_IDS, Role
from eval.run import CallRow, Run
from eval.score import Tally

NAMES = {
    MODEL_IDS[Role.READER]: "Nemotron 3.5 Super VL",
    MODEL_IDS[Role.CLEANER]: "Nemotron 3 Nano",
    MODEL_IDS[Role.JUDGE]: "Nemotron 3 Ultra",
    MODEL_IDS[Role.WRITER]: "Nemotron 3 Super",
}
LABEL = {"routed": "Routed (default)", "all_ultra": "Ultra for every step"}


class StepRow(BaseModel):
    step: str
    model: str
    calls: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost: Decimal = Decimal("0")


class Summary(BaseModel):
    expected_errors: int = 0
    caught: int = 0
    downgraded: int = 0
    missed: list[str] = []
    false_likely: list[str] = []
    unexpected: list[str] = []
    totals_ok: int = 0
    deadlines_ok: int = 0
    samples: int = 0
    fields: dict[str, Tally] = {}
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    wall_seconds: float = 0
    calls: int = 0
    failed_calls: int = 0
    unpriced_calls: int = 0
    cost: Decimal = Decimal("0")
    steps: list[StepRow] = []
    errors: list[str] = []

    @property
    def extraction_ok(self) -> int:
        return sum(t.ok for t in self.fields.values())

    @property
    def extraction_total(self) -> int:
        return sum(t.total for t in self.fields.values())

    @property
    def extraction_share(self) -> float:
        return self.extraction_ok / self.extraction_total if self.extraction_total else 0.0


def _price(run: Run, call: CallRow) -> Decimal | None:
    price = run.prices.get(call.model)
    if price is None:
        return None
    return (
        Decimal(price["input"]) * (call.prompt_tokens or 0) + Decimal(price["output"]) * (call.completion_tokens or 0)
    ) / Decimal(1_000_000)


def summarize(run: Run) -> Summary:
    s = Summary(samples=len(run.samples))
    steps: dict[tuple[str, str], StepRow] = {}
    fields: dict[str, Tally] = defaultdict(Tally)
    for sample in run.samples:
        f = sample.findings
        s.expected_errors += f.expected_errors
        s.caught += f.caught
        s.downgraded += f.downgraded
        s.missed += [f"{sample.name}: {item}" for item in f.missed]
        s.false_likely += [f"{sample.name}: {item}" for item in f.false_likely]
        s.unexpected += [f"{sample.name}: {item}" for item in f.unexpected]
        s.totals_ok += int(f.total_ok)
        s.deadlines_ok += int(f.deadline_ok)
        s.wall_seconds += sample.wall_seconds
        if sample.error:
            s.errors.append(f"{sample.name}: {sample.error}")
        for name, tally in sample.extraction.items():
            fields[name].ok += tally.ok
            fields[name].total += tally.total
        for call in sample.calls:
            row = steps.setdefault((call.step, call.model), StepRow(step=call.step, model=call.model))
            cost = _price(run, call)
            row.calls += 1
            row.failed += int(not call.ok)
            row.prompt_tokens += call.prompt_tokens or 0
            row.completion_tokens += call.completion_tokens or 0
            row.latency_ms += call.latency_ms
            row.cost += cost or Decimal("0")
            s.unpriced_calls += int(cost is None)
    s.fields = dict(fields)
    s.steps = list(steps.values())
    for row in s.steps:
        s.calls += row.calls
        s.failed_calls += row.failed
        s.prompt_tokens += row.prompt_tokens
        s.completion_tokens += row.completion_tokens
        s.latency_ms += row.latency_ms
        s.cost += row.cost
    return s


# --- markdown ---------------------------------------------------------------------------------------------


def pct(tally_ok: int, total: int) -> str:
    return f"{tally_ok}/{total} ({tally_ok / total:.0%})" if total else "n/a"


def usd(value: Decimal) -> str:
    return f"${value:,.4f}"


def name(model: str) -> str:
    return NAMES.get(model, model)


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out)


def _listing(title: str, items: list[str]) -> str:
    return f"**{title}:** " + ("none" if not items else "; ".join(items))


def render_report(routed: Run | None, ultra: Run | None) -> str:
    runs = [(run, summarize(run)) for run in (routed, ultra) if run is not None]
    if not runs:
        raise ValueError("no run to report")
    sample_names = [sample.name for sample in runs[0][0].samples]
    out = [
        "# ClaimGuard eval",
        "",
        f"Every sample ({', '.join(sample_names)}) goes through the real pipeline on Nebius Token Factory: read, "
        "confirm the lines exactly as read (no human corrections), run the checks, review amber findings, write "
        "the letters. Expected results come from each `samples/*/expected_flags.json`, which is derived from the "
        "CMS data independently of the check code. `maya-photo` is Maya's bill as a phone-style photo, scored "
        "against the same expected lines. The hospital web lookup is not part of this eval.",
        "",
        "## Scorecard",
        "",
    ]
    columns = [LABEL[run.mode] for run, _ in runs]

    def row(label: str, value) -> list[str]:
        return [label, *[value(s, run) for run, s in runs]]

    base = runs[0][1]

    def multiple(s: Summary, run: Run) -> str:
        if run is runs[0][0]:
            return "1.0×"
        return f"{s.cost / base.cost:.1f}×" if base.cost else "n/a"

    rows = [
        row("Seeded errors caught / expected", lambda s, r: f"{s.caught} / {s.expected_errors}"),
        row("Amber flags Ultra moved to context", lambda s, r: str(s.downgraded)),
        row("Missed errors", lambda s, r: str(len(s.missed))),
        row("False Likely-error flags", lambda s, r: str(len(s.false_likely))),
        row("Likely-error totals correct", lambda s, r: f"{s.totals_ok} / {s.samples} samples"),
        row("Extraction accuracy (all fields)", lambda s, r: pct(s.extraction_ok, s.extraction_total)),
        row("Model calls (failed)", lambda s, r: f"{s.calls} ({s.failed_calls})"),
        row("Tokens in / out", lambda s, r: f"{s.prompt_tokens:,} / {s.completion_tokens:,}"),
        row("Model latency, all calls added up", lambda s, r: f"{s.latency_ms / 1000:.1f} s"),
        row("Wall-clock time, all samples", lambda s, r: f"{s.wall_seconds:.0f} s"),
        row("Estimated cost", lambda s, r: usd(s.cost)),
        row("Cost compared with routed", multiple),
    ]
    out += [table(["", *columns], rows), ""]
    if len(runs) == 1:
        other = "all_ultra" if runs[0][0].mode == "routed" else "routed"
        cmd = "python -m eval --all-ultra" if other == "all_ultra" else "python -m eval"
        out += [f"The {LABEL[other]} run is not in this report yet: run `{cmd}`.", ""]
    for run, s in runs:
        out += [f"**{LABEL[run.mode]}**, finished {run.finished_at}. " + " ".join(run.notes), ""]
        if s.errors:
            out += [f"**{LABEL[run.mode]}: documents that could not be read:** " + "; ".join(s.errors), ""]

    out += ["## Findings by sample", ""]
    for run, s in runs:
        out += [f"### {LABEL[run.mode]}", ""]
        rows = [
            [
                x.name, f"{x.findings.caught} / {x.findings.expected_errors}", str(x.findings.downgraded),
                str(len(x.findings.missed)), str(len(x.findings.false_likely)),
                f"{x.findings.context_found} / {x.findings.context_expected}",
                f"${x.findings.actual_total} (expected ${x.findings.expected_total})" + ("" if x.findings.total_ok else " ✗"),
                "yes" if x.findings.deadline_ok else "no",
            ]
            for x in run.samples
        ]
        out += [table(["Sample", "Errors caught", "Moved to context", "Missed", "False Likely errors", "Context notes", "Likely-error total", "Deadline right"], rows), ""]
        out += [_listing("Missed", s.missed), "", _listing("False Likely-error flags", s.false_likely), ""]
        out += [_listing("Other findings nobody expected", s.unexpected), ""]

    out += ["## Extraction accuracy", "", "Per field, over every line (and the bill header and EOB) of every sample. A line the reader missed counts every one of its fields wrong. The dose fields also count a dose invented where the bill states none.", ""]
    field_names = list(runs[0][1].fields)
    out += [table(["Field", *columns], [[f, *[pct(s.fields[f].ok, s.fields[f].total) if f in s.fields else "n/a" for _, s in runs]] for f in field_names]), ""]
    for run, _ in runs:
        rows = [
            [x.name, x.document, f"{x.lines_read} / {x.lines_expected}",
             pct(sum(t.ok for t in x.extraction.values()), sum(t.total for t in x.extraction.values()))]
            for x in run.samples
        ]
        out += [f"### By sample: {LABEL[run.mode]}", "", table(["Sample", "Document", "Lines read / expected", "Fields correct"], rows), ""]

    out += ["## Cost and latency by step", ""]
    for run, s in runs:
        rows = [
            [r.step, name(r.model), f"{r.calls} ({r.failed})", f"{r.prompt_tokens:,} / {r.completion_tokens:,}",
             f"{r.latency_ms / 1000:.1f} s", f"{r.latency_ms / r.calls / 1000:.1f} s", usd(r.cost)]
            for r in s.steps
        ]
        rows.append(["**Total**", "", f"{s.calls} ({s.failed_calls})", f"{s.prompt_tokens:,} / {s.completion_tokens:,}",
                     f"{s.latency_ms / 1000:.1f} s", "", usd(s.cost)])
        out += [f"### {LABEL[run.mode]}", "", table(["Step", "Model", "Calls (failed)", "Tokens in / out", "Latency, added up", "Mean per call", "Estimated cost"], rows), ""]
        if s.unpriced_calls:
            out += [f"{s.unpriced_calls} calls used a model with no listed price and count as $0.", ""]

    run0 = runs[0][0]
    out += [
        "## Prices used", "",
        "These are estimates: list prices times the token counts in the call log, with no cached-token discount, "
        "so a real bill can be lower. Source: " + run0.price_source + ".", "",
        table(["Model", "Model ID", "Input, per million tokens", "Output, per million tokens"],
              [[name(m), f"`{m}`", f"${Decimal(p['input']):,.2f}", f"${Decimal(p['output']):,.2f}"] for m, p in run0.prices.items()]),
        "",
        "## How to reproduce", "",
        "`python -m eval` runs the routed pipeline and `python -m eval --all-ultra` repeats it with Nemotron 3 Ultra "
        "on every step that can run on it. Each run is saved in `eval/runs/` and this file is rebuilt from both. "
        "Both need `NEBIUS_API_KEY` and spend Token Factory credit. Model outputs vary between runs, so numbers "
        "will differ slightly.",
        "",
    ]
    return "\n".join(out)
