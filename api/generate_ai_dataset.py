from pydantic import BaseModel
from typing import Any, List, Dict, Optional
import re
import json
import os
import csv
import io
import base64
from dotenv import load_dotenv
from .github_ai import generate_completion, DEFAULT_MODEL, POWERFUL_MODEL, is_model_available_for_user

# Import model limits service
from services.model_limits import (
    check_and_get_model, 
    record_model_usage, 
    get_status_message_text
)

# Try to import pyarrow for Parquet support
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))


def convert_json_to_csv(data: List[Dict]) -> str:
    if not data:
        return ""
    output = io.StringIO()
    fieldnames = list(data[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for record in data:
        clean_record = {}
        for key, value in record.items():
            if value is None:
                clean_record[key] = ''
            elif isinstance(value, (int, float, bool)):
                clean_record[key] = value
            else:
                clean_record[key] = str(value).replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
        writer.writerow(clean_record)
    return output.getvalue()


def convert_json_to_sql(data: List[Dict], table_name: str = "generated_data") -> str:
    if not data:
        return ""
    
    sanitized_table_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in table_name)
    columns = list(data[0].keys())
    sanitized_columns = [''.join(c if c.isalnum() or c == '_' else '_' for c in col) for col in columns]
    
    column_definitions = []
    for col in sanitized_columns:
        sample_value = data[0].get(columns[sanitized_columns.index(col)])
        if isinstance(sample_value, int):
            column_definitions.append(f"`{col}` INT")
        elif isinstance(sample_value, float):
            column_definitions.append(f"`{col}` DECIMAL(15,2)")
        elif isinstance(sample_value, bool):
            column_definitions.append(f"`{col}` BOOLEAN")
        else:
            column_definitions.append(f"`{col}` TEXT")
    
    sql_statements = [f"CREATE TABLE `{sanitized_table_name}` ("]
    for i, col_def in enumerate(column_definitions):
        if i < len(column_definitions) - 1:
            sql_statements.append(f"  {col_def},")
        else:
            sql_statements.append(f"  {col_def}")
    sql_statements.append(");")
    sql_statements.append("")
    
    quoted_cols = [f"`{col}`" for col in sanitized_columns]
    
    for record in data:
        values = []
        for col in columns:
            value = record.get(col)
            if value is None:
                values.append('NULL')
            elif isinstance(value, bool):
                values.append('TRUE' if value else 'FALSE')
            elif isinstance(value, str):
                escaped_value = value.replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n").replace("\r", "\\r")
                values.append(f"'{escaped_value}'")
            elif isinstance(value, (int, float)):
                values.append(str(value))
            else:
                escaped_value = str(value).replace("\\", "\\\\").replace("'", "''")
                values.append(f"'{escaped_value}'")
        
        sql_statements.append(f"INSERT INTO `{sanitized_table_name}` ({', '.join(quoted_cols)}) VALUES ({', '.join(values)});")
    
    return "\n".join(sql_statements)


def convert_json_to_parquet(data: List[Dict]) -> str:
    if not PARQUET_AVAILABLE:
        raise ValueError("Parquet support requires pyarrow. Please install it with: pip install pyarrow")
    if not data:
        return ""
    table = pa.Table.from_pylist(data)
    output = io.BytesIO()
    pq.write_table(table, output, compression='snappy')
    return base64.b64encode(output.getvalue()).decode('utf-8')


class AiDatasetRequest(BaseModel):
    prompt: str
    type: str = "chat"
    model_id: Optional[str] = None
    format: Optional[str] = "json"

    model_config = {
        "protected_namespaces": ()
    }

class AiDatasetResponse(BaseModel):
    dataset: Any
    metadata: Dict[str, Any]

def generate_ai_only_dataset_from_prompt(prompt: str, model_id: str = DEFAULT_MODEL, output_format: str = "json") -> Dict[str, Any]:
    """
    Generate complete dataset in a SINGLE API call.
    Optimized for efficiency - one call generates all rows at once.
    """
    try:
        format_type = output_format.lower() if output_format else 'json'
        prompt_lower = prompt.lower()
        
        # Only override format if explicitly mentioned in prompt
        if 'sql' in prompt_lower and format_type == 'json':
            format_type = 'sql'
        elif ('mongodb' in prompt_lower or 'mongo' in prompt_lower) and format_type == 'json':
            format_type = 'mongodb'
        
        # Extract row count from prompt
        rows_match = re.search(r'(\d+)\s*rows?', prompt_lower)
        num_rows = int(rows_match.group(1)) if rows_match else 10
        
        # Extract column count from prompt
        cols_match = re.search(r'(\d+)\s*columns?', prompt_lower)
        num_cols = int(cols_match.group(1)) if cols_match else None
        
        # Handle text numbers
        text_numbers = {
            'ten': 10, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
            'hundred': 100, 'thousand': 1000, 'five hundred': 500,
            'two hundred': 200, 'three hundred': 300
        }
        for text, num in text_numbers.items():
            if text in prompt_lower:
                if 'row' in prompt_lower[prompt_lower.find(text):prompt_lower.find(text)+20]:
                    num_rows = num
        
        # Calculate appropriate max_tokens based on dataset size
        # Estimate: ~40 tokens per row for JSON (optimized)
        estimated_tokens = min(num_rows * 60, 8000)
        
        system_prompt = """Generate realistic datasets as JSON arrays only. No explanations."""
        
        col_instruction = f"with {num_cols} columns" if num_cols else ""
        
        user_prompt = f"""Generate {num_rows} rows {col_instruction} for: "{prompt}"
Output ONLY valid JSON array, no markdown:
[{{"col1":"val1",...}},...]"""

        # Optimized timeout based on row count
        timeout = 60 if num_rows <= 50 else 120 if num_rows <= 200 else 180
        
        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=model_id,
            temperature=0.5,
            max_tokens=estimated_tokens,
            timeout=timeout
        )
        
        if not response:
            raise Exception("Empty response from AI")
        
        generated_text = response.strip()
        
        # Clean response - remove markdown code blocks if present
        if generated_text.startswith('```'):
            lines = generated_text.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            generated_text = '\n'.join(lines)
        
        # Remove any "json" prefix
        if generated_text.startswith('json'):
            generated_text = generated_text[4:].strip()
        
        # Always try to parse as JSON first, then convert to requested format
        try:
            parsed_data = json.loads(generated_text)
            if not isinstance(parsed_data, list):
                parsed_data = [parsed_data] if isinstance(parsed_data, dict) else []
            
            # Convert to the requested format
            if format_type == 'json':
                return {
                    'data': parsed_data,
                    'format': format_type,
                    'raw_text': generated_text,
                    'rows_requested': num_rows,
                    'rows_generated': len(parsed_data),
                    'api_calls': 1
                }
            elif format_type == 'csv':
                csv_data = convert_json_to_csv(parsed_data)
                return {
                    'data': csv_data,
                    'format': format_type,
                    'raw_text': csv_data,
                    'rows_requested': num_rows,
                    'rows_generated': len(parsed_data),
                    'api_calls': 1,
                    'column_info': list(parsed_data[0].keys()) if parsed_data else []
                }
            elif format_type == 'sql':
                # Extract table name from prompt
                table_name = "generated_data"
                prompt_words = prompt.lower().split()
                for word in ['customer', 'employee', 'product', 'user', 'order', 'student', 'sales']:
                    if word in prompt_words:
                        table_name = f"{word}_data"
                        break
                sql_data = convert_json_to_sql(parsed_data, table_name)
                return {
                    'data': sql_data,
                    'format': format_type,
                    'raw_text': sql_data,
                    'rows_requested': num_rows,
                    'rows_generated': len(parsed_data),
                    'api_calls': 1,
                    'column_info': list(parsed_data[0].keys()) if parsed_data else []
                }
            elif format_type == 'parquet':
                try:
                    parquet_data = convert_json_to_parquet(parsed_data)
                    return {
                        'data': parquet_data,
                        'format': format_type,
                        'raw_text': f"Parquet binary data ({len(parsed_data)} rows)",
                        'rows_requested': num_rows,
                        'rows_generated': len(parsed_data),
                        'api_calls': 1,
                        'column_info': list(parsed_data[0].keys()) if parsed_data else []
                    }
                except Exception as e:
                    # Fall back to JSON if Parquet conversion fails
                    return {
                        'data': parsed_data,
                        'format': 'json',
                        'raw_text': generated_text,
                        'rows_requested': num_rows,
                        'rows_generated': len(parsed_data),
                        'api_calls': 1,
                        'error': f'Parquet conversion failed: {str(e)}. Returning JSON instead.'
                    }
            else:
                # Default to returning parsed JSON data
                return {
                    'data': parsed_data,
                    'format': 'json',
                    'raw_text': generated_text,
                    'rows_requested': num_rows,
                    'rows_generated': len(parsed_data),
                    'api_calls': 1
                }
        except json.JSONDecodeError:
            return {
                'data': [],
                'format': 'error',
                'raw_text': generated_text,
                'error': 'Failed to parse JSON response',
                'api_calls': 1
            }
            
    except TimeoutError:
        raise Exception("AI request timed out. Please try again with a smaller dataset or simpler request.")
    except Exception as e:
        if "timeout" in str(e).lower():
            raise Exception("AI request timed out. Please try again with a smaller dataset or simpler request.")
        raise Exception(f"Failed to generate AI dataset: {str(e)}")

