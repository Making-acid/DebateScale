import sys
import io
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import MultiProtocolLLM, create_debate_llms
from cre.providers import provider_catalog, resolve_protocol


TOOLS = [{"type": "function", "function": {"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]


class TestProviderCatalog(unittest.TestCase):
    def test_reference_breadth_and_generic_entries(self):
        catalog = provider_catalog()
        self.assertGreaterEqual(len(catalog), 30)
        self.assertTrue({"opencode-go", "openai", "deepseek", "anthropic", "google-gemini", "mistral", "minimax", "azure-openai", "ollama", "generic-responses", "generic-chat", "generic-anthropic"}.issubset({item["id"] for item in catalog}))

    def test_deepseek_uses_the_first_party_api(self):
        provider = next(item for item in provider_catalog() if item["id"] == "deepseek")
        self.assertEqual(provider["base_url"], "https://api.deepseek.com")
        self.assertEqual(provider["default_model"], "deepseek-flash")
        self.assertEqual(provider["models"][0], "deepseek-flash")
        self.assertEqual(provider["protocol"], "openai_chat")

    def test_opencode_routes_each_protocol(self):
        self.assertEqual(resolve_protocol("opencode-go", "grok-4.6"), "openai_responses")
        self.assertEqual(resolve_protocol("opencode-go", "glm-5.3"), "openai_chat")
        self.assertEqual(resolve_protocol("opencode-go", "qwen3.8-max"), "anthropic_messages")
        provider = next(item for item in provider_catalog() if item["id"] == "opencode-go")
        self.assertEqual(provider["default_model"], "gpt-5.6-luna")
        self.assertGreaterEqual(len(provider["models"]), 28)

    def test_factory_creates_independent_clients(self):
        config = {"provider": "opencode-go", "base_url": "https://opencode.ai/zen/go/v1", "api_key": "x", "model_a": "grok-4.6", "model_b": "qwen3.8-max", "protocol": "auto"}
        a, b = create_debate_llms(config)
        self.assertIsNot(a, b)
        self.assertEqual(a.protocol, "openai_responses")
        self.assertEqual(b.protocol, "anthropic_messages")
        self.assertEqual(a.extra_headers["User-Agent"], "Continuous-Research-Engine/0.8.2")
        self.assertTrue(a.extra_headers["x-opencode-session"])
        self.assertEqual(a.request_group, b.request_group)
        self.assertGreater(a.min_interval_seconds, 0)

    def test_deepseek_factory_disables_private_long_thinking_for_tool_loop(self):
        config = {
            "provider": "deepseek", "api_key": "x",
            "model_a": "deepseek-v4-pro", "model_b": "deepseek-v4-pro",
            "protocol": "auto",
        }
        a, b = create_debate_llms(config)
        self.assertEqual(a.thinking_mode, "disabled")
        self.assertEqual(b.thinking_mode, "disabled")
        self.assertFalse(a.include_tool_choice)


class TestMultiProtocolLLM(unittest.IsolatedAsyncioTestCase):
    def test_chat_sse_assembles_keepalive_reasoning_and_tools(self):
        stream = io.BytesIO(
            b': keep-alive\n\n'
            b'data: {"choices":[{"delta":{"reasoning_content":"think "}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"search","arguments":"{\\"query\\":"}}]}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"x\\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
            b'data: [DONE]\n\n'
        )
        result = MultiProtocolLLM._read_chat_sse(stream)
        message = result["choices"][0]["message"]
        self.assertEqual(message["reasoning_content"], "think ")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], '{"query":"x"}')

    async def test_retries_transient_connection_errors(self):
        attempts, delays = [], []
        def requester(path, payload, headers):
            attempts.append(path)
            if len(attempts) < 3:
                raise urllib.error.URLError("temporary disconnect")
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}
        llm = MultiProtocolLLM(
            "https://x/v1", "key", "model", protocol="openai_responses",
            requester=requester, retry_attempts=3, sleeper=delays.append,
        )
        turn = await llm.run([{"role": "user", "content": "x"}], [])
        self.assertEqual(turn.text, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(delays), 2)

    async def test_responses_converts_tools_and_parses_call(self):
        seen = {}
        def requester(path, payload, headers):
            seen.update(path=path, payload=payload, headers=headers)
            return {"output": [{"type": "function_call", "call_id": "c1", "name": "search", "arguments": '{"query":"x"}'}, {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}], "usage": {"input_tokens": 10, "output_tokens": 3}}
        llm = MultiProtocolLLM("https://x/v1", "key", "model", protocol="openai_responses", requester=requester)
        turn = await llm.run([{"role": "system", "content": "s"}], TOOLS)
        self.assertEqual(seen["path"], "responses")
        self.assertEqual(seen["payload"]["tools"][0]["name"], "search")
        self.assertEqual(turn.text, "ok")
        self.assertEqual(turn.tool_calls[0].arguments, {"query": "x"})

    async def test_chat_preserves_provider_continuation_fields(self):
        seen = {}
        def requester(path, payload, headers):
            seen.update(payload=payload)
            return {
                "choices": [{"message": {
                    "content": "", "reasoning_content": "private continuation",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"query":"x"}'}}],
                }}],
                "usage": {},
            }
        llm = MultiProtocolLLM(
            "https://x", "key", "deepseek", protocol="openai_chat",
            requester=requester, include_tool_choice=False,
            reasoning_effort="low", thinking_mode="enabled",
        )
        turn = await llm.run([{"role": "user", "content": "x"}], TOOLS)
        self.assertEqual(turn.continuation["reasoning_content"], "private continuation")
        self.assertNotIn("tool_choice", seen["payload"])
        self.assertEqual(seen["payload"]["reasoning_effort"], "low")
        self.assertEqual(seen["payload"]["thinking"], {"type": "enabled"})

    async def test_anthropic_converts_tools_and_parses_call(self):
        seen = {}
        def requester(path, payload, headers):
            seen.update(path=path, payload=payload, headers=headers)
            return {"content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "t1", "name": "search", "input": {"query": "y"}}], "usage": {"input_tokens": 4, "output_tokens": 2}}
        llm = MultiProtocolLLM("https://x/v1", "key", "model", protocol="anthropic_messages", requester=requester)
        turn = await llm.run([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], TOOLS)
        self.assertEqual(seen["path"], "messages")
        self.assertEqual(seen["payload"]["system"], "s")
        self.assertEqual(seen["payload"]["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer key")
        self.assertIn("anthropic-version", seen["headers"])
        self.assertEqual(turn.tool_calls[0].arguments, {"query": "y"})


if __name__ == "__main__":
    unittest.main()
