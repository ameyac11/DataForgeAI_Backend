import os
from groq import Groq
from config import get_settings

settings = get_settings()

# groq model name mapping
GROQ_MODELS = {
    "compound": "compound-beta",
    "compound-mini": "compound-beta-mini",
    "llama-scout-4": "meta-llama/llama-4-scout-17b-16e-instruct",
    "gpt-oss-120b": "qwen/qwen3-235b-a22b",
}

# models that support web search tool
WEB_SEARCH_MODELS = {"compound", "compound-mini"}


def _get_client() -> Groq:
    return Groq(api_key=settings.GROQ_API_KEY)


async def stream_completion(messages: list, model_id: str, use_web_search: bool = False):
    """Async generator yielding text chunks via Groq streaming.
    NOTE: Web search tools are NEVER used during chat streaming.
    Tools are only used in generate_completion() for dataset generation."""
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    kwargs = {
        "model": groq_model,
        "messages": messages,
        "temperature": 0.2,
        "max_completion_tokens": 1000,
        "stream": True,
    }

    # NO tools during chat streaming — ever
    # Compound models stream normally without web search during chat

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


def generate_completion(messages: list, model_id: str, temperature: float = 0.5, max_tokens: int = 8192, timeout: int = 120, use_web_search: bool = False) -> str:
    """Non-streaming completion for dataset generation."""
    client = _get_client()
    groq_model = GROQ_MODELS.get(model_id, model_id)

    try:
        kwargs = {
            "model": groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        # compound models get web_search + visit_website tools ONLY during dataset generation
        if model_id in WEB_SEARCH_MODELS and use_web_search:
            kwargs["tools"] = [
                {"type": "web_search_preview"},
            ]
            kwargs["tool_choice"] = "auto"
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate_limit" in error_str:
            raise Exception(f"RATE_LIMITED:{model_id}")
        raise