def generate_ai_dataset(
    prompt: str, 
    type: str = "chat", 
    model_id: str = None, 
    is_authenticated: bool = False, 
    output_format: str = "json",
    user_id: str = None
) -> Dict[str, Any]:
    """
    Generate AI dataset with invisible model limiting.
    
    Args:
        prompt: The user's prompt
        type: Generation type (chat, etc.)
        model_id: Requested model ID
        is_authenticated: Whether user is authenticated
        output_format: Output format (json, csv, sql, parquet)
        user_id: Internal user ID for usage tracking (from users.id)
    """
    try:
        if model_id is None:
            model_id = DEFAULT_MODEL
        
        # Legacy auth check (still needed for model availability)
        if model_id == POWERFUL_MODEL and not is_authenticated:
            model_id = DEFAULT_MODEL
        
        # Apply invisible model limiting
        # This checks usage limits and falls back to alternative models if needed
        actual_model, status_code = check_and_get_model(user_id, model_id)
        
        # Handle case where all models are unavailable (very rare)
        if actual_model is None:
            status_message = get_status_message_text(status_code)
            return {
                'dataset': [],
                'metadata': {
                    'title': "Service Temporarily Unavailable",
                    'description': status_message or "Our AI models are currently at capacity. Please try again shortly.",
                    'error': 'all_models_unavailable',
                    'ai_generated': True,
                    'rows': 0,
                    'columns': 0,
                    'format': 'JSON',
                    'column_info': []
                }
            }
        
        # Use the determined model (may be different from requested due to limits)
        result = generate_ai_only_dataset_from_prompt(prompt, actual_model, output_format)
        
        # Record usage AFTER successful generation
        # This ensures we only count successful API calls
        record_model_usage(user_id, actual_model)
        
        prompt_lower = prompt.lower()
        
        rows_match = re.search(r'(\d+)\s*rows?', prompt_lower)
        estimated_rows = int(rows_match.group(1)) if rows_match else None
        
        cols_match = re.search(r'(\d+)\s*columns?', prompt_lower)
        estimated_cols = int(cols_match.group(1)) if cols_match else None
        
        actual_rows = result.get('rows_generated', 0)
        actual_cols = 0
        
        if result['format'] == 'json' and isinstance(result.get('data'), list):
            actual_rows = len(result['data'])
            if actual_rows > 0 and isinstance(result['data'][0], dict):
                actual_cols = len(result['data'][0].keys())
        elif result['format'] in ['csv', 'sql', 'parquet']:
            actual_rows = result.get('rows_generated', estimated_rows or 0)
            actual_cols = len(result.get('column_info', [])) if result.get('column_info') else estimated_cols
        elif result['format'] == 'error':
            return {
                'dataset': [],
                'metadata': {
                    'title': "Dataset Generation Error",
                    'description': f"I generated data but couldn't parse it properly. Raw response: {result.get('raw_text', '')[:200]}...",
                    'error': result.get('error', 'Unknown parsing error'),
                    'ai_generated': True,
                    'rows': 0,
                    'columns': 0,
                    'format': 'JSON',
                    'column_info': []
                }
            }
        
        dataset_type = "dataset"
        if 'customer' in prompt_lower:
            dataset_type = "customer dataset"
        elif 'student' in prompt_lower:
            dataset_type = "student dataset" 
        elif 'employee' in prompt_lower:
            dataset_type = "employee dataset"
        elif 'order' in prompt_lower or 'sales' in prompt_lower:
            dataset_type = "sales dataset"
        elif 'product' in prompt_lower:
            dataset_type = "product dataset"
        
        description = f"Perfect! I've created a comprehensive {dataset_type} based on your request: '{prompt}'. "
        
        if actual_rows > 0:
            description += f"The dataset contains {actual_rows} rows"
            if actual_cols > 0:
                description += f" and {actual_cols} columns"
            description += f" in {result['format'].upper()} format. "
        elif estimated_rows:
            description += f"I've generated {estimated_rows} rows"
            if estimated_cols:
                description += f" with {estimated_cols} columns"
            description += f" in {result['format'].upper()} format. "
        
        description += "The data includes realistic values with proper relationships and data types. Is there anything you'd like me to adjust or modify?"
        
        column_info = []
        # Get column info from result if available (for non-JSON formats)
        if result.get('column_info'):
            column_info = [{'name': col, 'type': 'String'} for col in result['column_info']]
        elif result['format'] == 'json' and isinstance(result.get('data'), list) and actual_rows > 0:
            first_row = result['data'][0]
            if isinstance(first_row, dict):
                for col_name in first_row.keys():
                    value = first_row[col_name]
                    if isinstance(value, int):
                        data_type = "Number"
                    elif isinstance(value, float):
                        data_type = "Number"
                    elif isinstance(value, bool):
                        data_type = "Boolean"
                    elif isinstance(value, str):
                        if '@' in value and '.' in value:
                            data_type = "Email"
                        elif len(value) > 50:
                            data_type = "Paragraph"
                        else:
                            data_type = "String"
                    else:
                        data_type = "String"
                    
                    column_info.append({
                        'name': col_name,
                        'type': data_type
                    })
        
        metadata = {
            'title': f"{dataset_type.title()}",
            'description': description,
            'rows': actual_rows or estimated_rows or "Generated as requested",
            'columns': actual_cols or estimated_cols or "Generated as requested", 
            'format': result['format'].upper(),
            'size': f"~{len(result['raw_text']) // 1024}KB" if len(result['raw_text']) > 1024 else f"{len(result['raw_text'])} bytes",
            'filename': f"dataset_{result['format']}.{result['format'] if result['format'] != 'mongodb' else 'json'}",
            'ai_generated': True,
            'conversation_context': "Generated using natural language processing",
            'column_info': column_info
        }
        
        return {
            'dataset': result['data'],
            'metadata': metadata
        }
        
    except Exception as e:
        return {
            'dataset': [],
            'metadata': {
                'title': "Dataset Generation Error",
                'description': f"I apologize, but I encountered an issue while generating your dataset: {str(e)}. Please try rephrasing your request or check if all required parameters are provided.",
                'error': str(e),
                'ai_generated': True,
                'rows': 0,
                'columns': 0,
                'format': 'JSON',
                'column_info': []
            }
        }
