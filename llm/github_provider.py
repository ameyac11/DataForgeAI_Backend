# github llm provider
import logging
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    SystemMessage, UserMessage, AssistantMessage,
    TextContentItem, ImageContentItem, ImageUrl,
)
from azure.core.credentials import AzureKeyCredential
from config import get_settings

from llm.model_config import (
    MODEL_CONFIG,
    BEHAVIOR_MODES,
    get_api_model_name,
    get_max_output_tokens,
)

logger = logging.getLogger("dataforge.llm.github")
settings = get_settings()

GITHUB_ENDPOINT = "https://models.github.ai/inference"




def _get_client(timeout: int = 120) -> ChatCompletionsClient:
    return ChatCompletionsClient(
        endpoint=GITHUB_ENDPOINT,
        credential=AzureKeyCredential(settings.GITHUB_TOKEN),
    )


def _convert_messages(messages: list) -> list:
    # convert to azure format
    converted = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "user":
            if isinstance(content, list):
                # multimodal text images
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
    # stream azure completion
    client = _get_client()
    model_name = get_api_model_name(model_id)
    _balanced = BEHAVIOR_MODES["balanced"]

    try:
        response = client.complete(
            model=model_name,
            messages=_convert_messages(messages),
            temperature=_balanced["temperature"],
            top_p=_balanced["top_p"],
            max_tokens=get_max_output_tokens(model_id),
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


def generate_completion(messages: list, model_id: str, temperature: float = 0.5, top_p: float = None, max_tokens: int = 8192, timeout: int = 120) -> str:
    # get azure completion
    client = _get_client(timeout)
    model_name = get_api_model_name(model_id)
    _balanced = BEHAVIOR_MODES["balanced"]

    try:
        response = client.complete(
            model=model_name,
            messages=_convert_messages(messages),
            temperature=temperature,
            top_p=top_p if top_p is not None else _balanced["top_p"],
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
