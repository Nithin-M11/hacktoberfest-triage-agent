"""OpenAI-compatible LLM client with one JSON repair retry."""

from __future__ import annotations

import json
import os
import openai

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "240"))
TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
_client: openai.OpenAI | None = None


def client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=BASE_URL,
            api_key=os.environ.get("LLM_API_KEY", "local"),
            timeout=TIMEOUT,
            max_retries=1,
        )
    return _client


def _create(messages: list[dict], json_mode: bool = True) -> str:
    kwargs: dict = {"model": MODEL, "messages": messages, "temperature": TEMPERATURE}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _complete(messages: list[dict]) -> tuple[str | None, str | None]:
    try:
        return _create(messages, json_mode=True), None
    except openai.BadRequestError:
        try:
            return _create(messages, json_mode=False), None
        except openai.OpenAIError as exc:
            return None, f"{type(exc).__name__}: {exc}"
    except openai.OpenAIError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def chat_json(messages: list[dict]) -> dict | None:
    raw, error = _complete(messages)
    if error:
        return {"__transport_error__": error}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    repair = messages + [
        {"role": "assistant", "content": raw or ""},
        {"role": "user", "content": "That was not valid JSON. Output ONLY the corrected JSON object."},
    ]
    raw2, error2 = _complete(repair)
    if error2:
        return {"__transport_error__": error2}
    try:
        return json.loads(raw2)
    except (json.JSONDecodeError, TypeError):
        return None
