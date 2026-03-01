"""LLM Router — all model knowledge is imported from model_config.py."""
import logging
from typing import Generator, List, Dict, Any, Optional

logger = logging.getLogger("dataforge.llm.router")

from llm.model_config import (
    LLMProvider,
    MODEL_CONFIG,
    get_provider as _cfg_get_provider,
    get_model_metadata,
    get_display_order,
    get_fallback_order,
    get_default_model as _cfg_default_model,
    get_max_output_tokens,
    is_vision_model as _cfg_is_vision,
    is_web_search_model as _cfg_is_web,
    DEFAULT_CHAT_MODEL,
    DEFAULT_GEN_MODEL,
)


def get_provider(model_id: str):
    """Return the right provider module. Validates model_id against MODEL_CONFIG."""
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        logger.error("[ROUTER] Unknown model requested: '%s'. Available: %s", model_id, list(MODEL_CONFIG.keys()))
        raise ValueError(
            f"Unknown model '{model_id}'. Available models: {', '.join(MODEL_CONFIG.keys())}"
        )
    from llm import github_provider, groq_provider
    if cfg["provider"] == LLMProvider.GITHUB:
        return github_provider
    return groq_provider


async def stream_chat(messages: list, model_id: str = None):
    """Stream chat response. Validates model before calling provider."""
    model_id = model_id or DEFAULT_CHAT_MODEL
    logger.info("[ROUTER] Streaming chat with model '%s'", model_id)
    provider = get_provider(model_id)
    async for chunk in provider.stream_completion(messages, model_id):
        yield chunk


def generate_text(messages: list, model_id: str = None, temperature: float = 0.5, top_p: float = None) -> str:
    """Non-streaming text generation. max_tokens pulled from model_config automatically."""
    model_id = model_id or DEFAULT_GEN_MODEL
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        logger.error("[ROUTER] Unknown model requested for generation: '%s'", model_id)
        raise ValueError(
            f"Unknown model '{model_id}'. Available models: {', '.join(MODEL_CONFIG.keys())}"
        )

    max_tokens = cfg["max_output_tokens"]
    provider = get_provider(model_id)
    logger.info("[ROUTER] Generating text with model '%s' (max_tokens=%d, temp=%.2f)", model_id, max_tokens, temperature)
    try:
        result = provider.generate_completion(messages, model_id, temperature=temperature, top_p=top_p, max_tokens=max_tokens)
    except Exception as exc:
        logger.error("[ROUTER] generate_text failed for model '%s': %s: %s", model_id, type(exc).__name__, exc)
        raise
    if not result:
        logger.warning("[ROUTER] Model '%s' returned empty response", model_id)
        raise ValueError(f"Model '{model_id}' returned an empty response. Please try again.")
    return result


def get_available_models() -> List[Dict[str, Any]]:
    metadata = get_model_metadata()
    return [{"id": m, **metadata[m]} for m in get_display_order() if m in metadata]


def get_fallback_model(current_model: str, vision_required: bool = False, excluded_models: Optional[List[str]] = None) -> Optional[str]:
    excluded = set(excluded_models or [])
    excluded.add(current_model)
    for model in get_fallback_order():
        if model in excluded:
            continue
        if vision_required and not _cfg_is_vision(model):
            continue
        return model
    return None


def is_vision_model(model: str) -> bool:
    return _cfg_is_vision(model)


def is_web_search_model(model: str) -> bool:
    return _cfg_is_web(model)


def get_default_model() -> str:
    return _cfg_default_model()


def get_model_provider(model: str) -> str:
    return _cfg_get_provider(model).value
