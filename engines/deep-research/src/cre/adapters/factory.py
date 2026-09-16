"""Build runnable LLM adapters from a saved provider profile."""

from __future__ import annotations

from typing import Any
import uuid

from ..providers import get_provider, resolve_protocol
from .multi_protocol_llm import MultiProtocolLLM


def create_llm(config: dict[str, Any], model: str) -> MultiProtocolLLM:
    provider = get_provider(str(config["provider"]))
    extra_headers = {}
    if provider["id"] == "opencode-go":
        # OpenCode asks third-party agents to identify themselves and attach a
        # session id so its gateway can optimize prompt caching.
        extra_headers = {
            "User-Agent": "Continuous-Research-Engine/0.8.2",
            "x-opencode-session": uuid.uuid4().hex,
        }
    base_url = str(config.get("base_url") or provider["base_url"])
    return MultiProtocolLLM(
        base_url=base_url,
        api_key=str(config.get("api_key", "")),
        model=model,
        protocol=resolve_protocol(
            provider["id"], model, str(config.get("protocol", "auto"))
        ),
        auth_mode=str(config.get("auth_mode") or provider["auth_mode"]),
        timeout=float(config.get("timeout_seconds", 120)),
        query_params=dict(config.get("query_params") or provider["query_params"]),
        extra_headers=extra_headers,
        retry_attempts=7 if provider["id"] == "opencode-go" else 5,
        request_group=f"opencode-go:{base_url}" if provider["id"] == "opencode-go" else "",
        min_interval_seconds=2.0 if provider["id"] == "opencode-go" else 0.0,
        include_tool_choice=provider["id"] != "deepseek",
        # DeepSeek documents SSE keep-alive comments for long scheduling waits.
        # Streaming prevents its keep-alive traffic from being mistaken for an
        # invalid non-streaming HTTP chunk by the stdlib transport.
        use_streaming=provider["id"] == "deepseek",
        # The engine externalizes depth as durable argument, retrieval and
        # collision passes. DeepSeek V4 otherwise defaults to long thinking and
        # can consume the entire response before emitting a state action. Keep
        # these orchestration turns non-thinking; the proof process itself is
        # still multi-pass and inspectable.
        reasoning_effort="low" if provider["id"] == "deepseek" else "",
        thinking_mode="disabled" if provider["id"] == "deepseek" else "",
    )


def create_debate_llms(config: dict[str, Any]) -> tuple[MultiProtocolLLM, MultiProtocolLLM]:
    """Create isolated A/B clients; their runtime message histories remain separate."""

    return create_llm(config, str(config["model_a"])), create_llm(
        config, str(config["model_b"])
    )
