"""Built-in model-provider presets and protocol routing.

The catalog is deliberately data-only.  A preset means that CRE knows how to
address and authenticate the provider; live model availability is still checked
against the provider because commercial catalogs change frequently.
"""

from __future__ import annotations

from copy import deepcopy


_OPENCODE_PROTOCOLS = {
    # OpenAI Responses
    "grok-4.6": "openai_responses",
    "gpt-5.6-luna": "openai_responses",
    "muse-spark-1.3-contributor": "openai_responses",
    "muse-spark-1.2-contributor": "openai_responses",
    # Anthropic Messages
    "minimax-m3": "anthropic_messages",
    "minimax-m2.7": "anthropic_messages",
    "minimax-m2.5": "anthropic_messages",
    "qwen3.8-max": "anthropic_messages",
    "qwen3.8-flash": "anthropic_messages",
    "qwen3.7-max": "anthropic_messages",
    "qwen3.7-plus": "anthropic_messages",
    "qwen3.6-plus": "anthropic_messages",
}

_OPENCODE_CHAT_MODELS = [
    "glm-5.3-flash", "glm-5.3", "glm-5.2", "glm-5.1", "kimi-k3",
    "kimi-k2.7-code", "kimi-k2.6", "longcat-2.0", "deepseek-v4-pro",
    "deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "mimo-v2.5",
    "mimo-v2.5-pro", "hy4-preview", "hy3", "omen-alpha",
]
for _model in _OPENCODE_CHAT_MODELS:
    _OPENCODE_PROTOCOLS[_model] = "openai_chat"

_OPENCODE_MODELS = [
    "gpt-5.6-luna", "glm-5.3-flash", "qwen3.8-flash", "mimo-v2.5",
    "longcat-2.0", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor",
    "minimax-m3", "minimax-m2.7", "minimax-m2.5", "qwen3.7-plus",
    "qwen3.6-plus", "mimo-v2.5-pro", "kimi-k2.7-code", "kimi-k2.6",
    "deepseek-v4-flash", "hy3", "omen-alpha", "glm-5.3", "glm-5.2",
    "glm-5.1", "kimi-k3", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp",
    "qwen3.8-max", "qwen3.7-max", "hy4-preview", "grok-4.6",
]

_OPENCODE_MODEL_NOTES = {
    "gpt-5.6-luna": "推荐：能力与消耗较均衡",
    "glm-5.3-flash": "低成本：适合长流程试跑",
    "qwen3.8-flash": "低成本：长流程候选",
    "mimo-v2.5": "超低成本：适合调试，复杂论证能力较弱",
    "longcat-2.0": "超低成本",
    "muse-spark-1.3-contributor": "超低成本：提示可能用于训练",
    "muse-spark-1.2-contributor": "超低成本：提示可能用于训练",
    "grok-4.6": "高消耗：不建议用于反复试跑",
    "kimi-k3": "高消耗",
    "qwen3.8-max": "高消耗",
    "qwen3.7-max": "高消耗",
}


def _provider(
    provider_id: str,
    name: str,
    base_url: str,
    default_model: str,
    models: list[str],
    *,
    protocol: str = "openai_responses",
    auth_mode: str = "bearer",
    notes: str = "",
    query_params: dict[str, str] | None = None,
    requires_base_url: bool = False,
    model_protocols: dict[str, str] | None = None,
    model_notes: dict[str, str] | None = None,
) -> dict:
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "default_model": default_model,
        "models": models,
        "protocol": protocol,
        "auth_mode": auth_mode,
        "notes": notes,
        "query_params": query_params or {},
        "requires_base_url": requires_base_url,
        "model_protocols": model_protocols or {},
        "model_notes": model_notes or {},
    }


