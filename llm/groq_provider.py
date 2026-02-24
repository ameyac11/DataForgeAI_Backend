import os
import logging
from groq import Groq
from config import get_settings
from models import MODEL_CONFIG

logger = logging.getLogger("dataforge.llm.groq")
settings = get_settings()

# groq model name mapping
GROQ_MODELS = {
    "compound": "groq/compound",
    "compound-mini": "groq/compound-mini",
    "llama-scout-4": "meta-llama/llama-4-scout-17b-16e-instruct",
    "gpt-oss-120b": "openai/gpt-oss-120b",
}

# compound models get web_search tool automatically
COMPOUND_MODELS = {mid for mid, cfg in MODEL_CONFIG.items() if cfg.get("web_search")}

# compound_custom payload — enable only the web_search tool
COMPOUND_TOOLS = {"tools": {"enabled_tools": ["web_search"]}}


def _get_client() -> Groq:
    return Groq(api_key=settings.GROQ_API_KEY)


async def stream_completion(messages: list, model_id: str):
    """Async generator yielding text chunks via Groq streaming.
    Compound models always get internet tools via compound_custom."""
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    # max_tokens from centralized config
    max_tokens = MODEL_CONFIG.get(model_id, {}).get("max_output_tokens", 8192)

    kwargs = {
        "model": groq_model,
        "messages": messages,
        "temperature": 0.8,
        "max_completion_tokens": max_tokens,
        "stream": True,
    }

    if model_id in COMPOUND_MODELS:
        kwargs["compound_custom"] = COMPOUND_TOOLS

    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate_limit" in error_str:
            logger.warning("[GROQ STREAM] Rate limit hit for model '%s'", model_id)
            raise Exception(f"Rate limit exceeded for model '{model_id}'. Please wait a moment and try again.")
        if "413" in error_str or "too large" in error_str:
            logger.warning("[GROQ STREAM] Request too large for model '%s'", model_id)
            raise Exception(f"Request too large for model '{model_id}'. Try reducing message length or image count.")
        if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
            logger.error("[GROQ STREAM] Authentication failed for model '%s' — check GROQ_API_KEY", model_id)
            raise Exception(f"LLM authentication failed (Groq). Please check server API key configuration.")
        if "timeout" in error_str or "timed out" in error_str:
            logger.error("[GROQ STREAM] Timeout for model '%s'", model_id)
            raise Exception(f"Model '{model_id}' timed out. Please try again.")
        logger.error("[GROQ STREAM] Unexpected error for model '%s': %s: %s", model_id, type(e).__name__, e)
        raise Exception(f"LLM error with model '{model_id}': {str(e)[:150]}")


def generate_completion(messages: list, model_id: str, temperature: float = 0.8, max_tokens: int = 8192, timeout: int = 1200) -> str:
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    try:
        kwargs = {
            "model": groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        # compound: stream and collect (non-streaming returns empty for tool-call chains)
        if model_id in COMPOUND_MODELS:
            kwargs["compound_custom"] = COMPOUND_TOOLS
            kwargs["stream"] = True
            stream = client.chat.completions.create(**kwargs)
            collected = ""
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    collected += chunk.choices[0].delta.content
            return collected

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate_limit" in error_str:
            logger.warning("[GROQ GENERATE] Rate limit hit for model '%s'", model_id)
            raise Exception(f"Rate limit exceeded for model '{model_id}'. Please wait a moment and try again.")
        if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
            logger.error("[GROQ GENERATE] Authentication failed for model '%s' — check GROQ_API_KEY", model_id)
            raise Exception(f"LLM authentication failed (Groq). Please check server API key configuration.")
        if "timeout" in error_str or "timed out" in error_str:
            logger.error("[GROQ GENERATE] Timeout for model '%s'", model_id)
            raise Exception(f"Model '{model_id}' timed out. Please try again.")
        logger.error("[GROQ GENERATE] Unexpected error for model '%s': %s: %s", model_id, type(e).__name__, e)
        raise Exception(f"LLM error with model '{model_id}': {str(e)[:150]}")
