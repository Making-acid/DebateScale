"""Reference adapters."""

from .factory import create_debate_llms, create_llm
from .in_memory_store import InMemoryStore
from .json_file_store import JsonFileStore
from .multi_protocol_llm import MultiProtocolLLM
from .openai_like_llm import OpenAILikeLLM
from .web_search import DuckDuckGoSearch
from .local_asr import LocalASRTranscriber

__all__ = [
    "InMemoryStore", "JsonFileStore", "MultiProtocolLLM", "OpenAILikeLLM",
    "create_llm", "create_debate_llms", "DuckDuckGoSearch", "LocalASRTranscriber",
]
