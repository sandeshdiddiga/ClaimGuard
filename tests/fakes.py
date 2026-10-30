"""A stand-in for the OpenAI SDK client: replays canned replies and remembers what it was sent."""

from types import SimpleNamespace
from typing import Any

from app.llm import CallRecord


class FakeCompletions:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )


class FakeOpenAI:
    def __init__(self, replies: list[Any]) -> None:
        self.completions = FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)


class ListSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, CallRecord]] = []

    def record_call(self, case_id: str, record: CallRecord) -> None:
        self.records.append((case_id, record))
