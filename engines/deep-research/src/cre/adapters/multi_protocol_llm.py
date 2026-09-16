"""LLM adapter for OpenAI Chat, OpenAI Responses and Anthropic Messages."""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import random
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from ..ports.llm import LLMTurn, LLMUsage, ToolCall

Requester = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]

_REQUEST_GATES: dict[str, threading.Lock] = {}
_REQUEST_GATES_GUARD = threading.Lock()
_LAST_REQUEST_AT: dict[str, float] = {}


def _request_gate(name: str) -> threading.Lock:
    with _REQUEST_GATES_GUARD:
        return _REQUEST_GATES.setdefault(name, threading.Lock())


class MultiProtocolLLM:
    def __init__(self, base_url: str, api_key: str, model: str, *,
                 protocol: str = "openai_responses", auth_mode: str = "bearer",
                 timeout: float = 120.0, query_params: Optional[dict[str, str]] = None,
                 extra_headers: Optional[dict[str, str]] = None,
                 requester: Optional[Requester] = None,
                 retry_attempts: int = 6,
                 request_group: str = "",
                 min_interval_seconds: float = 0.0,
                 include_tool_choice: bool = True,
                 use_streaming: bool = False,
                 max_output_tokens: int = 12_000,
                 reasoning_effort: str = "",
                 thinking_mode: str = "",
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.protocol = protocol
        self.auth_mode = auth_mode
        self.timeout = timeout
        self.query_params = query_params or {}
        self.extra_headers = extra_headers or {}
        self._requester = requester
        self.retry_attempts = max(1, retry_attempts)
        self.request_group = request_group
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.include_tool_choice = include_tool_choice
        self.use_streaming = use_streaming
        self.max_output_tokens = max(512, int(max_output_tokens))
        self.reasoning_effort = reasoning_effort.strip()
        self.thinking_mode = thinking_mode.strip()
        self._sleeper = sleeper

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.auth_mode == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.api_key and self.auth_mode == "x-api-key":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.api_key and self.auth_mode == "api-key":
            headers["api-key"] = self.api_key
        if self.protocol == "anthropic_messages":
            headers.setdefault("anthropic-version", "2023-06-01")
        headers.update(self.extra_headers)
        return headers

    def _post_once(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        if self._requester is not None:
            return self._requester(path, payload, headers)
        if payload.get("stream"):
            headers["Accept"] = "text/event-stream"
        url = f"{self.base_url}/{path}"
        if self.query_params:
            url += "?" + urllib.parse.urlencode(self.query_params)
        request = urllib.request.Request(url, json.dumps(payload).encode("utf-8"), headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if payload.get("stream"):
                return self._read_chat_sse(response)
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _read_chat_sse(response) -> dict[str, Any]:
        """Assemble an OpenAI Chat SSE stream into the ordinary response shape.

        DeepSeek sends SSE keep-alive comments while a request is scheduled. Reading
        its long-running response as one non-streaming chunk can make Python's HTTP
        client treat an empty keep-alive line as a broken chunk boundary.
        """

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish_reason = None
        saw_data = False
        saw_done = False
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            saw_data = True
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            if delta.get("content") is not None:
                text_parts.append(str(delta["content"]))
            if delta.get("reasoning_content") is not None:
                reasoning_parts.append(str(delta["reasoning_content"]))
            for fragment in delta.get("tool_calls") or []:
                index = int(fragment.get("index", 0))
                current = calls.setdefault(index, {
                    "id": "", "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
                if fragment.get("id"):
                    current["id"] = str(fragment["id"])
                function = fragment.get("function") or {}
                if function.get("name"):
                    current["function"]["name"] += str(function["name"])
                if function.get("arguments"):
                    current["function"]["arguments"] += str(function["arguments"])
        if not saw_data:
            raise http.client.IncompleteRead(b"")
        if not saw_done and finish_reason is None:
            raise http.client.IncompleteRead("".join(text_parts).encode("utf-8"))
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(text_parts),
            "tool_calls": [calls[index] for index in sorted(calls)],
        }
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        return {
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": usage,
        }

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in {408, 409, 425, 429, 500, 502, 503, 504, 529}
        return isinstance(
            exc,
            (
                urllib.error.URLError,
                http.client.HTTPException,
                json.JSONDecodeError,
                ConnectionError,
                TimeoutError,
                OSError,
            ),
        )

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        if not isinstance(exc, urllib.error.HTTPError) or exc.headers is None:
            return None
        raw = exc.headers.get("Retry-After")
        try:
            return max(0.0, min(float(raw), 90.0)) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _wait_for_slot(self) -> None:
        if not self.request_group or not self.min_interval_seconds:
            return
        remaining = self.min_interval_seconds - (
            time.monotonic() - _LAST_REQUEST_AT.get(self.request_group, 0.0)
        )
        if remaining > 0:
            self._sleeper(remaining)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        gate = _request_gate(self.request_group) if self.request_group else contextlib.nullcontext()
        with gate:
            last_error: Exception | None = None
            started_at = time.monotonic()
            payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            for attempt in range(self.retry_attempts):
                self._wait_for_slot()
                if self.request_group:
                    _LAST_REQUEST_AT[self.request_group] = time.monotonic()
                try:
                    return self._post_once(path, payload)
                except Exception as exc:
                    last_error = exc
                    if attempt + 1 >= self.retry_attempts or not self._retryable(exc):
                        elapsed = time.monotonic() - started_at
                        raise ConnectionError(
                            "provider request failed; "
                            f"protocol={self.protocol}, model={self.model}, path={path}, "
                            f"attempts={attempt + 1}, payload_bytes={payload_bytes}, "
                            f"elapsed_seconds={elapsed:.1f}, "
                            f"cause={type(exc).__name__}: {str(exc)[:300]}"
                        ) from exc
                    server_delay = self._retry_after(exc)
                    backoff = min(30.0, 1.5 * (2 ** attempt)) + random.uniform(0.0, 0.5)
                    self._sleeper(server_delay if server_delay is not None else backoff)
            assert last_error is not None
            raise last_error

    @staticmethod
    def _args(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append({"type": "function", "name": fn.get("name", ""),
                           "description": fn.get("description", ""),
                           "parameters": fn.get("parameters", {"type": "object"})})
        return result

    @staticmethod
    def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                result.append({"type": "function_call_output", "call_id": message.get("tool_call_id", ""), "output": str(message.get("content", ""))})
                continue
            content = message.get("content")
            if content:
                result.append({"role": role, "content": content})
            for call in message.get("tool_calls") or []:
                fn = call.get("function", {})
                result.append({"type": "function_call", "call_id": call.get("id", ""), "name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")})
        return result

    @staticmethod
    def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"name": item.get("function", {}).get("name", ""),
                 "description": item.get("function", {}).get("description", ""),
                 "input_schema": item.get("function", {}).get("parameters", {"type": "object"})}
                for item in tools]

    @staticmethod
    def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        systems, result = [], []
        for message in messages:
            role = message.get("role")
            if role == "system":
                systems.append(str(message.get("content", "")))
                continue
            if role == "tool":
                converted = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": str(message.get("content", ""))}]}
            else:
                blocks = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": str(message["content"])})
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    blocks.append({"type": "tool_use", "id": call.get("id", ""), "name": fn.get("name", ""), "input": MultiProtocolLLM._args(fn.get("arguments"))})
                converted = {"role": "assistant" if role == "assistant" else "user", "content": blocks or [{"type": "text", "text": ""}]}
            if result and result[-1]["role"] == converted["role"]:
                result[-1]["content"].extend(converted["content"])
            else:
                result.append(converted)
        return "\n\n".join(systems), result

    async def run(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None) -> LLMTurn:
        tools = tools or []
        if self.protocol == "openai_chat":
            payload: dict[str, Any] = {
                "model": self.model, "messages": messages,
                "max_tokens": self.max_output_tokens,
            }
            if self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort
            if self.thinking_mode:
                payload["thinking"] = {"type": self.thinking_mode}
            if self.use_streaming:
                payload.update(stream=True, stream_options={"include_usage": True})
            if tools:
                payload["tools"] = tools
                if self.include_tool_choice:
                    payload["tool_choice"] = "auto"
            response = await asyncio.to_thread(self._post, "chat/completions", payload)
            message = response["choices"][0]["message"]
            calls = [ToolCall(str(tc.get("id", "")), str(tc.get("function", {}).get("name", "")), self._args(tc.get("function", {}).get("arguments"))) for tc in message.get("tool_calls") or [] if tc.get("type") == "function"]
            usage = response.get("usage") or {}
            continuation = {
                key: message[key]
                for key in ("reasoning_content", "reasoning_details")
                if message.get(key) is not None
            }
            return LLMTurn(
                str(message.get("content") or ""), calls,
                LLMUsage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
                continuation,
            )

        if self.protocol == "openai_responses":
            payload = {
                "model": self.model, "input": self._responses_input(messages),
                "max_output_tokens": self.max_output_tokens,
            }
            if tools:
                payload["tools"] = self._responses_tools(tools)
                if self.include_tool_choice:
                    payload["tool_choice"] = "auto"
            response = await asyncio.to_thread(self._post, "responses", payload)
            texts, calls = [], []
            for item in response.get("output") or []:
                if item.get("type") == "function_call":
                    calls.append(ToolCall(str(item.get("call_id") or item.get("id", "")), str(item.get("name", "")), self._args(item.get("arguments"))))
                for block in item.get("content") or []:
                    if block.get("type") in {"output_text", "text"}:
                        texts.append(str(block.get("text", "")))
            usage = response.get("usage") or {}
            return LLMTurn(str(response.get("output_text") or "\n".join(texts)), calls, LLMUsage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)))

        if self.protocol == "anthropic_messages":
            system, converted = self._anthropic_messages(messages)
            payload = {"model": self.model, "messages": converted, "max_tokens": self.max_output_tokens}
            if system:
                payload["system"] = system
            if tools:
                payload["tools"] = self._anthropic_tools(tools)
                if self.include_tool_choice:
                    payload["tool_choice"] = {"type": "auto"}
            response = await asyncio.to_thread(self._post, "messages", payload)
            texts, calls = [], []
            for block in response.get("content") or []:
                if block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    calls.append(ToolCall(str(block.get("id", "")), str(block.get("name", "")), self._args(block.get("input"))))
            usage = response.get("usage") or {}
            return LLMTurn("\n".join(texts), calls, LLMUsage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)))

        raise ValueError(f"unsupported protocol: {self.protocol}")
