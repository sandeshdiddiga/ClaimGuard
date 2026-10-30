"""Real Token Factory calls for the judge, scope gate and letters. Run with: pytest -m live"""

import os
import sqlite3
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.judge import judge_amber
from app.letters.render import build_letters
from app.llm import LLMClient
from app.safety import screen_question
from app.store import Store
from app.textguard import has_banned_term, numbers_not_in
from tests.builders import sample_audit
from tests.test_scope_redirect import OFF_TOPIC

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def require_key() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("NEBIUS_API_KEY"):
        pytest.skip("NEBIUS_API_KEY not set")


def test_nano_redirects_all_ten_off_topic_prompts(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    case_id = store.create_case("self_pay")
    llm = LLMClient(sink=store)
    missed = [p for p, _ in OFF_TOPIC if screen_question(llm, case_id, p).allowed]
    assert missed == []


def test_nano_lets_billing_questions_through(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    llm = LLMClient(sink=store)
    case_id = store.create_case("self_pay")
    assert screen_question(llm, case_id, "Why was line 3 on my bill flagged as a duplicate?").allowed


def test_ultra_judges_the_amber_units_finding_and_changes_nothing_else(ref: sqlite3.Connection, tmp_path: Path) -> None:
    _, _, result = sample_audit("maya", ref)
    store = Store(tmp_path / "state.db")
    case_id = store.create_case("self_pay")
    judged = judge_amber(LLMClient(sink=store), case_id, result.findings)
    (amber,) = [f for f in judged if f.judge_decision]
    assert amber.judge_decision in {"keep", "downgrade"} and amber.judge_reason
    for before, after in zip(result.findings, judged):
        if before.level != "amber":
            assert after == before
    assert [c.step for c in store.calls(case_id)] == ["judge_amber"]


def test_super_letters_pass_the_figure_and_wording_checks(ref: sqlite3.Connection, tmp_path: Path) -> None:
    sample, _, result = sample_audit("maya", ref)
    store = Store(tmp_path / "state.db")
    case_id = store.create_case("self_pay")
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=LLMClient(sink=store), case_id=case_id)
    assert len(letters) == 2
    for letter in letters:
        assert not has_banned_term(letter.text)
        assert letter.text.rstrip().endswith("Prepared with ClaimGuard. This is not legal advice.")
    assert [c.step for c in store.calls(case_id)].count("draft_letter") == 2
