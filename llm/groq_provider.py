"""Groq LLM Provider — all limits/model-names come from model_config.py."""
import os
import logging
from groq import Groq
from config import get_settings

from llm.model_config import (
    MODEL_CONFIG, LLMProvider, BEHAVIOR_MODES,
    get_api_model_name, get_max_output_tokens,
    get_reasoning_effort, is_compound_model,
)

logger = logging.getLogger("dataforge.llm.groq")
settings = get_settings()

# compound_custom payload — enable only the web_search tool
COMPOUND_TOOLS = {"tools": {"enabled_tools": ["web_search", "visit_website"]}}


def _get_client() -> Groq:
    return Groq(api_key=settings.GROQ_API_KEY)


async def stream_completion(messages: list, model_id: str):
    """Async generator yielding text chunks via Groq streaming.
    Compound models always get internet tools via compound_custom."""
    client = _get_client()
    model_name = get_api_model_name(model_id)
    _balanced = BEHAVIOR_MODES["balanced"]

    # max_tokens from centralized config
    max_tokens = get_max_output_tokens(model_id)

    kwargs = {
        "model": model_name,
        "messages": messages,
        "temperature": _balanced["temperature"],
        "top_p": _balanced["top_p"],
        "max_completion_tokens": max_tokens,
        "stream": True,
    }

    if is_compound_model(model_id):
        kwargs["compound_custom"] = COMPOUND_TOOLS

    effort = get_reasoning_effort(model_id)
    if effort:
        kwargs["reasoning_effort"] = effort

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


def generate_completion(messages: list, model_id: str, temperature: float = 0.5, top_p: float = None, max_tokens: int = 8192, timeout: int = 1200) -> str:
    client = _get_client()
    model_name = get_api_model_name(model_id)
    _balanced = BEHAVIOR_MODES["balanced"]

    try:
        kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p if top_p is not None else _balanced["top_p"],
            "max_completion_tokens": max_tokens,
        }

        effort = get_reasoning_effort(model_id)
        if effort:
            kwargs["reasoning_effort"] = effort

        # compound: stream and collect (non-streaming returns empty for tool-call chains)
        if is_compound_model(model_id):
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
