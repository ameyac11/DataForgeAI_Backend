"""PromptBuilder — assembles system prompts per request.

system prompt = execution block + generation block + security block

Imports model knowledge from llm.model_config (not hardcoded).
"""

from llm.model_config import is_compound_model
from final_prompt.prompts import (
    EXECUTION_BLOCK_CHAT_PREVIEW,
    EXECUTION_BLOCK_CHAT_DOWNLOAD,
    EXECUTION_BLOCK_CUSTOM_DOWNLOAD,
    GENERATION_BLOCK_SYNTHETIC,
    GENERATION_BLOCK_REALISTIC,
    GENERATION_BLOCK_HYBRID,
    GENERATION_BLOCK_LIVE_DATA,
    SECURITY_BLOCK,
)

EXECUTION_BLOCKS = {
    "chat_preview": EXECUTION_BLOCK_CHAT_PREVIEW,
    "chat_download": EXECUTION_BLOCK_CHAT_DOWNLOAD,
    "custom_download": EXECUTION_BLOCK_CUSTOM_DOWNLOAD,
}

GENERATION_BLOCKS = {
    "synthetic": GENERATION_BLOCK_SYNTHETIC,
    "realistic": GENERATION_BLOCK_REALISTIC,
    "hybrid": GENERATION_BLOCK_HYBRID,
    "live_data": GENERATION_BLOCK_LIVE_DATA,
}


def build_system_prompt(execution_mode: str, generation_mode: str, model_id: str) -> str:
    """Build a complete system prompt from execution + generation + security blocks.

    Args:
        execution_mode: "chat_preview" | "chat_download" | "custom_download"
        generation_mode: "synthetic" | "realistic" | "hybrid" | "live_data"
        model_id: used for compound detection — forces live_data
    """
    # compound models always use live_data regardless of what frontend sent
    if is_compound_model(model_id):
        generation_mode = "live_data"

    execution_block = EXECUTION_BLOCKS.get(execution_mode, EXECUTION_BLOCK_CUSTOM_DOWNLOAD)
    generation_block = GENERATION_BLOCKS.get(generation_mode, GENERATION_BLOCK_SYNTHETIC)

    return f"{execution_block}\n\n{generation_block}\n\n{SECURITY_BLOCK}"
