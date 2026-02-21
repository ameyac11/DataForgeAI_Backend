from llm import groq_provider, github_provider
from models import MODEL_CONFIG, DEFAULT_CHAT_MODEL, DEFAULT_GEN_MODEL


def get_provider(model_id: str):
    """Return the right provider module. Validates model_id against MODEL_CONFIG."""
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        raise ValueError(f"Unknown model: {model_id}")
    if cfg["provider"] == "github":
        return github_provider
    return groq_provider


async def stream_chat(messages: list, model_id: str = None):
    """Stream chat response. Validates model before calling provider."""
    model_id = model_id or DEFAULT_CHAT_MODEL
    provider = get_provider(model_id)
    async for chunk in provider.stream_completion(messages, model_id):
        yield chunk


def generate_text(messages: list, model_id: str = None, temperature: float = 0.5) -> str:
    """Non-streaming text generation. max_tokens pulled from MODEL_CONFIG automatically."""
    model_id = model_id or DEFAULT_GEN_MODEL
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        raise ValueError(f"Unknown model: {model_id}")

    max_tokens = cfg["max_output_tokens"]
    provider = get_provider(model_id)
    result = provider.generate_completion(messages, model_id, temperature=temperature, max_tokens=max_tokens)
    if not result:
        raise ValueError(f"Model '{model_id}' returned an empty response. Please try again.")
    return result
