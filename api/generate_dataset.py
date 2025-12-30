from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import csv
import io
import base64
import decimal
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False
from .generate_preview import generate_AI_preview, generate_fake_preview
from .github_ai import DEFAULT_MODEL, is_model_available_for_user

class Column(BaseModel):
    name: str
    type: str

class DownloadDatasetRequest(BaseModel):
    columns: List[Column]
    rows: int
    format: str
    source: str = "AI"
    keyword: str = ""
    model_id: Optional[str] = None

    model_config = {
        "protected_namespaces": ()
    }

class DownloadDatasetResponse(BaseModel):
    dataset: Any

def generate_dataset(
    columns: List[Column],
    rows: int,
    format: str,
    source: str = "AI",
    keyword: str = "",
    user_id: Optional[str] = None,
    model_id: Optional[str] = None,
    is_authenticated: bool = False,
) -> Any:
    
    columns_dict = [{"name": col.name, "type": col.type} for col in columns]
    
    if source == "AI":
        requested_model = model_id
        if requested_model and not is_model_available_for_user(requested_model, is_authenticated):
            requested_model = DEFAULT_MODEL

        dataset_records = generate_AI_preview(columns_dict, rows, keyword, user_id, model_id=requested_model)
    else:
        dataset_records = generate_fake_preview(columns_dict, rows)
    
    if not dataset_records:
        return [] if format.lower() == 'json' else ""
    
    if format.lower() == 'json':
        cleaned_records = []
        for record in dataset_records:
            cleaned_record = {}
            for key, value in record.items():
                if isinstance(value, (decimal.Decimal, float)):
                    cleaned_record[key] = float(value)
                elif value is None:
                    cleaned_record[key] = None
                else:
                    cleaned_record[key] = value
            cleaned_records.append(cleaned_record)
        return cleaned_records
    elif format.lower() == 'sql':
        if keyword:
            sanitized_keyword = ''.join(c if c.isalnum() or c == '_' else '_' for c in keyword)
            table_name = f"{sanitized_keyword.lower()}_data"
        else:
            table_name = "generated_data"
        
        column_definitions = []
        for column in columns:
            col_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in column.name)
            
            if column.type in ['String', 'Email', 'Name', 'City', 'Country', 'State', 'Company Name', 'Job Title', 'Department', 'Username', 'Domain', 'Word', 'Color']:
                column_definitions.append(f"`{col_name}` VARCHAR(255)")
            elif column.type in ['Address', 'Paragraph', 'Sentence']:
                column_definitions.append(f"`{col_name}` TEXT")
            elif column.type == 'Number':
                column_definitions.append(f"`{col_name}` INT")
            elif column.type == 'Currency':
                column_definitions.append(f"`{col_name}` DECIMAL(15,2)")
            elif column.type in ['Date', 'Date of Birth']:
                column_definitions.append(f"`{col_name}` DATE")
            elif column.type == 'Boolean':
                column_definitions.append(f"`{col_name}` BOOLEAN")
            elif column.type in ['Latitude', 'Longitude']:
                column_definitions.append(f"`{col_name}` DECIMAL(10,6)")
            elif column.type in ['Phone Number', 'SSN', 'Postal Code']:
                column_definitions.append(f"`{col_name}` VARCHAR(50)")
            elif column.type in ['Credit Card', 'URL', 'IP Address', 'Password', 'Image URL']:
                column_definitions.append(f"`{col_name}` VARCHAR(255)")
            else:
                column_definitions.append(f"`{col_name}` TEXT")
        
        sql_statements = [f"CREATE TABLE `{table_name}` ("]
        for i, col_def in enumerate(column_definitions):
            if i < len(column_definitions) - 1:
                sql_statements.append(f"  {col_def},")
            else:
                sql_statements.append(f"  {col_def}")
        sql_statements.append(");")
        sql_statements.append("")
        
        col_names = ['`' + ''.join(c if c.isalnum() or c == '_' else '_' for c in col.name) + '`' for col in columns]
        
        for record in dataset_records:
            values = []
            for column in columns:
                value = record.get(column.name)
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
            
            sql_statements.append(f"INSERT INTO `{table_name}` ({', '.join(col_names)}) VALUES ({', '.join(values)});")
        
        return "\n".join(sql_statements)
    elif format.lower() == 'csv':
        if not dataset_records:
            return ""
        output = io.StringIO()
        fieldnames = [col.name for col in columns]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for record in dataset_records:
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
    elif format.lower() == 'parquet':
        if not PARQUET_AVAILABLE:
            raise ValueError("Parquet support requires pyarrow. Please install it with: pip install pyarrow")
        if not dataset_records:
            return ""
        
        cleaned_records = []
        for record in dataset_records:
            cleaned_record = {}
            for key, value in record.items():
                if isinstance(value, decimal.Decimal):
                    cleaned_record[key] = float(value)
                else:
                    cleaned_record[key] = value
            cleaned_records.append(cleaned_record)
        
        table = pa.Table.from_pylist(cleaned_records)
        output = io.BytesIO()
        pq.write_table(table, output, compression='snappy')
        return base64.b64encode(output.getvalue()).decode('utf-8')
    
    return dataset_records
