import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import OpenAILikeLLM


def fake_requester(payload: dict) -> dict:
    # echoes the requested model and tool names; returns one fake tool call
    tool_name = payload["tools"][0]["function"]["name"] if payload.get("tools") else None
    message = {"content": "thinking..."}
    if tool_name:
        message["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": '{"title": "x", "importance": "high"}',
                },
            }
        ]
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }


class TestOpenAILikeLLM(unittest.IsolatedAsyncioTestCase):
    async def test_parses_tool_call_and_usage(self):
        llm = OpenAILikeLLM(
            base_url="https://api.example.com/v1",
            api_key="sk-test",
            model="gpt-test",
            requester=fake_requester,
        )
        turn = await llm.run(
            [{"role": "system", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "update_map"}}],
        )
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].name, "update_map")
        self.assertEqual(turn.tool_calls[0].arguments["importance"], "high")
        self.assertEqual(turn.usage.input_tokens, 12)
        self.assertEqual(turn.usage.output_tokens, 7)

    async def test_no_tools_returns_text_only(self):
        llm = OpenAILikeLLM("https://x", "k", "m", requester=fake_requester)
        turn = await llm.run([{"role": "system", "content": "x"}])
        self.assertEqual(turn.text, "thinking...")
        self.assertEqual(turn.tool_calls, [])


if __name__ == "__main__":
    unittest.main()
