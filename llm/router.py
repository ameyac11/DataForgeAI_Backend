from llm import groq_provider, github_provider

# which provider handles which model
GROQ_MODELS = {"compound", "compound-mini", "llama-scout-4", "gpt-oss-120b"}
GITHUB_MODELS = {"gpt-4.1", "gpt-4.1-nano", "gpt-4o-mini"}

# all available models with display info
MODEL_REGISTRY = {
    "compound": {"name": "Compound", "provider": "groq", "web_search": True},
    "compound-mini": {"name": "Compound Mini", "provider": "groq", "web_search": True},
    "llama-scout-4": {"name": "Llama 4 Scout", "provider": "groq", "vision": True},
    "gpt-oss-120b": {"name": "GPT OSS 120B", "provider": "groq"},
    "gpt-4.1": {"name": "GPT-4.1", "provider": "github", "vision": True},
    "gpt-4.1-nano": {"name": "GPT-4.1 Nano", "provider": "github"},
    "gpt-4o-mini": {"name": "GPT-4o Mini", "provider": "github", "vision": True},
}

DEFAULT_CHAT_MODEL = "llama-scout-4"
DEFAULT_GEN_MODEL = "gpt-4o-mini"

# fallback order when a model fails
FALLBACK_CHAIN = ["llama-scout-4", "compound", "compound-mini", "gpt-4o-mini", "gpt-oss-120b", "gpt-4.1"]


def get_provider(model_id: str):
    """Return the right provider module for a model."""
    if model_id in GROQ_MODELS:
        return groq_provider
    if model_id in GITHUB_MODELS:
        return github_provider
    return groq_provider  # default


async def stream_chat(messages: list, model_id: str = None):
    """Stream chat response with automatic fallback on failure.
    Web search tools are NEVER used during chat — only during dataset generation."""
    model_id = model_id or DEFAULT_CHAT_MODEL
    tried = set()

    # try requested model first, then fallback chain
    models_to_try = [model_id] + [m for m in FALLBACK_CHAIN if m != model_id]

    for mid in models_to_try:
        if mid in tried:
            continue
        tried.add(mid)
        try:
            provider = get_provider(mid)
            async for chunk in provider.stream_completion(messages, mid):
                yield chunk
            return  # success, done
        except Exception:
            continue  # try next model

    yield "Sorry, all models are currently unavailable. Please try again later."


def generate_text(messages: list, model_id: str = None, temperature: float = 0.5, max_tokens: int = 8192, use_web_search: bool = False) -> str:
    """Non-streaming text generation with fallback."""
    model_id = model_id or DEFAULT_GEN_MODEL
    tried = set()
    models_to_try = [model_id] + [m for m in FALLBACK_CHAIN if m != model_id]

    for mid in models_to_try:
        if mid in tried:
            continue
        tried.add(mid)
        try:
            provider = get_provider(mid)
            result = provider.generate_completion(messages, mid, temperature=temperature, max_tokens=max_tokens, use_web_search=use_web_search)
            if result:
                return result
        except Exception:
            continue

    return ""
