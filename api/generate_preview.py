from pydantic import BaseModel
from typing import List, Any, Optional
from faker import Faker
from dotenv import load_dotenv
import os
import json
from .github_ai import generate_completion, FAST_MODEL

# Import model limits for usage tracking
from services.model_limits import check_and_get_model, record_model_usage

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

class PreviewRequest(BaseModel):
    source: str
    columns: List[dict]
    rows: int
    format: str
    keyword: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "source": "AI",
                "columns": [
                    {"name": "id", "type": "Number"},
                    {"name": "name", "type": "String"},
                    {"name": "email", "type": "Email"}
                ],
                "rows": 5,
                "format": "json",
                "keyword": "users"
            }
        }

class PreviewResponse(BaseModel):
    data: List[dict]

def generate_AI_preview(
    columns: List[dict],
    rows: int,
    keyword: str,
    user_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> List[dict]:
    """
    Generate preview data in a SINGLE API call.
    Optimized for speed - generates all rows at once.
    Tracks model usage for the user.
    """
    try:
        # Preview defaults to FAST_MODEL (gpt-4.1-nano). Download can override via model_id.
        requested_model = model_id or FAST_MODEL

        # Check model availability and get fallback if needed
        actual_model, _ = check_and_get_model(user_id, requested_model)
        if actual_model is None:
            actual_model = requested_model
        
        columns_desc = ", ".join([f"{col.get('name', 'col')}({col.get('type', 'String')})" for col in columns])
        
        # Calculate appropriate max_tokens based on dataset size
        # estimated_tokens = min(rows * 50, 4000)
        estimated_tokens = min(rows * len(columns) * 25, 8000)
        
        system_prompt = (
            "You are a precise data generator. Generate realistic, contextually accurate datasets. "
            "Follow the exact column names and types provided. "
            "For ID columns, use sequential integers starting from 1. "
            "For other numeric columns, use appropriate realistic numbers. "
            "If a keyword is provided, ALL data must match that context. "
            "Output only valid JSON array with proper data types, no explanations or markdown."
        )

        extra_instruction = ""
        if keyword and keyword.strip():
            extra_instruction = (
                f"CRITICAL: All data must be about '{keyword}'. "
                f"Use appropriate names, locations, and values relevant to '{keyword}'. "
                f"For example, if keyword is 'Japan', use Japanese names, Japanese cities, Japanese phone formats, etc. "
                f"Never use generic or unrelated data. "
            )

        user_prompt = (
            f"Generate exactly {rows} rows of data. "
            f"Schema: {columns_desc}. "
            f"{extra_instruction}"
            f"IMPORTANT RULES:\n"
            f"1. For 'id' or similar identifier columns, use sequential integers: 1, 2, 3, ..., {rows}\n"
            f"2. For all other columns, generate realistic data matching the column type\n"
            f"3. Ensure data types are correct: numbers without quotes, strings with quotes\n"
            f"4. Output ONLY a valid JSON array: [{{{columns[0].get('name')}:1,...}},...]"
        )
        
        # Optimized timeout for speed
        timeout = 45 if rows <= 20 else 60 if rows <= 50 else 90
        
        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=actual_model,
            temperature=0.5,
            max_tokens=estimated_tokens,
            timeout=timeout
        )
        
        # Record usage after successful generation
        record_model_usage(user_id, actual_model)
        
        generated_text = response.strip()
        
        # Clean markdown formatting
        if "```json" in generated_text:
            generated_text = generated_text.split("```json")[1].split("```")[0]
        elif "```" in generated_text:
            generated_text = generated_text.split("```")[1].split("```")[0]
        
        try:
            dataset = json.loads(generated_text.strip())
            
            if isinstance(dataset, list) and len(dataset) > 0:
                cleaned_dataset = []
                for i, row in enumerate(dataset[:rows]):
                    cleaned_row = {}
                    for col in columns:
                        col_name = col.get('name', f'column_{i}')
                        col_type = col.get('type', 'String').lower()
                        
                        if col_name in row:
                            value = row[col_name]
                            if col_type in ['number', 'integer', 'int'] and not isinstance(value, int):
                                try:
                                    value = int(str(value).replace(',', '').replace('$', ''))
                                except:
                                    value = 0
                            elif col_type in ['float', 'decimal'] and not isinstance(value, (int, float)):
                                try:
                                    value = float(str(value).replace(',', '').replace('$', ''))
                                except:
                                    value = 0.0
                            elif col_type in ['boolean', 'bool']:
                                if isinstance(value, str):
                                    value = value.lower() in ['true', 'yes', '1']
                                else:
                                    value = bool(value)
                            
                            cleaned_row[col_name] = value
                        else:
                            cleaned_row[col_name] = generate_fake_preview_single(col_name, col.get('type', 'String'), i)
                    
                    cleaned_dataset.append(cleaned_row)
                
                # Fill remaining rows if needed (fallback)
                while len(cleaned_dataset) < rows:
                    row = {}
                    for col in columns:
                        col_name = col.get('name', f'column_{len(cleaned_dataset)}')
                        col_type = col.get('type', 'String')
                        row[col_name] = generate_fake_preview_single(col_name, col_type, len(cleaned_dataset))
                    cleaned_dataset.append(row)
                
                return cleaned_dataset
            else:
                return generate_fake_preview(columns, rows)
                
        except json.JSONDecodeError:
            return generate_fake_preview(columns, rows)
    
    except Exception as e:
        print(f"AI generation failed: {e}")
        return generate_fake_preview(columns, rows)

