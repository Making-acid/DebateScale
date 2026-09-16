"""Hard budget tracking for a single Research Pass (mechanical ceiling)."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ResearchBudget
from ..ports.llm import LLMUsage


@dataclass
class PassUsage:
    model_turns: int = 0
    # Successful external research actions (search/read/custom tools).
    tool_calls: int = 0
    failed_tool_calls: int = 0
    argument_discovery_searches: int = 0
    exact_motion_searches: int = 0
    fact_verification_searches: int = 0
    source_reads: int = 0
    audio_transcriptions: int = 0
    # Local durable mutations are visible for audit but do not spend research
    # allowance: they are emitted inside an already-paid model response.
    state_actions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    # Approximate size of the prompt that is about to be sent.  This is kept
    # separate from provider-reported cumulative token usage so operators can
    # distinguish a large current context from a long, but well-compacted pass.
    current_context_chars: int = 0
    estimated_context_tokens: int = 0
    context_compactions: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class PassBudget:
    """Tracks a pass's usage against hard caps. Semantic decisions stay with the
    agent; this only enforces mechanical ceilings."""

    def __init__(self, limits: ResearchBudget):
        self._limits = limits
        self.usage = PassUsage()

    def record_tokens(self, usage: LLMUsage) -> None:
        self.usage.input_tokens += usage.input_tokens
        self.usage.output_tokens += usage.output_tokens
        self.usage.last_input_tokens = usage.input_tokens
        self.usage.last_output_tokens = usage.output_tokens

    def record_model_turn(self) -> None:
        self.usage.model_turns += 1

    def record_tool_call(
        self, *, success: bool = True, kind: str = "", mode: str = "",
        discovery_kind: str = "",
    ) -> None:
        if kind == "search" and mode == "argument_discovery":
            self.usage.argument_discovery_searches += 1
            if discovery_kind == "exact_motion":
                self.usage.exact_motion_searches += 1
        elif kind == "search" and mode == "fact_verification":
            self.usage.fact_verification_searches += 1
        elif kind == "read_source":
            self.usage.source_reads += 1
        elif kind == "transcribe_source" and success:
            self.usage.audio_transcriptions += 1
        if success:
            self.usage.tool_calls += 1
        else:
            self.usage.failed_tool_calls += 1

    def record_state_action(self) -> None:
        self.usage.state_actions += 1

    def record_context(self, chars: int, *, compacted: bool = False) -> None:
        self.usage.current_context_chars = max(0, int(chars))
        # Chinese and JSON/tool syntax make a precise tokenizer-dependent count
        # impossible here.  A conservative 2 chars/token is more useful than
        # pretending this is the provider's exact tokenizer.
        self.usage.estimated_context_tokens = (self.usage.current_context_chars + 1) // 2
        if compacted:
            self.usage.context_compactions += 1

    @property
    def research_exhausted(self) -> bool:
        return (
            self.usage.tool_calls >= self._limits.max_tool_calls_per_pass
            or self.usage.failed_tool_calls
            >= self._limits.max_failed_tool_calls_per_pass
        )

    def snapshot(self) -> dict[str, int | bool]:
        return {
            "model_turns": self.usage.model_turns,
            "model_turn_limit": self._limits.max_model_turns_per_pass,
            "research_calls": self.usage.tool_calls,
            "research_call_limit": self._limits.max_tool_calls_per_pass,
            "failed_calls": self.usage.failed_tool_calls,
            "failed_call_limit": self._limits.max_failed_tool_calls_per_pass,
            "state_actions": self.usage.state_actions,
            "argument_discovery_searches": self.usage.argument_discovery_searches,
            "exact_motion_searches": self.usage.exact_motion_searches,
            "fact_verification_searches": self.usage.fact_verification_searches,
            "source_reads": self.usage.source_reads,
            "audio_transcriptions": self.usage.audio_transcriptions,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "last_input_tokens": self.usage.last_input_tokens,
            "last_output_tokens": self.usage.last_output_tokens,
            "tokens": self.usage.total_tokens,
            "token_limit": self._limits.max_tokens_per_pass,
            "next_turn_reserve": self._limits.min_token_reserve_per_model_turn,
            "current_context_chars": self.usage.current_context_chars,
            "estimated_context_tokens": self.usage.estimated_context_tokens,
            "context_compactions": self.usage.context_compactions,
            "research_exhausted": self.research_exhausted,
        }

    @property
    def exhausted(self) -> bool:
        if self.usage.model_turns >= self._limits.max_model_turns_per_pass:
            return True
        if self.usage.total_tokens >= self._limits.max_tokens_per_pass:
            return True
        return False