# First-party APIs are listed before subscription gateways and aggregators so a
# user with a model company's own key never has to route through a middleman.
# ChatGPT subscription OAuth is intentionally not counted as an API-key provider;
# it needs a separate interactive OAuth integration.
PROVIDERS = [
    _provider("openai", "OpenAI 官方", "https://api.openai.com/v1", "gpt-5.6", ["gpt-5.6", "gpt-5.4", "gpt-5.2", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-4.1"]),
    _provider(
        "deepseek", "DeepSeek 官方 API", "https://api.deepseek.com",
        "deepseek-flash",
        ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"],
        protocol="openai_chat",
        notes="DeepSeek 第一方按量 API；保存密钥后会从官方 /models 接口读取你账号可用的完整目录。",
        model_notes={
            "deepseek-flash": "推荐：最新 V4.1 Flash，速度快、成本低，适合长流程研究",
            "deepseek-v4-pro": "旧入口：官方已临时路由至 V4.1 Flash",
            "deepseek-v4-flash": "兼容入口：官方临时路由至 V4.1 Flash",
            "deepseek-v4-flash-vision-exp": "已退役的兼容入口；请优先使用 deepseek-flash",
        },
    ),
    _provider(
        "anthropic", "Anthropic Claude 官方 API", "https://api.anthropic.com/v1",
        "claude-sonnet-5",
        ["claude-sonnet-5", "claude-opus-5", "claude-fable-5", "claude-haiku-4-5-20251001"],
        protocol="anthropic_messages", auth_mode="x-api-key",
        notes="Anthropic 第一方 Messages API；模型目录按当前 API key 实时读取。",
    ),
    _provider(
        "google-gemini", "Google Gemini 官方 API", "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.8-flash",
        ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-pro"],
        protocol="openai_chat",
        notes="Google 官方 OpenAI 兼容入口；使用 Gemini API key，并实时读取账号模型目录。",
    ),
    _provider(
        "mistral", "Mistral AI 官方 API", "https://api.mistral.ai/v1",
        "mistral-medium-latest",
        ["mistral-medium-latest", "mistral-large-latest", "mistral-small-latest", "magistral-medium-latest", "magistral-small-latest"],
        protocol="openai_chat",
        notes="Mistral 第一方 API；保存后从官方模型管理接口读取完整可用目录。",
    ),
    _provider(
        "minimax", "MiniMax 官方 API（中国区）", "https://api.minimaxi.com/v1",
        "MiniMax-M2.7",
        ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"],
        protocol="openai_chat",
        notes="MiniMax 中国区第一方 OpenAI 兼容 API；Token Plan Key 与按量付费 API Key 均可按官方权限使用。",
    ),
    _provider("opencode-go", "OpenCode Go 订阅", "https://opencode.ai/zen/go/v1", "gpt-5.6-luna", _OPENCODE_MODELS, protocol="auto", model_protocols=_OPENCODE_PROTOCOLS, model_notes=_OPENCODE_MODEL_NOTES, notes="提供完整模型目录；默认使用较适合长流程的 GPT-5.6 Luna，并按模型自动切换接口协议。"),
    _provider("azure-openai", "Azure OpenAI", "", "gpt-5.6", ["gpt-5.6", "gpt-5.4", "gpt-5.2", "gpt-4.1"], auth_mode="api-key", query_params={"api-version": "2025-06-01-preview"}, requires_base_url=True),
    _provider("amazon-bedrock", "AWS Bedrock（OpenAI 模型）", "", "openai.gpt-5.5", ["openai.gpt-5.6-sol", "openai.gpt-5.6-terra", "openai.gpt-5.6-luna", "openai.gpt-5.5", "openai.gpt-5.4"], requires_base_url=True),
    _provider("dashscope", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-coder-plus", ["qwen3-coder-plus", "qwen3-coder-flash", "qwen3.8-max", "qwen3.7-max", "qwen3.7-plus", "deepseek-v4-pro", "glm-5.2"]),
    _provider("volcengine-ark", "火山方舟（豆包）", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-2.0-code", ["doubao-seed-2.0-code", "doubao-seed-2.0-pro", "doubao-seed-2.0-lite", "doubao-seed-2.0-mini"]),
    _provider("zai", "智谱 GLM（Coding Plan）", "https://open.bigmodel.cn/api/v1", "glm-5.3", ["glm-5.3", "glm-5-turbo", "glm-5.2", "glm-5.1", "glm-5"]),
    _provider("tokenhub", "腾讯云 TokenHub", "https://tokenhub.tencentmaas.com/v1", "glm-5.2", ["glm-5.2", "glm-5.1", "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "deepseek-v4-pro", "minimax-m3", "hy3"]),
    _provider("openrouter", "OpenRouter（聚合）", "https://openrouter.ai/api/v1", "openai/gpt-5.6", ["openai/gpt-5.6", "openai/gpt-5.6-sol", "anthropic/claude-opus-4.6", "google/gemini-3.1-pro", "qwen/qwen3-max", "deepseek/deepseek-v3.2"]),
    _provider("groq", "Groq（超快推理）", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "qwen/qwen3.6-27b"]),
    _provider("xai", "xAI Grok", "https://api.x.ai/v1", "grok-4.5", ["grok-4.5", "grok-4.3", "grok-4.1-fast", "grok-4"]),
    _provider("perplexity", "Perplexity", "https://api.perplexity.ai/v1", "sonar-pro", ["sonar-pro", "sonar-reasoning-pro", "sonar"]),
    _provider("huggingface", "Hugging Face Inference", "https://router.huggingface.co/v1", "openai/gpt-oss-120b", ["openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "deepseek-ai/DeepSeek-R1", "qwen/qwen3-32b"]),
    _provider("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/qwen3-235b-a22b", ["accounts/fireworks/models/qwen3-235b-a22b", "accounts/fireworks/models/llama4-maverick", "accounts/fireworks/models/qwen3-32b"]),
    _provider("digitalocean", "DigitalOcean AI Platform", "https://inference.do-ai.run/v1", "openai-gpt-oss-20b", ["openai-gpt-oss-20b", "openai-gpt-oss-120b"]),
    _provider("sambanova", "SambaNova", "https://api.sambanova.ai/v1", "gpt-oss-120b", ["gpt-oss-120b", "MiniMax-M2.7", "MiniMax-M2.5", "DeepSeek-V3.1"]),
    _provider("nebius", "Nebius Token Factory", "https://api.tokenfactory.nebius.com/v1", "moonshotai/Kimi-K2.5", ["moonshotai/Kimi-K2.5", "nebius/NousResearch/Hermes-4-405B", "meta-llama/Llama-3.3-70B-Instruct"]),
    _provider("vercel", "Vercel AI Gateway", "https://ai-gateway.vercel.sh/v1", "openai/gpt-5.6-sol", ["openai/gpt-5.6-sol", "openai/gpt-5.4", "anthropic/claude-opus-5", "anthropic/claude-sonnet-5"]),
    _provider("cloudflare", "Cloudflare AI Gateway", "", "openai/gpt-4.1", ["openai/gpt-4.1", "@cf/openai/gpt-oss-120b"], requires_base_url=True),
    _provider("novai", "NovAI（国产模型网关）", "https://aiapi-pro.com/v1", "deepseek-v3.2", ["deepseek-v3.2", "glm-5", "qwen-max", "qwen-plus", "minimax-text-01"]),
    _provider("ollama", "Ollama（本地）", "http://localhost:11434/v1", "qwen3-coder:32b", ["qwen3-coder:32b", "qwen3-coder:14b", "llama3.3", "deepseek-r1"], protocol="openai_chat", auth_mode="none"),
    _provider("lmstudio", "LM Studio（本地）", "http://localhost:1234/v1", "local-model", ["local-model"], protocol="openai_chat", auth_mode="none"),
    _provider("generic-responses", "通用 Responses 中转站", "", "gpt-5.6", ["gpt-5.6", "gpt-5.4", "gpt-4.1", "gpt-4o"], requires_base_url=True),
    # Extra universal entries are intentionally outside the 23-provider baseline.
    _provider("generic-chat", "通用 Chat Completions 接口", "", "", [], protocol="openai_chat", requires_base_url=True),
    _provider("generic-anthropic", "通用 Anthropic Messages 接口", "", "", [], protocol="anthropic_messages", auth_mode="x-api-key", requires_base_url=True),
]


def provider_catalog() -> list[dict]:
    return deepcopy(PROVIDERS)


def get_provider(provider_id: str) -> dict:
    for item in PROVIDERS:
        if item["id"] == provider_id:
            return deepcopy(item)
    raise KeyError(provider_id)


def resolve_protocol(provider_id: str, model: str, override: str = "auto") -> str:
    if override and override != "auto":
        return override
    provider = get_provider(provider_id)
    mapped = provider["model_protocols"].get(model)
    if mapped:
        return mapped
    protocol = provider["protocol"]
    # Unknown OpenCode models are safest through Chat Completions; users can still
    # choose a protocol explicitly with a generic preset.
    return "openai_chat" if protocol == "auto" else protocol
