"""
Centralized Model Configuration — the SINGLE source of truth for all LLM models.

Every other module (router, providers, rate-limiter, generator) MUST import
from here instead of hardcoding model names, limits, or capabilities.

Behavior Modes control LLM sampling parameters (temperature, top_p) independently.
DataForgeAI uses generation-oriented modes tuned for dataset output quality.
"""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    GROQ = "groq"
    GITHUB = "github"


# ── Master model registry ──────────────────────────────────────────────────────
#
# Keys used in MODEL_CONFIG:
#   api_model       – actual model identifier sent to the provider API
#   provider        – "groq" | "github"
#   type            – "compound" (built-in web search) | "non_compound"
#   max_output_tokens – hard cap passed to the LLM on every call
#   rpm             – requests-per-minute  (enforced via Redis)
#   rpd             – requests-per-day     (enforced via Redis)
#   vision          – supports image/multimodal input
#   web_search      – has built-in web search (compound models only)
#   is_default      – the default model for new chats
#   reasoning_effort– only for models that support it (e.g. gpt-oss-120b)
#   display_name    – human-readable label for the frontend
#   description     – short description for tooltips
# ────────────────────────────────────────────────────────────────────────────────

MODEL_CONFIG = {
    # ── GitHub Models ──────────────────────────────────────────────────────
    "gpt-4o": {
        "api_model": "openai/gpt-4o",
        "provider": LLMProvider.GITHUB,
        "type": "non_compound",
        "max_output_tokens": 3900,
        "rpm": 10,
        "rpd": 50,
        "vision": True,
        "web_search": False,
        "is_default": False,
        "display_name": "GPT-4o",
        "description": "OpenAI GPT-4o",
    },
    "gpt-4o-mini": {
        "api_model": "openai/gpt-4o-mini",
        "provider": LLMProvider.GITHUB,
        "type": "non_compound",
        "max_output_tokens": 3900,
        "rpm": 15,
        "rpd": 150,
        "vision": True,
        "web_search": False,
        "is_default": False,
        "display_name": "GPT-4o Mini",
        "description": "OpenAI GPT-4o Mini",
    },
    # ── Groq Models ────────────────────────────────────────────────────────
    "compound": {
        "api_model": "groq/compound",
        "provider": LLMProvider.GROQ,
        "type": "compound",
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 250,
        "vision": False,
        "web_search": True,
        "is_default": False,
        "display_name": "Compound",
        "description": "Groq Compound",
    },
    "compound-mini": {
        "api_model": "groq/compound-mini",
        "provider": LLMProvider.GROQ,
        "type": "compound",
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 250,
        "vision": False,
        "web_search": True,
        "is_default": False,
        "display_name": "Compound Mini",
        "description": "Groq Compound Mini",
    },
    "llama-scout-4": {
        "api_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "provider": LLMProvider.GROQ,
        "type": "non_compound",
        "max_output_tokens": 8000,
        "rpm": 30,
        "rpd": 1000,
        "vision": True,
        "web_search": False,
        "is_default": True,
        "display_name": "Llama 4 Scout",
        "description": "Meta Llama 4 Scout",
    },
    "gpt-oss-120b": {
        "api_model": "openai/gpt-oss-120b",
        "provider": LLMProvider.GROQ,
        "type": "non_compound",
        "max_output_tokens": 4000,
        "rpm": 30,
        "rpd": 1000,
        "vision": False,
        "web_search": False,
        "is_default": False,
        "reasoning_effort": "low",
        "display_name": "GPT OSS 120B",
        "description": "OpenAI GPT OSS 120B",
    },
    "kimi-k2": {
        "api_model": "moonshotai/kimi-k2-instruct-0905",
        "provider": LLMProvider.GROQ,
        "type": "non_compound",
        "max_output_tokens": 8000,
        "rpm": 60,
        "rpd": 1000,
        "vision": False,
        "web_search": False,
        "is_default": False,
        "display_name": "Kimi K2",
        "description": "Moonshot Kimi K2 Instruct",
    },
    "gpt-4.1-nano": {
        "api_model": "openai/gpt-4.1-nano",
        "provider": LLMProvider.GITHUB,
        "type": "non_compound",
        "max_output_tokens": 3900,
        "rpm": 15,
        "rpd": 150,
        "vision": False,
        "web_search": False,
        "is_default": False,
        "display_name": "GPT-4.1 Nano",
        "description": "OpenAI GPT-4.1 Nano — fast, lightweight model for column suggestions",
    },
}


