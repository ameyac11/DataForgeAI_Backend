import os
from groq import Groq
from config import get_settings

settings = get_settings()

# groq model name mapping
GROQ_MODELS = {
    "compound": "groq/compound",
    "compound-mini": "groq/compound-mini",
    "llama-scout-4": "meta-llama/llama-4-scout-17b-16e-instruct",
    "gpt-oss-120b": "openai/gpt-oss-120b",
}

# models that support web search tool via compound_custom
WEB_SEARCH_MODELS = {"compound", "compound-mini"}

# compound_custom payload — enables web_search and visit_website tools
COMPOUND_TOOLS = {"tools": {"enabled_tools": ["web_search", "visit_website"]}}


def _get_client() -> Groq:
    return Groq(api_key=settings.GROQ_API_KEY)


async def stream_completion(messages: list, model_id: str, use_web_search: bool = True):
    """Async generator yielding text chunks via Groq streaming.
    Compound models ALWAYS get internet tools enabled via compound_custom."""
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    kwargs = {
        "model": groq_model,
        "messages": messages,
        "temperature": 0.8,
        "max_completion_tokens": 8000,
        "stream": True,
    }

    # Compound models always get internet tools via compound_custom
    if model_id in WEB_SEARCH_MODELS:
        kwargs["compound_custom"] = COMPOUND_TOOLS

    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate_limit" in error_str:
            raise Exception(f"RATE_LIMITED:{model_id}")
        if "413" in error_str or "too large" in error_str:
            raise Exception(f"TOO_LARGE:{model_id}")
        raise


def generate_completion(messages: list, model_id: str, temperature: float = 0.8, max_tokens: int = 8000, timeout: int = 1200, use_web_search: bool = True) -> str:
    """Non-streaming completion for dataset generation.
    Compound models ALWAYS get internet tools via compound_custom.
    Compound models use streaming internally to collect the full response,
    because compound_custom tool-call chains leave content=None in a single
    non-streaming response."""
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    try:
        kwargs = {
            "model": groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        # Compound models: use streaming to collect full response —
        # non-streaming returns content=None when web_search tool calls are involved
        if model_id in WEB_SEARCH_MODELS:
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
            raise Exception(f"RATE_LIMITED:{model_id}")
        raise
