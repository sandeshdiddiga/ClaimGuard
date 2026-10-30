"""The single Token Factory client. Every model call in the app goes through here (see CLAUDE.md).

Each attempt is recorded with model, latency and token counts. Message content, replies and exception
messages are never recorded or logged: bills contain personal details.
"""

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import BASE_URL, ConfigError, Step, model_for

# The openai SDK and httpx log request bodies (our prompts, which hold bill text) at DEBUG level.
for _name in ("openai", "httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

T = TypeVar("T", bound=BaseModel)

Messages = list[dict[str, Any]]


@dataclass(frozen=True)
class CallRecord:
    step: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    ok: bool
    error: str | None = None  # exception class name or "invalid_json"; never a message


class CallSink(Protocol):
    def record_call(self, case_id: str, record: CallRecord) -> None: ...


class LLMError(RuntimeError):
    """A model call failed. The message names the step and error type only."""


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse the JSON object in a model reply, tolerating reasoning blocks and code fences."""
    text = _THINK.sub("", text).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def image_part(png_bytes: bytes, mime: str = "image/png") -> dict[str, Any]:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


class LLMClient:
    def __init__(self, sink: CallSink | None = None, client: OpenAI | None = None) -> None:
        self._sink = sink
        self._client = client

    def _openai(self) -> OpenAI:
        if self._client is None:
            key = os.environ.get("NEBIUS_API_KEY")
            if not key:
                raise ConfigError("NEBIUS_API_KEY is not set (see .env.example)")
            self._client = OpenAI(base_url=BASE_URL, api_key=key, timeout=90, max_retries=2)
        return self._client

    def _record(self, case_id: str, record: CallRecord) -> None:
        if self._sink is not None:
            self._sink.record_call(case_id, record)

    def _request(self, step: Step, messages: Messages, case_id: str) -> tuple[str, str, int, Any]:
        model = model_for(step)
        started = time.perf_counter()
        try:
            response = self._openai().chat.completions.create(
                model=model, messages=messages, temperature=0
            )
        except ConfigError:
            raise
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000)
            self._record(case_id, CallRecord(step.value, model, latency, None, None, False, type(exc).__name__))
            raise LLMError(f"{step.value}: {type(exc).__name__}") from None
        latency = round((time.perf_counter() - started) * 1000)
        return response.choices[0].message.content or "", model, latency, response.usage

    def _usage(self, usage: Any) -> tuple[int | None, int | None]:
        if usage is None:
            return None, None
        return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)

    def complete_text(self, step: Step, messages: Messages, *, case_id: str) -> str:
        text, model, latency, usage = self._request(step, messages, case_id)
        prompt, completion = self._usage(usage)
        self._record(case_id, CallRecord(step.value, model, latency, prompt, completion, True))
        return _THINK.sub("", text).strip()

    def complete_json(self, step: Step, messages: Messages, schema: type[T], *, case_id: str) -> T:
        """Ask for JSON matching `schema`; one retry if the reply does not parse or validate."""
        instruction = (
            "Reply with only a JSON object matching this JSON Schema, no other text:\n"
            + json.dumps(schema.model_json_schema())
        )
        attempt_messages = [{"role": "system", "content": instruction}, *messages]
        for attempt in (1, 2):
            text, model, latency, usage = self._request(step, attempt_messages, case_id)
            prompt, completion = self._usage(usage)
            try:
                parsed = schema.model_validate(extract_json(text))
            except (ValueError, ValidationError):
                self._record(
                    case_id, CallRecord(step.value, model, latency, prompt, completion, False, "invalid_json")
                )
                if attempt == 2:
                    raise LLMError(f"{step.value}: invalid_json after retry") from None
                attempt_messages = [
                    *attempt_messages,
                    {"role": "user", "content": "That was not valid JSON for the schema. Reply with only the JSON object."},
                ]
                continue
            self._record(case_id, CallRecord(step.value, model, latency, prompt, completion, True))
            return parsed
        raise AssertionError("unreachable")
