import json
import logging

import pytest
from pydantic import BaseModel

from app import config
from app.config import ConfigError, Step, model_for
from app.llm import LLMClient, LLMError, extract_json, image_part
from tests.fakes import FakeOpenAI, ListSink


class Answer(BaseModel):
    value: int


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


def make(replies: list) -> tuple[LLMClient, FakeOpenAI, ListSink]:
    fake, sink = FakeOpenAI(replies), ListSink()
    return LLMClient(sink=sink, client=fake), fake, sink


def test_each_step_uses_its_routed_model() -> None:
    assert model_for(Step.READ_DOCUMENT) == "test/reader"
    assert model_for(Step.CLEAN_CODES) == "test/cleaner"
    assert model_for(Step.JUDGE_AMBER) == "test/judge"
    assert model_for(Step.EXPLAIN) == model_for(Step.DRAFT_LETTER) == "test/writer"


def test_missing_model_id_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_JUDGE")
    monkeypatch.setitem(config.MODEL_IDS, config.Role.JUDGE, "")
    with pytest.raises(ConfigError, match="list_models"):
        model_for(Step.JUDGE_AMBER)


def test_success_records_model_latency_and_tokens() -> None:
    client, fake, sink = make(['{"value": 3}'])
    assert client.complete_json(Step.CLEAN_CODES, [{"role": "user", "content": "x"}], Answer, case_id="c1") == Answer(value=3)
    (case_id, record), = sink.records
    assert case_id == "c1"
    assert (record.step, record.model, record.ok, record.error) == ("clean_codes", "test/cleaner", True, None)
    assert (record.prompt_tokens, record.completion_tokens) == (11, 7)
    assert record.latency_ms >= 0
    assert fake.completions.requests[0]["model"] == "test/cleaner"
    assert fake.completions.requests[0]["temperature"] == 0


def test_invalid_json_retries_once_then_succeeds() -> None:
    client, fake, sink = make(["not json at all", '{"value": 5}'])
    assert client.complete_json(Step.CLEAN_CODES, [{"role": "user", "content": "x"}], Answer, case_id="c").value == 5
    assert [r.ok for _, r in sink.records] == [False, True]  # both attempts are logged: both cost tokens
    assert sink.records[0][1].error == "invalid_json"
    assert len(fake.completions.requests) == 2


def test_two_invalid_replies_raise() -> None:
    client, _, sink = make(["nope", '{"value": "abc"}'])
    with pytest.raises(LLMError, match="invalid_json after retry"):
        client.complete_json(Step.CLEAN_CODES, [{"role": "user", "content": "x"}], Answer, case_id="c")
    assert len(sink.records) == 2


def test_api_failure_is_recorded_without_the_message() -> None:
    client, _, sink = make([ConnectionError("secret patient text in an error body")])
    with pytest.raises(LLMError) as raised:
        client.complete_text(Step.EXPLAIN, [{"role": "user", "content": "x"}], case_id="c")
    assert "secret" not in str(raised.value)
    (_, record), = sink.records
    assert (record.ok, record.error, record.prompt_tokens) == (False, "ConnectionError", None)


def test_content_never_reaches_records_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    secret = "PATIENT-NAME-Maya-Okafor-ACCT-123"
    client, _, sink = make([json.dumps({"value": 1, "echo": secret})])
    with caplog.at_level(logging.DEBUG):
        client.complete_json(Step.CLEAN_CODES, [{"role": "user", "content": secret}], Answer, case_id="c")
    assert secret not in repr(sink.records)
    assert secret not in caplog.text


def test_missing_api_key_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY"):
        LLMClient().complete_text(Step.EXPLAIN, [], case_id="c")


@pytest.mark.parametrize(
    "reply",
    [
        '{"value": 2}',
        '```json\n{"value": 2}\n```',
        '<think>reasoning {with braces}</think>\n{"value": 2}',
        'Sure! Here you go: {"value": 2} Hope that helps.',
    ],
)
def test_extract_json_tolerates_wrappers(reply: str) -> None:
    assert extract_json(reply) == {"value": 2}


def test_extract_json_rejects_text_without_an_object() -> None:
    with pytest.raises(ValueError):
        extract_json("no braces here")


def test_text_replies_drop_reasoning_blocks() -> None:
    client, _, _ = make(["<think>hidden</think>Plain answer."])
    assert client.complete_text(Step.EXPLAIN, [], case_id="c") == "Plain answer."


def test_image_part_is_a_base64_data_url() -> None:
    part = image_part(b"\x89PNGdata")
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
