# centralized model configuration — single source of truth

MODEL_CONFIG = {
    "gpt-4.1": {
        "max_output_tokens": 7900,
        "rpm": 10,
        "rpd": 50,
        "type": "non_compound",
        "provider": "github",
        "vision": True,
    },
    "gpt-4.1-nano": {
        "max_output_tokens": 7900,
        "rpm": 15,
        "rpd": 150,
        "type": "non_compound",
        "provider": "github",
    },
    "gpt-4o-mini": {
        "max_output_tokens": 7900,
        "rpm": 15,
        "rpd": 150,
        "type": "non_compound",
        "provider": "github",
        "vision": True,
    },
    "compound": {
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 250,
        "type": "compound",
        "provider": "groq",
        "web_search": True,
    },
    "compound-mini": {
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 250,
        "type": "compound",
        "provider": "groq",
        "web_search": True,
    },
    "llama-scout-4": {
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 1000,
        "type": "non_compound",
        "provider": "groq",
        "vision": True,
    },
    "gpt-oss-120b": {
        "max_output_tokens": 4000,
        "rpm": 30,
        "rpd": 1000,
        "type": "non_compound",
        "provider": "groq",
    },
}

DEFAULT_CHAT_MODEL = "llama-scout-4"
DEFAULT_GEN_MODEL = "gpt-4o-mini"
COLUMN_SUGGEST_MODEL = "gpt-4.1-nano"


def is_compound(model_id: str) -> bool:
    cfg = MODEL_CONFIG.get(model_id)
    return cfg is not None and cfg["type"] == "compound"


def get_max_tokens(model_id: str) -> int:
    cfg = MODEL_CONFIG.get(model_id)
    if cfg is None:
        raise ValueError(f"Unknown model: {model_id}")
    return cfg["max_output_tokens"]
