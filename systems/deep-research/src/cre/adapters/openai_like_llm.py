"""OpenAI-compatible LLM adapter.

Talks to any endpoint exposing an OpenAI-style ``/chat/completions`` API
(OpenAI, DeepSeek, vLLM, Ollama, etc.) using only the standard library, so the
engine stays dependency-free. Inject a ``requester`` to test without network.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Optional

from ..ports.llm import LLMTurn, LLMUsage, ToolCall

Requester = Callable[[dict[str, Any]], dict[str, Any]]


class OpenAILikeLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        requester: Optional[Requester] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._requester = requester

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._requester is not None:
            return self._requester(payload)
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def run(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMTurn:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = self._post(payload)
        msg = resp["choices"][0]["message"]
        text = msg.get("content") or ""

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            if tc.get("type") != "function":
                continue
            fn = tc["function"]
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args)
            )

        usage_data = resp.get("usage") or {}
        usage = LLMUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )
        return LLMTurn(text=text, tool_calls=tool_calls, usage=usage)
