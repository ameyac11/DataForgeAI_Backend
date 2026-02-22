import logging
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    SystemMessage, UserMessage, AssistantMessage,
    TextContentItem, ImageContentItem, ImageUrl,
)
from azure.core.credentials import AzureKeyCredential
from config import get_settings

logger = logging.getLogger("dataforge.llm.github")
settings = get_settings()

GITHUB_ENDPOINT = "https://models.github.ai/inference"

# github model name mapping
GITHUB_MODELS = {
    "gpt-4o": "openai/gpt-4o",
    "gpt-4.1-nano": "openai/gpt-4.1-nano",
    "gpt-4o-mini": "openai/gpt-4o-mini",
}


def _get_client(timeout: int = 120) -> ChatCompletionsClient:
    return ChatCompletionsClient(
        endpoint=GITHUB_ENDPOINT,
        credential=AzureKeyCredential(settings.GITHUB_TOKEN),
    )


def _convert_messages(messages: list) -> list:
    """Convert dict messages to Azure AI SDK message objects."""
    converted = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "user":
            if isinstance(content, list):
                # Multimodal content with text + images
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append(TextContentItem(text=part["text"]))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        parts.append(ImageContentItem(image_url=ImageUrl(url=url)))
                converted.append(UserMessage(content=parts))
            else:
                converted.append(UserMessage(content=content))
        elif role == "assistant":
            converted.append(AssistantMessage(content=content))
    return converted


async def stream_completion(messages: list, model_id: str):
    """Async generator yielding text chunks via GitHub Models streaming."""
    client = _get_client()
    github_model = GITHUB_MODELS.get(model_id, model_id)

    try:
        response = client.complete(
            model=github_model,
            messages=_convert_messages(messages),
            temperature=0.2,
            max_tokens=8000,
            stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
            logger.warning("[GITHUB STREAM] Rate limit hit for model '%s'", model_id)
            raise Exception(f"Rate limit exceeded for model '{model_id}'. Please wait a moment and try again.")
        if "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
            logger.error("[GITHUB STREAM] Authentication failed for model '%s' — check GITHUB_TOKEN", model_id)
            raise Exception(f"LLM authentication failed (GitHub Models). Please check server API key configuration.")
        if "timeout" in error_str or "timed out" in error_str:
            logger.error("[GITHUB STREAM] Timeout for model '%s'", model_id)
            raise Exception(f"Model '{model_id}' timed out. Please try again.")
        if "413" in error_str or "too large" in error_str or "content_length" in error_str:
            logger.warning("[GITHUB STREAM] Request too large for model '%s'", model_id)
            raise Exception(f"Request too large for model '{model_id}'. Try reducing message length or image count.")
        logger.error("[GITHUB STREAM] Unexpected error for model '%s': %s: %s", model_id, type(e).__name__, e)
        raise Exception(f"LLM error with model '{model_id}': {str(e)[:150]}")


def generate_completion(messages: list, model_id: str, temperature: float = 0.5, max_tokens: int = 8192, timeout: int = 120) -> str:
    """Non-streaming completion. max_tokens always provided by router from MODEL_CONFIG."""
    client = _get_client(timeout)
    github_model = GITHUB_MODELS.get(model_id, model_id)

    try:
        response = client.complete(
            model=github_model,
            messages=_convert_messages(messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
            logger.warning("[GITHUB GENERATE] Rate limit hit for model '%s'", model_id)
            raise Exception(f"Rate limit exceeded for model '{model_id}'. Please wait a moment and try again.")
        if "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
            logger.error("[GITHUB GENERATE] Authentication failed for model '%s' — check GITHUB_TOKEN", model_id)
            raise Exception(f"LLM authentication failed (GitHub Models). Please check server API key configuration.")
        if "timeout" in error_str or "timed out" in error_str:
            logger.error("[GITHUB GENERATE] Timeout for model '%s'", model_id)
            raise Exception(f"Model '{model_id}' timed out. Please try again.")
        logger.error("[GITHUB GENERATE] Unexpected error for model '%s': %s: %s", model_id, type(e).__name__, e)
        raise Exception(f"LLM error with model '{model_id}': {str(e)[:150]}")
