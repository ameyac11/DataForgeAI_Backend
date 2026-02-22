import logging
from llm import groq_provider, github_provider
from models import MODEL_CONFIG, DEFAULT_CHAT_MODEL, DEFAULT_GEN_MODEL

logger = logging.getLogger("dataforge.llm.router")


def get_provider(model_id: str):
    """Return the right provider module. Validates model_id against MODEL_CONFIG."""
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        logger.error("[ROUTER] Unknown model requested: '%s'. Available: %s", model_id, list(MODEL_CONFIG.keys()))
        raise ValueError(
            f"Unknown model '{model_id}'. Available models: {', '.join(MODEL_CONFIG.keys())}"
        )
    if cfg["provider"] == "github":
        return github_provider
    return groq_provider


async def stream_chat(messages: list, model_id: str = None):
    """Stream chat response. Validates model before calling provider."""
    model_id = model_id or DEFAULT_CHAT_MODEL
    logger.info("[ROUTER] Streaming chat with model '%s'", model_id)
    provider = get_provider(model_id)
    async for chunk in provider.stream_completion(messages, model_id):
        yield chunk


def generate_text(messages: list, model_id: str = None, temperature: float = 0.5) -> str:
    """Non-streaming text generation. max_tokens pulled from MODEL_CONFIG automatically."""
    model_id = model_id or DEFAULT_GEN_MODEL
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        logger.error("[ROUTER] Unknown model requested for generation: '%s'", model_id)
        raise ValueError(
            f"Unknown model '{model_id}'. Available models: {', '.join(MODEL_CONFIG.keys())}"
        )

    max_tokens = cfg["max_output_tokens"]
    provider = get_provider(model_id)
    logger.info("[ROUTER] Generating text with model '%s' (max_tokens=%d, temp=%.1f)", model_id, max_tokens, temperature)
    try:
        result = provider.generate_completion(messages, model_id, temperature=temperature, max_tokens=max_tokens)
    except Exception as exc:
        logger.error("[ROUTER] generate_text failed for model '%s': %s: %s", model_id, type(exc).__name__, exc)
        raise
    if not result:
        logger.warning("[ROUTER] Model '%s' returned empty response", model_id)
        raise ValueError(f"Model '{model_id}' returned an empty response. Please try again.")
    return result
