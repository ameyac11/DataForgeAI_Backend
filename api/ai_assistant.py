import os
from typing import List, Optional
from pydantic import BaseModel, validator
from dotenv import load_dotenv
from .github_ai import generate_completion, FAST_MODEL
from services.model_limits import get_model_limits_service

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

class KeywordSearchRequest(BaseModel):
    query: str

class KeywordSearchResponse(BaseModel):
    keywords: List[str]

class PromptEnhanceRequest(BaseModel):
    prompt: str
    
    @validator('prompt')
    def validate_prompt_length(cls, v):
        if not v.strip():
            raise ValueError('Prompt cannot be empty')
        if len(v) > 2000:
            raise ValueError('Prompt must be under 2000 characters for enhancement')
        return v.strip()

class PromptEnhanceResponse(BaseModel):
    enhanced_prompt: str
    original_prompt: str

def generate_keywords(query: str, user_id: Optional[str] = None) -> List[str]:
    """Generate keywords with optional user tracking."""
    # Check and track limit for gpt-4.1-nano (utility functions)
    if user_id:
        service = get_model_limits_service()
        available, reason = service.check_model_available(user_id, FAST_MODEL)
        if not available:
            return []  # Silently return empty - invisible limiting
    
    try:
        system_prompt = "Generate search keywords. Output only comma-separated keywords."
        
        user_prompt = f"""Generate 3-5 dataset search keywords for: "{query}"
Return only keywords, comma-separated, no explanations."""

        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=FAST_MODEL,
            temperature=0.5,
            max_tokens=200,
            timeout=30
        )
        
        if response:
            # Track usage AFTER successful call
            if user_id:
                service = get_model_limits_service()
                service.record_usage(user_id, FAST_MODEL)
            
            keywords = [word.strip().lower() for word in response.replace('\n', ',').split(',')]
            keywords = list(set(keyword for keyword in keywords if keyword and keyword.strip()))
            return keywords
            
    except Exception as e:
        pass
    
    return []

def enhance_prompt(prompt: str, user_id: Optional[str] = None) -> str:
    """Enhance prompt with optional user tracking."""
    # Check and track limit for gpt-4.1-nano (utility functions)
    if user_id:
        service = get_model_limits_service()
        available, reason = service.check_model_available(user_id, FAST_MODEL)
        if not available:
            return prompt  # Silently return original - invisible limiting
    
    try:
        system_prompt = "Enhance dataset prompts to be more specific. Be concise."
        
        user_prompt = f"""Enhance this dataset prompt with specific details (types, ranges, fields).
Keep under 800 chars. Original: "{prompt}"
Return only the enhanced prompt."""

        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=FAST_MODEL,
            temperature=0.5,
            max_tokens=1000,
            timeout=45
        )
        
        if response:
            # Track usage AFTER successful call
            if user_id:
                service = get_model_limits_service()
                service.record_usage(user_id, FAST_MODEL)
            
            enhanced = response.strip()
            enhanced = enhanced.strip('"').strip("'").strip()
            
            if len(enhanced) > 1500:
                enhanced = enhanced[:1497] + "..."
                
            return enhanced
        else:
            return prompt
            
    except Exception as e:
        return prompt

def search_keywords(query: str, user_id: Optional[str] = None) -> List[str]:
    """Search keywords API with user tracking."""
    if not query:
        return []
        
    keywords = generate_keywords(query, user_id)
    return keywords[:10]

def enhance_prompt_api(prompt: str, user_id: Optional[str] = None) -> str:
    """Enhance prompt API with user tracking."""
    if not prompt:
        return ""
        
    enhanced = enhance_prompt(prompt, user_id)
    return enhanced