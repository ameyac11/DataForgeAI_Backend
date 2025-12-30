import os
import json
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
from .github_ai import generate_completion, FAST_MODEL

# Import model limits for usage tracking
from services.model_limits import check_and_get_model, record_model_usage

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

class GenerateColumnsRequest(BaseModel):
    topic: str = ""
    availableTypes: List[str]
    strategy: str = "ai"  
    template: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "topic": "users",
                "availableTypes": ["String", "Number", "Email", "Date"],
                "strategy": "ai",
                "template": ""
            }
        }

class ColumnDefinition(BaseModel):
    name: str
    type: str

class GenerateColumnsResponse(BaseModel):
    columns: List[ColumnDefinition] = []

    class Config:
        json_schema_extra = {
            "example": {
                "columns": [
                    {"name": "id", "type": "Number"},
                    {"name": "email", "type": "Email"}
                ]
            }
        }

def search_columns(topic: str, available_types: List[str], strategy: str = "ai", template: str = "", user_id: Optional[str] = None) -> List[ColumnDefinition]:
    """
    Search/generate columns for a topic.
    Tracks model usage when using AI strategy.
    """
    def get_default_columns() -> List[ColumnDefinition]:
        return [
            ColumnDefinition(
                name=f"{topic.lower()}_id",
                type="Number"
            ),
            ColumnDefinition(
                name="name",
                type="String"
            ),
            ColumnDefinition(
                name="created_at",
                type="Date"
            )
        ]
    
    try:
        if strategy == "template":
            templates = {
                "user": [
                    {"name": "user_id", "type": "Number"},
                    {"name": "email", "type": "Email"},
                    {"name": "full_name", "type": "String"},
                    {"name": "date_of_birth", "type": "Date"},
                    {"name": "address", "type": "Address"},
                    {"name": "phone_number", "type": "Phone Number"},
                    {"name": "created_at", "type": "Date"}
                ],
                "product": [
                    {"name": "product_id", "type": "Number"},
                    {"name": "name", "type": "String"},
                    {"name": "price", "type": "Currency"},
                    {"name": "description", "type": "String"},
                    {"name": "category", "type": "String"},
                    {"name": "stock_quantity", "type": "Number"},
                    {"name": "created_at", "type": "Date"}
                ],
                "transaction": [
                    {"name": "transaction_id", "type": "Number"},
                    {"name": "amount", "type": "Currency"},
                    {"name": "transaction_date", "type": "Date"},
                    {"name": "description", "type": "String"},
                    {"name": "sender", "type": "String"},
                    {"name": "recipient", "type": "String"},
                    {"name": "status", "type": "String"}
                ]
            }
            template_key = template.lower()
            if template_key in templates:
                try:
                    valid_columns = []
                    for col in templates[template_key]:
                        if col['type'] in available_types:
                            try:
                                valid_columns.append(ColumnDefinition(**col))
                            except Exception as e:
                                print(f"Error creating column from template: {e}")
                                continue
                    
                    if not valid_columns:
                        print(f"No valid columns found in template {template}")
                        return []
                    
                    return valid_columns
                except Exception as e:
                    print(f"Error processing template {template}: {e}")
                    return []
            else:
                print(f"Template {template} not found")
                return []

        # Check model availability and get fallback if needed
        actual_model, _ = check_and_get_model(user_id, FAST_MODEL)
        if actual_model is None:
            actual_model = FAST_MODEL

        system_prompt = "Generate JSON for database schemas. Output only valid JSON."
        
        user_prompt = f"""Generate columns for "{topic}" table.
Types: {', '.join(available_types)}
Return JSON: {{"columns":[{{"name":"col_name","type":"Type"}}]}}
Requirements: 5-8 columns, snake_case names, only listed types."""

        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=actual_model,
            temperature=0.5,
            max_tokens=1500,
            timeout=45
        )
        
        # Record usage after successful generation
        record_model_usage(user_id, actual_model)

        if not response:
            print("Empty response from model")
            return get_default_columns()

        text = response.strip()
        
        if text.startswith('```') and text.endswith('```'):
            text = text[3:-3].strip()
            if text.startswith('json'):
                text = text.replace('json', '', 1).strip()

        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                text = text[start:end]

            data = json.loads(text)
            
            if not isinstance(data, dict):
                print(f"Invalid response format: not a dictionary")
                return get_default_columns()

            columns = []
            for col in data.get('columns', []):
                if not isinstance(col, dict):
                    continue

                name = col.get('name', '').strip().lower().replace(' ', '_')
                col_type = col.get('type', '').strip()

                if not name or not col_type:
                    continue

                if col_type not in available_types:
                    continue

                try:
                    columns.append(ColumnDefinition(
                        name=name,
                        type=col_type
                    ))
                except Exception as e:
                    print(f"Error creating column: {str(e)}")
                    continue

            if not columns:
                print("No valid columns found in response")
                return [
                    ColumnDefinition(
                        name=f"{topic.lower()}_id",
                        type="Number"
                    ),
                    ColumnDefinition(
                        name="name",
                        type="String"
                    ),
                    ColumnDefinition(
                        name="created_at",
                        type="Date"
                    )
                ]

            return columns

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {str(e)}")
            print(f"Raw text: {text}")
        except Exception as e:
            print(f"Error processing response: {str(e)}")

            return get_default_columns()
            
    except Exception as e:
        print(f"Error processing response: {e}")
        return get_default_columns()

def generate_columns(topic: str, available_types: List[str], strategy: str = "ai", template: str = "", user_id: Optional[str] = None) -> GenerateColumnsResponse:
    """
    Generate columns for a dataset.
    
    Args:
        topic: The topic/table name
        available_types: List of available column types
        strategy: 'ai' or 'template'
        template: Template name if strategy is 'template'
        user_id: User ID or anonymous session ID for usage tracking
    """
    try:
        if not available_types:
            return GenerateColumnsResponse(columns=[])
        
        if strategy == "ai" and not topic:
            return GenerateColumnsResponse(columns=[])
        
        if strategy == "template" and not template:
            return GenerateColumnsResponse(columns=[])
        
        columns = search_columns(topic, available_types, strategy, template, user_id)
        return GenerateColumnsResponse(columns=columns)
        
    except Exception as e:
        return GenerateColumnsResponse(columns=[])
