"""Every finding's wording must appear in docs/SPEC.md section 5, character for character.

The spec table holds the wording; `[N]`, `[M]`, `[dose]`, `[date]`, `$[X]` and `$[Y]` are its placeholders.
Wording for cases the table does not cover is listed separately below and must stay neutral.
"""

from pathlib import Path

import pytest

from app.checks import wording

SPEC = (Path(__file__).resolve().parent.parent / "docs" / "SPEC.md").read_text()


@pytest.mark.parametrize(
    "template, spec_form",
    [
        (wording.DUPLICATE, "This charge appears twice on the same date. Ask the billing office to confirm or remove it."),
        (
            wording.DOSE.format(dose="[dose]", expected="[N]", billed="[M]"),
            "Your bill says [dose], which is [N] billing units for this drug, but [M] units were charged.",
        ),
        (wording.UNITS.format(limit="[N]", billed="[M]"), "CMS normally allows at most [N] units of this per day. [M] were billed."),
        (wording.GFE_DISPUTE.format(deadline="[date]"), "You may be able to start a federal billing dispute. Deadline: [date]."),
        (wording.EOB_MISMATCH.format(billed="[X]", owed="[Y]"), "The hospital billed $[X], but your insurer's EOB says you owe $[Y]."),
        (
            wording.DRUG_BENCHMARK.format(multiple="[N]"),
            "Charged [N]× Medicare's payment limit for this drug. Not an error; useful when asking for a discount.",
        ),
        (wording.CODE_UNKNOWN, "Not in CMS's current HCPCS list."),
        (wording.CODE_NOT_CHECKED, "Not checked (CPT needs an AMA license)."),
    ],
)
def test_wording_is_exactly_the_spec_wording(template: str, spec_form: str) -> None:
    assert template == spec_form
    assert f'"{spec_form}"' in SPEC


def test_the_insured_wording_is_the_phrase_the_spec_asks_for() -> None:
    assert wording.BILLING_REVIEW == "Ask for a billing review."
    assert '"ask for a billing review,"' in SPEC  # SPEC section 4, Dev


NOT_IN_TABLE = ["DOSE_NEEDS_INTERPRETING", "CODE_VALID", "GFE_DEADLINE_UNKNOWN", "GFE_WINDOW_ENDED"]


def test_wording_outside_the_table_is_listed_here() -> None:
    texts = {k for k, v in vars(wording).items() if k.isupper() and isinstance(v, str)}
    in_table = {"DUPLICATE", "DOSE", "UNITS", "GFE_DISPUTE", "EOB_MISMATCH", "DRUG_BENCHMARK", "CODE_UNKNOWN", "CODE_NOT_CHECKED", "BILLING_REVIEW"}
    assert texts == in_table | set(NOT_IN_TABLE)


def test_no_wording_is_accusatory_or_ai_flavoured() -> None:
    texts = [v for k, v in vars(wording).items() if k.isupper() and isinstance(v, str)]
    for banned in ("illegal", "fraud", "red flag", "anomaly", "ai-powered", "overcharg"):
        assert not any(banned in text.lower() for text in texts), banned


def test_the_old_ncci_and_opps_wording_is_gone() -> None:
    for name in ("UNBUNDLED", "BENCHMARK", "PACKAGED"):
        assert not hasattr(wording, name)
