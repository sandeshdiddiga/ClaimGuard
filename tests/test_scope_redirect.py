"""Nano's scope gate: diagnosis, treatment and legal-advice questions get a fixed redirect."""

import json

import pytest

from app.safety import ScopeDecision, screen_question
from app.textguard import has_banned_term
from tests.fakes import FakeOpenAI, ListSink
from app.llm import LLMClient

OFF_TOPIC = [
    ("Do I have diabetes? My glucose was 180.", "medical_advice"),
    ("Which medication should I take for this chest pain?", "medical_advice"),
    ("Is this lump on my arm cancer?", "medical_advice"),
    ("Should I skip my surgery to save money?", "medical_advice"),
    ("What dose of ibuprofen is safe for a child?", "medical_advice"),
    ("Can I sue the hospital for this bill?", "legal_advice"),
    ("Is the hospital breaking the law? Which statute applies?", "legal_advice"),
    ("Write me a lawsuit complaint against the billing office.", "legal_advice"),
    ("What's a good recipe for banana bread?", "off_topic"),
    ("Who won the football game last night?", "off_topic"),
]


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


def llm_with(replies: list) -> tuple[LLMClient, FakeOpenAI, ListSink]:
    fake, sink = FakeOpenAI(replies), ListSink()
    return LLMClient(sink=sink, client=fake), fake, sink


def reply(category: str) -> str:
    return json.dumps({"category": category})


def test_ten_off_topic_prompts_are_redirected() -> None:
    for prompt, category in OFF_TOPIC:
        llm, _, _ = llm_with([reply(category)])
        decision = screen_question(llm, "c1", prompt)
        assert decision.allowed is False, prompt
        assert decision.message and not has_banned_term(decision.message)
    assert len(OFF_TOPIC) == 10


def test_a_billing_question_goes_through() -> None:
    llm, _, _ = llm_with([reply("billing")])
    assert screen_question(llm, "c1", "Why is line 3 flagged?") == ScopeDecision(allowed=True, message=None)


def test_the_redirect_text_is_fixed_not_written_by_the_model() -> None:
    llm, _, _ = llm_with([json.dumps({"category": "medical_advice", "message": "Take two aspirin."})])
    decision = screen_question(llm, "c1", "What should I take?")
    assert "aspirin" not in (decision.message or "")
    assert "medical" in decision.message.lower()


def test_each_category_has_its_own_redirect() -> None:
    messages = set()
    for category in ("medical_advice", "legal_advice", "off_topic"):
        llm, _, _ = llm_with([reply(category)])
        messages.add(screen_question(llm, "c1", "x").message)
    assert len(messages) == 3


def test_an_unusable_answer_fails_closed() -> None:
    llm, _, _ = llm_with(["not json", "still not json"])
    decision = screen_question(llm, "c1", "anything")
    assert decision.allowed is False and decision.message


def test_a_failed_call_fails_closed() -> None:
    llm, _, _ = llm_with([RuntimeError("down")])
    assert screen_question(llm, "c1", "anything").allowed is False


def test_the_question_is_truncated_and_never_logged() -> None:
    llm, fake, sink = llm_with([reply("billing")])
    screen_question(llm, "c1", "Jane Q. Patient asks " + "x" * 5000)
    sent = json.dumps(fake.completions.requests[0]["messages"])
    assert len(sent) < 2500
    (_, record), = sink.records
    assert record.step == "clean_codes" and "Jane" not in repr(record)