# ── Behavior Modes (tuned for dataset generation) ──────────────────────────────
# DataForgeAI uses these for controlling generation quality/creativity.
# "precise"  → deterministic structured data output
# "balanced" → good mix of variety and accuracy
# "creative" → maximum variety in synthetic data
BEHAVIOR_MODES = {
    "precise":   {"temperature": 0.3,  "top_p": 0.85},
    "balanced":  {"temperature": 0.55, "top_p": 0.9},
    "creative":  {"temperature": 0.9,  "top_p": 0.95},
}

DEFAULT_BEHAVIOR_MODE = "balanced"

# Map DataForgeAI data modes to behavior modes
DATA_MODE_TO_BEHAVIOR = {
    "synthetic": "creative",
    "realistic": "balanced",
    "hybrid":    "balanced",
    "live_data": "precise",
}

# ── Default models ──────────────────────────────────────────────────────────────
DEFAULT_CHAT_MODEL = "llama-scout-4"
DEFAULT_GEN_MODEL = "gpt-4o-mini"
COLUMN_SUGGEST_MODEL = "gpt-4.1-nano"


def resolve_behavior(data_mode: str) -> dict:
    """Resolve sampling parameters from data mode."""
    behavior = DATA_MODE_TO_BEHAVIOR.get(data_mode, DEFAULT_BEHAVIOR_MODE)
    if behavior not in BEHAVIOR_MODES:
        logger.warning("Unknown behavior '%s', falling back to '%s'", behavior, DEFAULT_BEHAVIOR_MODE)
        behavior = DEFAULT_BEHAVIOR_MODE
    return {**BEHAVIOR_MODES[behavior], "resolved_mode": behavior}


def get_model_ids() -> list[str]:
    return list(MODEL_CONFIG.keys())


def get_provider(model: str) -> LLMProvider:
    cfg = MODEL_CONFIG.get(model)
    return cfg["provider"] if cfg else LLMProvider.GITHUB


def get_api_model_name(model: str) -> str:
    cfg = MODEL_CONFIG.get(model)
    return cfg["api_model"] if cfg else model


def get_max_output_tokens(model: str) -> int:
    cfg = MODEL_CONFIG.get(model)
    return cfg["max_output_tokens"] if cfg else 1000


def get_rpm(model: str) -> int:
    cfg = MODEL_CONFIG.get(model)
    return cfg["rpm"] if cfg else 10


def get_rpd(model: str) -> int:
    cfg = MODEL_CONFIG.get(model)
    return cfg["rpd"] if cfg else 50


def get_reasoning_effort(model: str) -> Optional[str]:
    cfg = MODEL_CONFIG.get(model)
    return cfg.get("reasoning_effort") if cfg else None


def is_vision_model(model: str) -> bool:
    cfg = MODEL_CONFIG.get(model)
    return cfg.get("vision", False) if cfg else False


def is_web_search_model(model: str) -> bool:
    cfg = MODEL_CONFIG.get(model)
    return cfg.get("web_search", False) if cfg else False


def is_compound_model(model: str) -> bool:
    cfg = MODEL_CONFIG.get(model)
    return cfg.get("type") == "compound" if cfg else False


def get_default_model() -> str:
    for mid, cfg in MODEL_CONFIG.items():
        if cfg.get("is_default"):
            return mid
    return DEFAULT_CHAT_MODEL


def get_display_order() -> list[str]:
    return [
        "compound", "compound-mini", "llama-scout-4",
        "kimi-k2", "gpt-oss-120b",
        "gpt-4o", "gpt-4o-mini",
    ]


def get_fallback_order() -> list[str]:
    return [
        "llama-scout-4", "kimi-k2", "compound", "compound-mini",
        "gpt-4o-mini", "gpt-oss-120b", "gpt-4o",
    ]


def get_model_metadata() -> dict:
    return {
        mid: {
            "name": cfg["display_name"],
            "provider": cfg["provider"].value,
            "description": cfg["description"],
            "vision": cfg.get("vision", False),
            "web_search": cfg.get("web_search", False),
            "is_default": cfg.get("is_default", False),
        }
        for mid, cfg in MODEL_CONFIG.items()
    }
