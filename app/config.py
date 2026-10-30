"""Model IDs and routing. The only place a model ID may appear (see CLAUDE.md).

Fill MODEL_IDS from `python -m scripts.list_models nemotron`. An environment variable MODEL_<ROLE> overrides
the value here, which tests and the "Ultra for everything" eval comparison use.
"""

import os
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class Role(StrEnum):
    READER = "reader"  # Nemotron 3.5 Super VL: reads bill and EOB images and PDFs
    CLEANER = "cleaner"  # Nemotron 3 Nano: cleans codes, scope gate
    JUDGE = "judge"  # Nemotron 3 Ultra: reviews amber units and dose findings only
    WRITER = "writer"  # Nemotron 3 Super: explanations and letter paragraphs


class Step(StrEnum):
    READ_DOCUMENT = "read_document"
    CLEAN_CODES = "clean_codes"
    JUDGE_AMBER = "judge_amber"
    EXPLAIN = "explain"
    DRAFT_LETTER = "draft_letter"
    PICK_LINKS = "pick_links"
    SEARCH_WEB = "search_web"  # a Tavily search, not a model call: it has no entry in ROUTING


ROUTING: dict[Step, Role] = {
    Step.READ_DOCUMENT: Role.READER,
    Step.CLEAN_CODES: Role.CLEANER,
    Step.JUDGE_AMBER: Role.JUDGE,
    Step.EXPLAIN: Role.WRITER,
    Step.DRAFT_LETTER: Role.WRITER,
    Step.PICK_LINKS: Role.WRITER,
}

# From `python -m scripts.list_models nemotron`. The Super VL model is the only vision model listed.
MODEL_IDS: dict[Role, str] = {
    Role.READER: "nvidia/Nemotron-3.5-Super-VL",
    Role.CLEANER: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    Role.JUDGE: "nvidia/Nemotron-3-Ultra-550b-a55b",
    Role.WRITER: "nvidia/nemotron-3-super-120b-a12b",
}


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: Decimal
    output: Decimal


# Token Factory list prices, read from the `pricing` field of GET /v1/models (prompt and completion, USD per token,
# multiplied by one million) on 2026-10-30. The eval's cost figures are estimates: they use these list prices and
# apply no cached-token discount. Re-read the endpoint before quoting them; prices change.
PRICE_SOURCE = "Nebius Token Factory GET /v1/models, pricing.prompt and pricing.completion, read 2026-10-30"
PRICES: dict[str, Price] = {
    MODEL_IDS[Role.READER]: Price(Decimal("0.30"), Decimal("0.90")),
    MODEL_IDS[Role.CLEANER]: Price(Decimal("0.06"), Decimal("0.24")),
    MODEL_IDS[Role.JUDGE]: Price(Decimal("1.00"), Decimal("3.00")),
    MODEL_IDS[Role.WRITER]: Price(Decimal("0.30"), Decimal("0.90")),
}


def cost_usd(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> Decimal | None:
    """Estimated cost of one call, or None when the model has no listed price."""
    price = PRICES.get(model)
    if price is None:
        return None
    return (price.input * (prompt_tokens or 0) + price.output * (completion_tokens or 0)) / Decimal(1_000_000)


class ConfigError(RuntimeError):
    pass


def model_for(step: Step) -> str:
    role = ROUTING[step]
    model = os.environ.get(f"MODEL_{role.name}") or MODEL_IDS[role]
    if not model:
        raise ConfigError(
            f"no model ID for {role.value} (step {step.value}): "
            f"run `python -m scripts.list_models nemotron`, then set MODEL_IDS in app/config.py"
        )
    return model
