# Disable Azure SDK verbose logging before any imports
import logging
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.ERROR)
logging.getLogger('azure.ai.inference').setLevel(logging.ERROR)
logging.getLogger('azure.core').setLevel(logging.ERROR)
logging.getLogger('azure.core.pipeline').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.WARNING)

import os
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from azure.core.pipeline.transport import RequestsTransport

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
ENDPOINT = "https://models.github.ai/inference"

MODEL_CONFIGS = {
    "gpt-4.1": {
        "name": "openai/gpt-4.1",
        "display_name": "GPT-4.1",
        "description": "Strongest Reasoning",
        "requires_auth": True,
        "default_temp": 0.5,
        "max_tokens": 16384,
        "timeout": 180,
        "use_completion_tokens": False
    },
    "gpt-4o": {
        "name": "openai/gpt-4o",
        "display_name": "GPT-4o",
        "description": "Most Creative",
        "requires_auth": True,
        "default_temp": 0.7,
        "max_tokens": 8192,
        "timeout": 180,
        "use_completion_tokens": False
    },
    "gpt-4.1-mini": {
        "name": "openai/gpt-4.1-mini",
        "display_name": "GPT-4.1 Mini",
        "description": "Balanced Performance",
        "requires_auth": False,
        "default_temp": 0.5,
        "max_tokens": 8192,
        "timeout": 120,
        "use_completion_tokens": False
    },
    "gpt-4o-mini": {
        "name": "openai/gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "description": "Fast & Creative",
        "requires_auth": False,
        "default_temp": 0.6,
        "max_tokens": 8192,
        "timeout": 90,
        "use_completion_tokens": False
    },
    "gpt-4.1-nano": {
        "name": "openai/gpt-4.1-nano",
        "display_name": "GPT-4.1 Nano",
        "description": "Fastest Model",
        "requires_auth": False,
        "default_temp": 0.5,
        "max_tokens": 4096,
        "timeout": 60,
        "use_completion_tokens": False
    },
    "meta/Meta-Llama-3.1-8B-Instruct": {
        "name": "meta/Meta-Llama-3.1-8B-Instruct",
        "display_name": "Llama 3.1 8B",
        "description": "Dataset Analytics",
        "requires_auth": False,
        "default_temp": 1.0,
        "max_tokens": 1000,
        "timeout": 120,
        "use_completion_tokens": False
    }
}

DEFAULT_MODEL = "gpt-4.1-mini"
FAST_MODEL = "gpt-4.1-nano"
POWERFUL_MODEL = "gpt-4o"
ANALYTICS_MODEL = "meta/Meta-Llama-3.1-8B-Instruct"

def get_client(timeout: int = 120) -> ChatCompletionsClient:
    """Get AI client with configurable timeout."""
    if not GITHUB_TOKEN:
        raise Exception("GitHub token not found. Please check your environment configuration.")
    
    # Create transport with optimized timeout for faster response
    transport = RequestsTransport(
        connection_timeout=30,
        read_timeout=timeout
    )
    
    return ChatCompletionsClient(
        endpoint=ENDPOINT,
        credential=AzureKeyCredential(GITHUB_TOKEN),
        transport=transport
    )

def generate_completion(
    system_prompt: str,
    user_prompt: str,
    model_id: str = DEFAULT_MODEL,
    temperature: float = None,
    max_tokens: int = None,
    timeout: int = None
) -> str:
    """
    Generate completion using AI model.
    Single API call optimized for large dataset generation.
    
    Args:
        system_prompt: System instructions
        user_prompt: User request
        model_id: Model to use
        temperature: Creativity level (0-1)
        max_tokens: Maximum output tokens (increased for large datasets)
        timeout: Request timeout in seconds (default based on model)
    """
    try:
        model_config = MODEL_CONFIGS.get(model_id, MODEL_CONFIGS[DEFAULT_MODEL])
        model_name = model_config["name"]
        use_completion_tokens = model_config.get("use_completion_tokens", False)
        
        if temperature is None:
            temperature = model_config["default_temp"]
        if max_tokens is None:
            max_tokens = model_config["max_tokens"]
        if timeout is None:
            timeout = model_config.get("timeout", 180)
        
        # Create client with proper timeout configuration
        client = get_client(timeout=timeout)
        
        # Build request parameters - some models need max_completion_tokens instead of max_tokens
        request_params = {
            "messages": [
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ],
            "temperature": temperature,
            "top_p": 1.0,
            "model": model_name
        }
        
        # Add token limit parameter only for models that support it via Azure SDK
        # GPT-5 doesn't support token limits via Azure SDK, so skip it
        if not use_completion_tokens:
            request_params["max_tokens"] = max_tokens
        
        response = client.complete(**request_params)
        
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content
        
        return ""
        
    except Exception as e:
        error_msg = str(e)
        print(f"AI Error Details: {error_msg}")
        raise Exception(f"AI generation failed: {error_msg}")

def is_model_available_for_user(model_id: str, is_authenticated: bool) -> bool:
    model_config = MODEL_CONFIGS.get(model_id)
    if not model_config:
        return False
    
    if model_config["requires_auth"] and not is_authenticated:
        return False
    
    return True

def get_available_models(is_authenticated: bool) -> List[Dict[str, Any]]:
    available = []
    for model_id, config in MODEL_CONFIGS.items():
        if model_id == "gpt-4.1-nano" or model_id.startswith("meta/"):
            continue
            
        if is_model_available_for_user(model_id, is_authenticated):
            available.append({
                "id": model_id,
                "name": config["display_name"],
                "description": config["description"],
                "requires_auth": config["requires_auth"]
            })
        else:
            available.append({
                "id": model_id,
                "name": config["display_name"],
                "description": config["description"],
                "requires_auth": config["requires_auth"],
                "locked": True
            })
    return available
