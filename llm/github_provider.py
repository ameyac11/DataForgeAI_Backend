from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
from azure.core.credentials import AzureKeyCredential
from config import get_settings

settings = get_settings()

GITHUB_ENDPOINT = "https://models.github.ai/inference"

# github model name mapping
GITHUB_MODELS = {
    "gpt-4.1": "openai/gpt-4.1",
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
            max_tokens=1000,
            stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        raise Exception(f"GITHUB_ERROR:{model_id}:{str(e)[:100]}")


def generate_completion(messages: list, model_id: str, temperature: float = 0.5, max_tokens: int = 8192, timeout: int = 120) -> str:
    """Non-streaming completion for dataset generation."""
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
        raise Exception(f"GITHUB_ERROR:{model_id}:{str(e)[:100]}")