def generate_fake_preview_single(column_name: str, column_type: str, row_index: int) -> Any:
    fake = Faker()
    
    col_type = column_type.strip()
    col_name = column_name.lower()
    
    if col_type == 'String':
        if 'name' in col_name and not ('user' in col_name or 'first' in col_name or 'last' in col_name):
            return fake.name()
        elif 'first_name' in col_name or 'firstname' in col_name:
            return fake.first_name()
        elif 'last_name' in col_name or 'lastname' in col_name:
            return fake.last_name()
        elif 'title' in col_name:
            return fake.catch_phrase()
        elif 'description' in col_name:
            return fake.text(max_nb_chars=100)
        else:
            return fake.word()
    
    elif col_type == 'Number':
        if 'age' in col_name:
            return fake.random_int(min=18, max=99)
        elif 'id' in col_name:
            return fake.random_int(min=1, max=10000)
        elif 'price' in col_name or 'cost' in col_name or 'amount' in col_name:
            return fake.random_int(min=10, max=1000)
        elif 'year' in col_name:
            return fake.random_int(min=1950, max=2025)
        else:
            return fake.random_int(min=1, max=1000)
    
    elif col_type == 'Boolean':
        return fake.boolean()
    
    elif col_type == 'Date':
        try:
            return fake.date().strftime('%Y-%m-%d')
        except AttributeError:
            return str(fake.date())
    
    elif col_type == 'Email':
        return fake.email()
    
    elif col_type == 'Phone Number':
        return fake.phone_number()
    
    elif col_type == 'Date of Birth':
        try:
            return fake.date_of_birth(minimum_age=18, maximum_age=90).strftime('%Y-%m-%d')
        except AttributeError:
            return str(fake.date_of_birth(minimum_age=18, maximum_age=90))
    
    elif col_type == 'Name':
        if 'first' in col_name or 'fname' in col_name:
            return fake.first_name()
        elif 'last' in col_name or 'lname' in col_name:
            return fake.last_name()
        else:
            return fake.name()
    
    elif col_type == 'Gender':
        return fake.random_element(elements=['Male', 'Female', 'Other'])
    
    elif col_type == 'SSN':
        return fake.ssn()
    
    elif col_type == 'Address':
        return fake.address()
    
    elif col_type == 'City':
        return fake.city()
    
    elif col_type == 'Country':
        return fake.country()
    
    elif col_type == 'State':
        return fake.state()
    
    elif col_type == 'Postal Code':
        return fake.postcode()
    
    elif col_type == 'Latitude':
        return round(fake.latitude(), 6)
    
    elif col_type == 'Longitude':
        return round(fake.longitude(), 6)
    
    elif col_type == 'Company Name':
        return fake.company()
    
    elif col_type == 'Job Title':
        return fake.job()
    
    elif col_type == 'Department':
        return fake.random_element(elements=[
            'Engineering', 'Marketing', 'Sales', 'Human Resources', 'Finance', 
            'Operations', 'Customer Service', 'IT', 'Legal', 'Research & Development'
        ])
    
    elif col_type == 'Currency':
        return f"${fake.random_int(min=10, max=9999)}.{fake.random_int(min=10, max=99):02d}"
    
    elif col_type == 'Credit Card':
        return fake.credit_card_number()
    
    elif col_type == 'URL':
        return fake.url()
    
    elif col_type == 'IP Address':
        return fake.ipv4()
    
    elif col_type == 'Username':
        return fake.user_name()
    
    elif col_type == 'Password':
        return fake.password(length=12)
    
    elif col_type == 'Domain':
        return fake.domain_name()
    
    elif col_type == 'Paragraph':
        return fake.paragraph(nb_sentences=3)
    
    elif col_type == 'Sentence':
        return fake.sentence()
    
    elif col_type == 'Word':
        return fake.word()
    
    elif col_type == 'Image URL':
        return f"https://picsum.photos/{fake.random_int(min=200, max=800)}/{fake.random_int(min=200, max=600)}"
    
    elif col_type == 'Color':
        return fake.color_name()
    
    elif col_type.lower() == 'text':
        return fake.text(max_nb_chars=100)
    elif col_type.lower() in ['integer', 'int']:
        return fake.random_int(min=1, max=1000)
    elif col_type.lower() in ['float', 'decimal']:
        return round(fake.pyfloat(min_value=0, max_value=100, right_digits=2), 2)
    elif col_type.lower() in ['datetime', 'timestamp']:
        try:
            return fake.date_time().strftime('%Y-%m-%d %H:%M:%S')
        except AttributeError:
            return str(fake.date_time())
    elif col_type.lower() in ['phone', 'phonenumber']:
        return fake.phone_number()
    elif col_type.lower() == 'uuid':
        return str(fake.uuid4())
    
    else:
        return fake.word()

def generate_fake_preview(columns: List[dict], rows: int) -> List[dict]:
    dataset = []
    
    for i in range(rows):
        row = {}
        for column in columns:
            column_name = column.get('name', f'column_{i}')
            column_type = column.get('type', 'String')
            row[column_name] = generate_fake_preview_single(column_name, column_type, i)
        dataset.append(row)
    
    return dataset

def generate_preview(source: str, columns: List[dict], rows: int, format: str, keyword: str = "", user_id: Optional[str] = None) -> List[dict]:
    """
    Generate preview data.
    
    Args:
        source: 'AI' for AI generation, anything else for fake data
        columns: List of column definitions
        rows: Number of rows to generate
        format: Output format
        keyword: Context keyword for AI generation
        user_id: User ID or anonymous session ID for usage tracking
    """
    if not columns:
        return []
    
    if source == "AI":
        dataset = generate_AI_preview(columns, rows, keyword, user_id)
    else:
        dataset = generate_fake_preview(columns, rows)
    
    return dataset