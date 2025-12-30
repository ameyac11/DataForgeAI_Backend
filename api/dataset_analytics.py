import os
import json
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from fastapi import UploadFile, HTTPException
import traceback
from datetime import datetime
import re
import warnings
warnings.filterwarnings('ignore')

try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy not available, some statistical features will be limited")

from api.github_ai import generate_completion, ANALYTICS_MODEL
from services.model_limits import check_and_get_model, record_model_usage

# ==================== PYDANTIC MODELS ====================

class DatasetAnalysisRequest(BaseModel):
    pass

class BasicStats(BaseModel):
    total_rows: int = Field(...)
    total_columns: int = Field(...)
    file_size: str = Field(...)
    file_type: str = Field(...)
    memory_usage: str = Field(...)
    encoding: Optional[str] = Field(None)
    data_density: Optional[float] = Field(None)
    estimated_storage_efficiency: Optional[str] = Field(None)

class StatisticalSummary(BaseModel):
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    variance: Optional[float] = None
    min_value: Optional[Union[str, float]] = None
    max_value: Optional[Union[str, float]] = None
    range_value: Optional[float] = None
    q25: Optional[float] = None
    q75: Optional[float] = None
    iqr: Optional[float] = None
    mode: Optional[Union[str, float]] = None
    skewness: Optional[float] = None
    kurtosis: Optional[float] = None
    coefficient_of_variation: Optional[float] = None
    percentile_5: Optional[float] = None
    percentile_95: Optional[float] = None

class ColumnAnalysis(BaseModel):
    name: str = Field(...)
    type: str = Field(...)
    null_count: int = Field(...)
    null_percentage: float = Field(...)
    unique_count: int = Field(...)
    unique_percentage: float = Field(...)
    sample_values: List[str] = Field(...)
    statistical_summary: Optional[StatisticalSummary] = None
    data_patterns: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    entropy: Optional[float] = None
    is_potential_key: bool = False
    is_constant: bool = False

class DataQuality(BaseModel):
    completeness_score: int = Field(...)
    consistency_score: int = Field(...)
    validity_score: int = Field(...)
    uniqueness_score: int = Field(...)
    timeliness_score: int = Field(...)
    overall_score: int = Field(...)
    duplicates: int = Field(...)
    duplicate_percentage: float = Field(...)
    issues: List[str] = Field(...)
    recommendations: List[str] = Field(...)
    quality_grade: str = Field(...)

class CorrelationAnalysis(BaseModel):
    column_pairs: List[Dict[str, Any]] = Field(default_factory=list)
    high_correlations: List[str] = Field(default_factory=list)
    multicollinearity_warning: bool = False

class DistributionAnalysis(BaseModel):
    column_name: str
    distribution_type: str
    normality_test_pvalue: Optional[float] = None
    is_normally_distributed: bool = False
    outlier_count: int = 0
    outlier_percentage: float = 0.0
    outlier_values: List[Any] = Field(default_factory=list)

class AnomalyDetection(BaseModel):
    total_anomalies: int = 0
    anomaly_percentage: float = 0.0
    anomalous_columns: List[str] = Field(default_factory=list)
    anomaly_details: List[Dict[str, Any]] = Field(default_factory=list)

class AIInsights(BaseModel):
    executive_summary: str = Field(...)
    key_findings: List[str] = Field(default_factory=list)
    data_story: str = Field(...)
    actionable_recommendations: List[str] = Field(default_factory=list)
    potential_use_cases: List[str] = Field(default_factory=list)
    data_quality_narrative: str = Field(...)
    advanced_analytics_suggestions: List[str] = Field(default_factory=list)

class DatasetInsights(BaseModel):
    general_insights: List[str] = Field(...)
    statistical_insights: List[str] = Field(...)
    business_insights: List[str] = Field(...)
    data_science_insights: List[str] = Field(...)
    ai_insights: Optional[AIInsights] = None

class DatasetAnalysisResponse(BaseModel):
    basic_stats: BasicStats
    column_analysis: List[ColumnAnalysis]
    data_quality: DataQuality
    insights: DatasetInsights
    correlation_analysis: Optional[CorrelationAnalysis] = None
    distribution_analysis: List[DistributionAnalysis] = Field(default_factory=list)
    anomaly_detection: Optional[AnomalyDetection] = None
    analysis_timestamp: str = Field(...)
    processing_time_ms: int = Field(...)

# ==================== UTILITY FUNCTIONS ====================

def format_file_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f}{size_names[i]}"


def parse_sql_to_dataframe(sql_content: str) -> tuple:
    """Parse SQL content (INSERT statements) to create a pandas DataFrame"""
    import re

    records = []
    columns = None

    # Clean the SQL content - remove extra whitespace and normalize
    sql_content = re.sub(r'\s+', ' ', sql_content.strip())

    # Try to extract column names from CREATE TABLE statement
    create_match = re.search(r'CREATE\s+TABLE\s+\w+\s*\((.*?)\);', sql_content, re.IGNORECASE | re.DOTALL)
    if create_match:
        cols_def = create_match.group(1)
        # Extract column names (first word before the type)
        col_matches = re.findall(r'(\w+)\s+\w+', cols_def)
        if col_matches:
            columns = [col.strip() for col in col_matches]

    # Parse INSERT statements - handle backticks and complex VALUES
    # Pattern to match INSERT INTO statements with optional column list
    insert_pattern = r'INSERT\s+INTO\s+[`"\']?(\w+)[`"\']?\s*(\([^)]+\))?\s*VALUES\s*((?:\([^)]*\)(?:\s*,\s*)?)+)\s*;?'
    insert_match = re.search(insert_pattern, sql_content, re.IGNORECASE | re.DOTALL)

    if insert_match:
        table_name, cols_part, values_part = insert_match.groups()

        # Parse column names if provided
        if cols_part:
            col_matches = re.findall(r'[`"\']?(\w+)[`"\']?', cols_part)
            if col_matches and not columns:
                columns = [col.strip() for col in col_matches]

        # Parse individual VALUES clauses
        values_clauses = re.findall(r'\(([^)]*)\)', values_part)

        for values_str in values_clauses:
            if values_str.strip():  # Skip empty values
                parsed_values = parse_values_string(values_str)
                if parsed_values:
                    records.append(parsed_values)

    # If no records found, try alternative approach - split by INSERT statements
    if not records:
        # Split by INSERT statements and process each one
        insert_statements = re.split(r'(?=INSERT\s+INTO)', sql_content, flags=re.IGNORECASE)
        insert_statements = [stmt for stmt in insert_statements if stmt.strip() and 'INSERT' in stmt.upper()]

        for insert_stmt in insert_statements:
            # Extract VALUES part
            values_match = re.search(r'VALUES\s*((?:\([^)]*\)(?:\s*,\s*)?)+)', insert_stmt, re.IGNORECASE | re.DOTALL)
            if values_match:
                values_part = values_match.group(1)
                values_clauses = re.findall(r'\(([^)]*)\)', values_part)

                for values_str in values_clauses:
                    if values_str.strip():
                        parsed_values = parse_values_string(values_str)
                        if parsed_values:
                            records.append(parsed_values)

    # Last resort: try to find any VALUES patterns
    if not records:
        values_pattern = r'VALUES\s*\(([^)]+)\)'
        all_values = re.findall(values_pattern, sql_content, re.IGNORECASE | re.DOTALL)

        for values_str in all_values:
            parsed_values = parse_values_string(values_str)
            if parsed_values:
                records.append(parsed_values)

    if not records:
        raise ValueError("No data found in SQL file. Please ensure it contains INSERT statements with VALUES clauses.")

    # Create DataFrame
    if columns:
        # Ensure column count matches value count
        max_cols = max(len(r) for r in records) if records else 0
        while len(columns) < max_cols:
            columns.append(f"column_{len(columns)+1}")
        df = pd.DataFrame(records, columns=columns[:max_cols])
    else:
        df = pd.DataFrame(records)

    return df, "SQL"


def parse_values_string(values_str: str) -> list:
    """Parse a VALUES string into a list of values"""
    values = []
    current_value = ""
    in_string = False
    string_char = None
    paren_depth = 0

    i = 0
    while i < len(values_str):
        char = values_str[i]

        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            current_value += char
        elif char == string_char and in_string and (i == 0 or values_str[i-1] != '\\'):  # Handle escaped quotes
            in_string = False
            string_char = None
            current_value += char
        elif char == '(' and not in_string:
            paren_depth += 1
            current_value += char
        elif char == ')' and not in_string:
            paren_depth -= 1
            current_value += char
        elif char == ',' and not in_string and paren_depth == 0:
            # Process the completed value
            val = current_value.strip()
            processed_val = process_sql_value(val)
            values.append(processed_val)
            current_value = ""
        else:
            current_value += char

        i += 1

    # Don't forget the last value
    if current_value.strip():
        val = current_value.strip()
        processed_val = process_sql_value(val)
        values.append(processed_val)

    return values


def process_sql_value(val: str) -> any:
    """Process a single SQL value"""
    val = val.strip()

    # Handle NULL values
    if val.upper() == 'NULL' or val == '':
        return None

    # Handle boolean values
    if val.upper() in ('TRUE', 'FALSE'):
        return val.upper() == 'TRUE'

    # Handle quoted strings
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        # Remove quotes and unescape
        content = val[1:-1]
        content = content.replace("''", "'").replace('\\"', '"').replace('\\\\', '\\')
        return content

    # Handle numbers
    try:
        # Try integer first
        if '.' not in val:
            return int(val)
        else:
            return float(val)
    except ValueError:
        # Not a number, return as string
        return val


def safe_unique_count(series: pd.Series) -> int:
    try:
        return int(series.nunique())
    except TypeError:
        try:
            return int(series.astype(str).nunique())
        except:
            return 0

def safe_unique_values(series: pd.Series, limit: int = 10) -> List[Any]:
    try:
        unique_vals = series.unique()
        return unique_vals[:limit].tolist()
    except TypeError:
        try:
            unique_vals = series.astype(str).unique()
            return unique_vals[:limit].tolist()
        except:
            return ["Complex data type"]

def calculate_entropy(series: pd.Series) -> float:
    """Calculate Shannon entropy for a column - measures information content"""
    try:
        value_counts = series.value_counts(normalize=True)
        entropy = -np.sum(value_counts * np.log2(value_counts + 1e-10))
        return round(float(entropy), 4)
    except:
        return 0.0

def detect_column_type(series: pd.Series) -> str:
    non_null_series = series.dropna()
    
    if len(non_null_series) == 0:
        return "Empty"
    
    if pd.api.types.is_bool_dtype(series):
        return "Boolean"
    
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Date/Time"
    
    if pd.api.types.is_numeric_dtype(series):
        if pd.api.types.is_integer_dtype(series):
            return "Integer"
        else:
            return "Float"
    
    if series.dtype == 'object':
        sample_values = non_null_series.astype(str).str.strip()
        
        try:
            pd.to_numeric(sample_values, errors='raise')
            return "Numeric (as Text)"
        except:
            pass
        
        datetime_patterns = [
            r'\d{4}-\d{2}-\d{2}',
            r'\d{2}/\d{2}/\d{4}',
            r'\d{2}-\d{2}-\d{4}',
        ]
        
        for pattern in datetime_patterns:
            if sample_values.str.match(pattern).any():
                return "Date (as Text)"
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if sample_values.str.match(email_pattern).any():
            return "Email"
        
        url_pattern = r'^https?:\/\/'
        if sample_values.str.match(url_pattern).any():
            return "URL"
        
        phone_pattern = r'^\+?[\d\s\-\(\)]{10,}$'
        if sample_values.str.match(phone_pattern).sum() / len(sample_values) > 0.5:
            return "Phone"
        
        try:
            unique_count = safe_unique_count(non_null_series)
            if unique_count <= 10 and len(non_null_series) > 10:
                return "Categorical"
        except:
            pass
        
        if series.name and ('id' in series.name.lower() or 'key' in series.name.lower()):
            try:
                unique_count = safe_unique_count(non_null_series)
                if unique_count / len(non_null_series) > 0.9:
                    return "Identifier"
            except:
                pass
        
        return "Text"
    
    return "Unknown"

def detect_data_patterns(series: pd.Series) -> List[str]:
    patterns = []
    non_null_series = series.dropna()
    
    if len(non_null_series) == 0:
        return patterns
    
    sample_value = non_null_series.iloc[0]
    if isinstance(sample_value, (dict, list)):
        if isinstance(sample_value, dict):
            patterns.append("JSON/Object structure")
            try:
                all_keys = [set(item.keys()) if isinstance(item, dict) else set() for item in non_null_series]
                if all_keys and len(set(frozenset(keys) for keys in all_keys)) == 1:
                    patterns.append("Consistent object schema")
            except:
                pass
        elif isinstance(sample_value, list):
            patterns.append("Array/List structure")
            try:
                lengths = [len(item) if isinstance(item, list) else 0 for item in non_null_series]
                if len(set(lengths)) == 1:
                    patterns.append(f"Consistent array length ({lengths[0]} items)")
            except:
                pass
        return patterns
    
    if series.dtype == 'object':
        try:
            str_series = non_null_series.astype(str)
            
            lengths = str_series.str.len()
            if lengths.nunique() == 1:
                patterns.append(f"Consistent length ({lengths.iloc[0]} characters)")
            
            if len(str_series) > 0 and str_series.str.startswith(str_series.iloc[0][:3]).sum() / len(str_series) > 0.8:
                patterns.append("Common prefix pattern")
            
            phone_pattern = r'^\+?1?-?\(?\d{3}\)?-?\d{3}-?\d{4}$'
            if str_series.str.match(phone_pattern).sum() / len(str_series) > 0.5:
                patterns.append("Phone number format")
            
            uuid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            if str_series.str.match(uuid_pattern).sum() / len(str_series) > 0.5:
                patterns.append("UUID format detected")
                
        except:
            patterns.append("Complex text data")
    
    if pd.api.types.is_numeric_dtype(series):
        Q1 = non_null_series.quantile(0.25)
        Q3 = non_null_series.quantile(0.75)
        IQR = Q3 - Q1
        outliers = non_null_series[(non_null_series < (Q1 - 1.5 * IQR)) | (non_null_series > (Q3 + 1.5 * IQR))]
        if len(outliers) > 0:
            patterns.append(f"Contains {len(outliers)} potential outliers ({len(outliers)/len(non_null_series)*100:.1f}%)")
        
        if non_null_series.is_monotonic_increasing:
            patterns.append("Monotonically increasing values")
        elif non_null_series.is_monotonic_decreasing:
            patterns.append("Monotonically decreasing values")
        
        if (non_null_series % 1 == 0).all():
            patterns.append("All integer values")
        elif (non_null_series % 0.5 == 0).sum() / len(non_null_series) > 0.8:
            patterns.append("Values clustered at 0.5 intervals")
    
    return patterns

def calculate_statistical_summary(series: pd.Series) -> Optional[StatisticalSummary]:
    if not pd.api.types.is_numeric_dtype(series):
        return None
    
    non_null_series = series.dropna()
    if len(non_null_series) == 0:
        return None
    
    try:
        mean_val = float(non_null_series.mean())
        std_val = float(non_null_series.std())
        min_val = float(non_null_series.min())
        max_val = float(non_null_series.max())
        q25 = float(non_null_series.quantile(0.25))
        q75 = float(non_null_series.quantile(0.75))
        
        summary = StatisticalSummary(
            mean=mean_val,
            median=float(non_null_series.median()),
            std=std_val,
            variance=float(non_null_series.var()),
            min_value=min_val,
            max_value=max_val,
            range_value=max_val - min_val,
            q25=q25,
            q75=q75,
            iqr=q75 - q25,
            mode=float(non_null_series.mode().iloc[0]) if len(non_null_series.mode()) > 0 else None,
            coefficient_of_variation=round((std_val / abs(mean_val)) * 100, 2) if mean_val != 0 else None,
            percentile_5=float(non_null_series.quantile(0.05)),
            percentile_95=float(non_null_series.quantile(0.95))
        )
        
        if SCIPY_AVAILABLE and len(non_null_series) > 2:
            summary.skewness = float(stats.skew(non_null_series))
            if len(non_null_series) > 3:
                summary.kurtosis = float(stats.kurtosis(non_null_series))
        
        return summary
    except Exception as e:
        print(f"Error calculating statistical summary: {e}")
        return None

def generate_column_recommendations(column_analysis: ColumnAnalysis, total_rows: int) -> List[str]:
    recommendations = []
    
    if column_analysis.null_percentage > 50:
        recommendations.append("⚠️ Consider removing this column due to high missing data rate (>50%)")
    elif column_analysis.null_percentage > 20:
        recommendations.append("📊 Implement imputation strategies (mean/median/mode or ML-based)")
    elif column_analysis.null_percentage > 5:
        recommendations.append("📈 Monitor missing values and improve data collection")
    
    if column_analysis.unique_percentage > 95 and total_rows > 100:
        recommendations.append("🔑 High cardinality - verify if this is an identifier column")
    elif column_analysis.unique_percentage < 1 and total_rows > 100:
        recommendations.append("📉 Very low cardinality - evaluate if column adds analytical value")
    
    if column_analysis.type == "Numeric (as Text)":
        recommendations.append("🔧 Convert to numeric type for better analysis and storage efficiency")
    elif column_analysis.type == "Date (as Text)":
        recommendations.append("📅 Parse as datetime for time-series analysis capabilities")
    
    if column_analysis.is_constant:
        recommendations.append("🚫 Constant column - consider removing for ML models")
    
    return recommendations

def analyze_column_comprehensive(series: pd.Series, total_rows: int) -> ColumnAnalysis:
    column_name = series.name
    data_type = detect_column_type(series)
    null_count = int(series.isnull().sum())
    null_percentage = round((null_count / total_rows) * 100, 2)
    unique_count = safe_unique_count(series)
    unique_percentage = round((unique_count / total_rows) * 100, 2)
    
    sample_values = safe_unique_values(series, 8)
    truncated_samples = []
    for val in sample_values:
        if isinstance(val, (dict, list)):
            truncated_samples.append(f"{type(val).__name__} ({len(val)} items)" if hasattr(val, '__len__') else str(type(val).__name__))
        else:
            truncated_samples.append(str(val)[:100])
    sample_values = truncated_samples
    
    statistical_summary = calculate_statistical_summary(series)
    data_patterns = detect_data_patterns(series)
    entropy = calculate_entropy(series.dropna())
    
    is_potential_key = unique_percentage > 95 and null_percentage < 1
    is_constant = unique_count == 1 and null_count == 0
    
    column_analysis = ColumnAnalysis(
        name=column_name,
        type=data_type,
        null_count=null_count,
        null_percentage=null_percentage,
        unique_count=unique_count,
        unique_percentage=unique_percentage,
        sample_values=sample_values,
        statistical_summary=statistical_summary,
        data_patterns=data_patterns,
        entropy=entropy,
        is_potential_key=is_potential_key,
        is_constant=is_constant
    )
    
    recommendations = generate_column_recommendations(column_analysis, total_rows)
    column_analysis.recommendations = recommendations
    
    return column_analysis

# ==================== CORRELATION ANALYSIS ====================

def analyze_correlations(df: pd.DataFrame) -> CorrelationAnalysis:
    """Analyze correlations between numeric columns"""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    
    if len(numeric_cols) < 2:
        return CorrelationAnalysis(
            column_pairs=[],
            high_correlations=["Not enough numeric columns for correlation analysis"],
            multicollinearity_warning=False
        )
    
    try:
        corr_matrix = df[numeric_cols].corr()
        column_pairs = []
        high_correlations = []
        multicollinearity = False
        
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                col1, col2 = numeric_cols[i], numeric_cols[j]
                corr_value = corr_matrix.loc[col1, col2]
                
                if not np.isnan(corr_value):
                    pair_info = {
                        "column1": col1,
                        "column2": col2,
                        "correlation": round(float(corr_value), 4),
                        "strength": "strong" if abs(corr_value) > 0.7 else "moderate" if abs(corr_value) > 0.4 else "weak",
                        "direction": "positive" if corr_value > 0 else "negative"
                    }
                    column_pairs.append(pair_info)
                    
                    if abs(corr_value) > 0.7:
                        high_correlations.append(f"📊 {col1} ↔ {col2}: {corr_value:.3f} (strong {pair_info['direction']})")
                        if abs(corr_value) > 0.9:
                            multicollinearity = True
        
        column_pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        return CorrelationAnalysis(
            column_pairs=column_pairs[:20],
            high_correlations=high_correlations,
            multicollinearity_warning=multicollinearity
        )
    except Exception as e:
        print(f"Error in correlation analysis: {e}")
        return CorrelationAnalysis(
            column_pairs=[],
            high_correlations=[f"Error calculating correlations: {str(e)}"],
            multicollinearity_warning=False
        )

# ==================== DISTRIBUTION ANALYSIS ====================

def analyze_distribution(series: pd.Series) -> DistributionAnalysis:
    """Analyze the distribution of a numeric column"""
    column_name = str(series.name)
    non_null = series.dropna()
    
    if len(non_null) < 3 or not pd.api.types.is_numeric_dtype(series):
        return DistributionAnalysis(
            column_name=column_name,
            distribution_type="insufficient_data",
            is_normally_distributed=False
        )
    
    try:
        skewness = float(stats.skew(non_null)) if SCIPY_AVAILABLE else 0
        
        if abs(skewness) < 0.5:
            dist_type = "approximately_normal"
        elif skewness > 1:
            dist_type = "highly_skewed_right"
        elif skewness > 0.5:
            dist_type = "moderately_skewed_right"
        elif skewness < -1:
            dist_type = "highly_skewed_left"
        else:
            dist_type = "moderately_skewed_left"
        
        normality_pvalue = None
        is_normal = False
        
        if SCIPY_AVAILABLE:
            sample = non_null.sample(min(5000, len(non_null)), random_state=42) if len(non_null) > 5000 else non_null
            try:
                if len(sample) < 50:
                    _, normality_pvalue = stats.shapiro(sample)
                else:
                    _, normality_pvalue = stats.normaltest(sample)
                is_normal = normality_pvalue > 0.05
            except:
                pass
        
        Q1, Q3 = non_null.quantile([0.25, 0.75])
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        outliers = non_null[(non_null < lower_bound) | (non_null > upper_bound)]
        
        return DistributionAnalysis(
            column_name=column_name,
            distribution_type=dist_type,
            normality_test_pvalue=round(float(normality_pvalue), 4) if normality_pvalue else None,
            is_normally_distributed=is_normal,
            outlier_count=len(outliers),
            outlier_percentage=round(len(outliers) / len(non_null) * 100, 2),
            outlier_values=outliers.head(5).tolist() if len(outliers) > 0 else []
        )
    except Exception as e:
        print(f"Error in distribution analysis for {column_name}: {e}")
        return DistributionAnalysis(
            column_name=column_name,
            distribution_type="error",
            is_normally_distributed=False
        )

# ==================== ANOMALY DETECTION ====================

def detect_anomalies(df: pd.DataFrame, column_analyses: List[ColumnAnalysis]) -> AnomalyDetection:
    """Detect anomalies across the dataset"""
    total_anomalies = 0
    anomalous_columns = []
    anomaly_details = []
    
    for col_analysis in column_analyses:
        col_name = col_analysis.name
        
        if any("outliers" in pattern.lower() for pattern in col_analysis.data_patterns):
            for pattern in col_analysis.data_patterns:
                if "outliers" in pattern.lower():
                    try:
                        count = int(pattern.split()[1])
                        total_anomalies += count
                        anomalous_columns.append(col_name)
                        anomaly_details.append({
                            "column": col_name,
                            "type": "statistical_outliers",
                            "description": pattern,
                            "severity": "high" if count > 10 else "medium"
                        })
                    except:
                        pass
        
        if "as Text" in col_analysis.type:
            anomaly_details.append({
                "column": col_name,
                "type": "data_type_mismatch",
                "description": f"Column appears to be {col_analysis.type.split(' (')[0]} stored as text",
                "severity": "medium"
            })
        
        if col_analysis.is_constant:
            anomaly_details.append({
                "column": col_name,
                "type": "constant_value",
                "description": "Column contains only one unique value",
                "severity": "low"
            })
    
    total_cells = len(df) * len(df.columns)
    anomaly_percentage = round((total_anomalies / total_cells) * 100, 4) if total_cells > 0 else 0
    
    return AnomalyDetection(
        total_anomalies=total_anomalies,
        anomaly_percentage=anomaly_percentage,
        anomalous_columns=list(set(anomalous_columns)),
        anomaly_details=anomaly_details
    )

# ==================== DATA QUALITY ASSESSMENT ====================

def assess_data_quality(df: pd.DataFrame, column_analyses: List[ColumnAnalysis]) -> DataQuality:
    total_cells = len(df) * len(df.columns)
    null_cells = df.isnull().sum().sum()
    completeness_score = int(((total_cells - null_cells) / total_cells) * 100) if total_cells > 0 else 100
    
    consistency_issues = 0
    for col_analysis in column_analyses:
        if "Numeric (as Text)" in col_analysis.type or "Date (as Text)" in col_analysis.type:
            consistency_issues += 1
    consistency_score = max(0, 100 - (consistency_issues * 10))
    
    validity_issues = sum(1 for col in column_analyses if col.null_percentage > 50)
    validity_score = max(0, 100 - (validity_issues * 15))
    
    # Handle duplicates check safely for DataFrames with nested objects
    try:
        # First, try to identify columns with unhashable types and exclude them
        hashable_cols = []
        for col in df.columns:
            try:
                # Test if column values are hashable
                sample = df[col].dropna().head(10)
                if len(sample) > 0:
                    # Try to hash the first non-null value
                    first_val = sample.iloc[0]
                    if not isinstance(first_val, (dict, list)):
                        hashable_cols.append(col)
                else:
                    hashable_cols.append(col)  # Empty columns are fine
            except:
                pass
        
        if hashable_cols:
            duplicates = int(df[hashable_cols].duplicated().sum())
        else:
            # If no hashable columns, convert all to strings and check
            duplicates = int(df.astype(str).duplicated().sum())
    except Exception as e:
        # Fallback: convert entire DataFrame to string representation
        try:
            duplicates = int(df.astype(str).duplicated().sum())
        except:
            duplicates = 0  # Unable to determine duplicates
    
    duplicate_percentage = round((duplicates / len(df)) * 100, 2) if len(df) > 0 else 0
    uniqueness_score = max(0, int(100 - duplicate_percentage))
    
    timeliness_score = 85
    datetime_cols = [col for col in column_analyses if 'Date' in col.type]
    if datetime_cols:
        timeliness_score = 90
    
    overall_score = int(
        completeness_score * 0.30 +
        consistency_score * 0.25 +
        validity_score * 0.20 +
        uniqueness_score * 0.15 +
        timeliness_score * 0.10
    )
    
    if overall_score >= 90:
        quality_grade = "A"
    elif overall_score >= 80:
        quality_grade = "B"
    elif overall_score >= 70:
        quality_grade = "C"
    elif overall_score >= 60:
        quality_grade = "D"
    else:
        quality_grade = "F"
    
    issues = []
    recommendations = []
    
    if null_cells > 0:
        null_percentage = (null_cells / total_cells) * 100
        if null_percentage > 20:
            issues.append(f"🔴 Critical: High missing data rate ({null_percentage:.1f}% of all cells)")
            recommendations.append("Implement comprehensive data validation and collection procedures")
        elif null_percentage > 10:
            issues.append(f"🟠 Warning: Moderate missing data rate ({null_percentage:.1f}% of all cells)")
            recommendations.append("Review data collection processes and implement missing data strategies")
        elif null_percentage > 1:
            issues.append(f"🟡 Notice: Some missing data present ({null_percentage:.1f}% of all cells)")
            recommendations.append("Monitor data quality and consider imputation for critical analyses")
    
    if duplicate_percentage > 5:
        issues.append(f"🔴 High duplicate rate: {duplicate_percentage}% of rows are duplicates")
        recommendations.append("Implement data deduplication processes")
    elif duplicates > 0:
        issues.append(f"🟠 Found {duplicates} duplicate rows ({duplicate_percentage}%)")
        recommendations.append("Review and remove duplicate entries")
    
    high_missing_cols = [col.name for col in column_analyses if col.null_percentage > 50]
    if high_missing_cols:
        issues.append(f"🔴 Columns with >50% missing data: {', '.join(high_missing_cols[:3])}")
        recommendations.append("Consider removing or redesigning columns with excessive missing data")
    
    type_issues = [col.name for col in column_analyses if "as Text" in col.type]
    if type_issues:
        issues.append(f"🟠 Data type inconsistencies in columns: {', '.join(type_issues[:3])}")
        recommendations.append("Standardize data types for improved analysis and storage")
    
    constant_cols = [col.name for col in column_analyses if col.is_constant]
    if constant_cols:
        issues.append(f"🟡 Constant columns found: {', '.join(constant_cols[:3])}")
        recommendations.append("Remove constant columns before ML modeling")
    
    return DataQuality(
        completeness_score=completeness_score,
        consistency_score=consistency_score,
        validity_score=validity_score,
        uniqueness_score=uniqueness_score,
        timeliness_score=timeliness_score,
        overall_score=overall_score,
        duplicates=duplicates,
        duplicate_percentage=duplicate_percentage,
        issues=issues,
        recommendations=recommendations,
        quality_grade=quality_grade
    )

# ==================== AI-POWERED INSIGHTS ====================

def generate_ai_insights(
    df: pd.DataFrame, 
    column_analyses: List[ColumnAnalysis], 
    data_quality: DataQuality,
    correlation_analysis: CorrelationAnalysis,
    basic_stats: BasicStats,
    user_id: Optional[str] = None
) -> Optional[AIInsights]:
    
    try:
        actual_model, _ = check_and_get_model(user_id, ANALYTICS_MODEL)
        if actual_model is None:
            actual_model = ANALYTICS_MODEL
        
        column_summary = []
        for col in column_analyses[:15]:
            col_info = f"- {col.name} ({col.type}): {col.unique_count} unique values, {col.null_percentage}% missing"
            if col.statistical_summary:
                col_info += f", mean={col.statistical_summary.mean:.2f}" if col.statistical_summary.mean else ""
            column_summary.append(col_info)
        
        correlation_summary = ""
        if correlation_analysis.high_correlations:
            correlation_summary = "\n".join(correlation_analysis.high_correlations[:5])
        
        system_prompt = """You are an expert data analyst AI assistant. Analyze the provided dataset summary and generate comprehensive, actionable insights. 
Be specific, professional, and focus on practical recommendations.
Use industry-standard data analysis terminology.
Format your response as valid JSON with the following structure:
{
    "executive_summary": "A 2-3 sentence high-level overview",
    "key_findings": ["finding1", "finding2", "finding3"],
    "data_story": "A narrative explaining what this data represents and its potential value",
    "actionable_recommendations": ["rec1", "rec2", "rec3"],
    "potential_use_cases": ["use_case1", "use_case2", "use_case3"],
    "data_quality_narrative": "Assessment of data quality and reliability",
    "advanced_analytics_suggestions": ["suggestion1", "suggestion2", "suggestion3"]
}"""

        user_prompt = f"""Analyze this dataset and provide comprehensive insights:

**Dataset Overview:**
- Total Rows: {basic_stats.total_rows:,}
- Total Columns: {basic_stats.total_columns}
- File Type: {basic_stats.file_type}
- Memory Usage: {basic_stats.memory_usage}

**Data Quality:**
- Overall Score: {data_quality.overall_score}% (Grade: {data_quality.quality_grade})
- Completeness: {data_quality.completeness_score}%
- Consistency: {data_quality.consistency_score}%
- Duplicates: {data_quality.duplicates} ({data_quality.duplicate_percentage}%)

**Column Summary:**
{chr(10).join(column_summary)}

**Key Correlations:**
{correlation_summary if correlation_summary else "No significant correlations found"}

**Issues Detected:**
{chr(10).join(data_quality.issues) if data_quality.issues else "No major issues"}

Please provide strategic insights, focusing on business value and data science opportunities."""

        response = generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=actual_model,
            temperature=0.7,
            max_tokens=2000
        )
        
        record_model_usage(user_id, actual_model)
        
        try:
            clean_response = response.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]
            clean_response = clean_response.strip()
            
            ai_data = json.loads(clean_response)
            
            return AIInsights(
                executive_summary=ai_data.get("executive_summary", "Analysis complete."),
                key_findings=ai_data.get("key_findings", []),
                data_story=ai_data.get("data_story", ""),
                actionable_recommendations=ai_data.get("actionable_recommendations", []),
                potential_use_cases=ai_data.get("potential_use_cases", []),
                data_quality_narrative=ai_data.get("data_quality_narrative", ""),
                advanced_analytics_suggestions=ai_data.get("advanced_analytics_suggestions", [])
            )
        except json.JSONDecodeError:
            return AIInsights(
                executive_summary=response[:500] if response else "AI analysis completed.",
                key_findings=["AI-powered analysis completed successfully"],
                data_story="The dataset has been analyzed for patterns and insights.",
                actionable_recommendations=["Review the detailed column analysis for specific recommendations"],
                potential_use_cases=["Data exploration", "Business intelligence", "Machine learning"],
                data_quality_narrative=f"Data quality grade: {data_quality.quality_grade}",
                advanced_analytics_suggestions=["Consider correlation analysis", "Explore feature engineering"]
            )
            
    except Exception as e:
        print(f"Error generating AI insights: {e}")
        return AIInsights(
            executive_summary="AI analysis encountered an issue. Please review the statistical analysis below.",
            key_findings=["Statistical analysis completed successfully"],
            data_story="Your dataset has been comprehensively analyzed.",
            actionable_recommendations=["Review column-level recommendations", "Address data quality issues"],
            potential_use_cases=["Data analysis", "Reporting", "ML preparation"],
            data_quality_narrative=f"Overall quality score: {data_quality.overall_score}%",
            advanced_analytics_suggestions=["Manual review recommended"]
        )

# ==================== COMPREHENSIVE INSIGHTS ====================

def generate_comprehensive_insights(
    df: pd.DataFrame, 
    column_analyses: List[ColumnAnalysis], 
    data_quality: DataQuality,
    correlation_analysis: CorrelationAnalysis,
    basic_stats: BasicStats,
    user_id: Optional[str] = None
) -> DatasetInsights:
    
    general_insights = []
    statistical_insights = []
    business_insights = []
    data_science_insights = []
    
    if len(df) < 100:
        general_insights.append("📊 Small dataset - consider collecting more data for robust analysis")
    elif len(df) < 1000:
        general_insights.append("📊 Medium-sized dataset - suitable for initial analysis and prototyping")
    elif len(df) < 100000:
        general_insights.append("📊 Large dataset - excellent for comprehensive analysis and modeling")
    else:
        general_insights.append("📊 Very large dataset - ideal for advanced analytics and deep learning")
    
    type_counts = {}
    for col in column_analyses:
        base_type = col.type.split('(')[0].strip()
        type_counts[base_type] = type_counts.get(base_type, 0) + 1
    
    numeric_cols = sum(1 for col in column_analyses if 'Numeric' in col.type or col.type in ['Integer', 'Float'])
    text_cols = sum(1 for col in column_analyses if col.type in ['Text', 'Categorical'])
    datetime_cols = sum(1 for col in column_analyses if 'Date' in col.type)
    
    if numeric_cols > 0:
        general_insights.append(f"🔢 Contains {numeric_cols} numeric columns suitable for statistical analysis")
    if text_cols > 0:
        general_insights.append(f"📝 Contains {text_cols} text columns for categorical and NLP analysis")
    if datetime_cols > 0:
        general_insights.append(f"📅 Contains {datetime_cols} date/time columns for temporal analysis")
    
    numeric_columns = [col for col in column_analyses if col.statistical_summary is not None]
    if numeric_columns:
        high_variance_cols = [col for col in numeric_columns 
                            if col.statistical_summary.coefficient_of_variation 
                            and col.statistical_summary.coefficient_of_variation > 100]
        if high_variance_cols:
            statistical_insights.append(f"📈 High variability detected in {len(high_variance_cols)} columns (CV > 100%)")
        
        if SCIPY_AVAILABLE:
            skewed_cols = [col for col in numeric_columns 
                          if col.statistical_summary.skewness and abs(col.statistical_summary.skewness) > 1]
            if skewed_cols:
                statistical_insights.append(f"📊 Skewed distributions in {len(skewed_cols)} columns - consider log transformation")
        
        outlier_cols = [col for col in column_analyses if any("outliers" in p.lower() for p in col.data_patterns)]
        if outlier_cols:
            statistical_insights.append(f"⚠️ Potential outliers detected in {len(outlier_cols)} columns")
    
    if correlation_analysis.multicollinearity_warning:
        statistical_insights.append("⚠️ Multicollinearity detected - consider feature selection or PCA")
    if correlation_analysis.high_correlations:
        statistical_insights.append(f"🔗 Found {len(correlation_analysis.high_correlations)} strong correlations")
    
    identifier_cols = [col for col in column_analyses if col.type == "Identifier" or col.is_potential_key]
    if identifier_cols:
        business_insights.append(f"🔑 Found {len(identifier_cols)} potential identifier columns for data linking")
    
    categorical_cols = [col for col in column_analyses if col.type == "Categorical"]
    if categorical_cols:
        business_insights.append(f"📋 Found {len(categorical_cols)} categorical columns for segmentation analysis")
    
    email_cols = [col for col in column_analyses if col.type == "Email"]
    phone_cols = [col for col in column_analyses if col.type == "Phone"]
    if email_cols or phone_cols:
        business_insights.append("👥 Contact information present - suitable for customer analytics")
    
    if data_quality.overall_score >= 90:
        business_insights.append("✅ Excellent data quality - highly reliable for business decisions")
    elif data_quality.overall_score >= 75:
        business_insights.append("👍 Good data quality - suitable for most business analyses")
    else:
        business_insights.append("⚠️ Data quality concerns - recommend cleaning before critical decisions")
    
    if numeric_cols >= 3:
        data_science_insights.append("🧠 Sufficient numeric features for correlation analysis and predictive modeling")
    
    if len(df) > 1000 and numeric_cols > 0:
        data_science_insights.append("🤖 Dataset size and structure suitable for machine learning")
    
    if datetime_cols > 0:
        data_science_insights.append("⏰ Time-series analysis and forecasting opportunities available")
    
    missing_data_cols = [col for col in column_analyses if col.null_percentage > 10]
    if missing_data_cols:
        data_science_insights.append(f"🔧 Consider imputation strategies for {len(missing_data_cols)} columns with >10% missing data")
    
    high_cardinality_cols = [col for col in column_analyses if col.unique_percentage > 90 and col.type == "Text"]
    if high_cardinality_cols:
        data_science_insights.append("📊 High cardinality text columns - consider embedding or hashing techniques")
    
    ai_insights = generate_ai_insights(df, column_analyses, data_quality, correlation_analysis, basic_stats, user_id)
    
    return DatasetInsights(
        general_insights=general_insights,
        statistical_insights=statistical_insights,
        business_insights=business_insights,
        data_science_insights=data_science_insights,
        ai_insights=ai_insights
    )

# ==================== MAIN ANALYSIS FUNCTION ====================

async def analyze_dataset_file(file: UploadFile, user_id: Optional[str] = None) -> DatasetAnalysisResponse:
    start_time = datetime.now()
    
    try:
        content = await file.read()
        file_size = len(content)
        
        if file.filename.endswith('.csv'):
            try:
                try:
                    df = pd.read_csv(pd.io.common.BytesIO(content), encoding='utf-8')
                    encoding = 'utf-8'
                except UnicodeDecodeError:
                    try:
                        df = pd.read_csv(pd.io.common.BytesIO(content), encoding='latin-1')
                        encoding = 'latin-1'
                    except:
                        df = pd.read_csv(pd.io.common.BytesIO(content), encoding='cp1252')
                        encoding = 'cp1252'
                        
                file_type = "CSV"
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading CSV file: {str(e)}")
                
        elif file.filename.endswith('.json'):
            try:
                json_data = json.loads(content.decode('utf-8'))
                if isinstance(json_data, list):
                    # Try to normalize nested JSON structure
                    try:
                        df = pd.json_normalize(json_data, max_level=2)
                    except:
                        df = pd.DataFrame(json_data)
                elif isinstance(json_data, dict):
                    # Try to normalize nested JSON structure
                    try:
                        df = pd.json_normalize([json_data], max_level=2)
                    except:
                        df = pd.DataFrame([json_data])
                else:
                    raise ValueError("JSON must be an object or array of objects")
                file_type = "JSON"
                encoding = 'utf-8'
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading JSON file: {str(e)}")
                
        elif file.filename.endswith(('.xlsx', '.xls')):
            try:
                df = pd.read_excel(pd.io.common.BytesIO(content))
                file_type = "Excel"
                encoding = None
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading Excel file: {str(e)}")
                
        elif file.filename.endswith('.sql'):
            try:
                # Parse SQL file to extract INSERT statements and create DataFrame
                sql_content = content.decode('utf-8')
                df, file_type = parse_sql_to_dataframe(sql_content)
                encoding = 'utf-8'
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading SQL file: {str(e)}")
                
        elif file.filename.endswith('.parquet'):
            try:
                import pyarrow.parquet as pq
                import pyarrow as pa
                table = pq.read_table(pd.io.common.BytesIO(content))
                df = table.to_pandas()
                file_type = "Parquet"
                encoding = None
            except ImportError:
                raise HTTPException(status_code=400, detail="Parquet support requires pyarrow. Please install it.")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading Parquet file: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV, JSON, SQL, Parquet, or Excel files.")
        
        if df.empty:
            raise HTTPException(status_code=400, detail="The uploaded file is empty or contains no data")
        
        if len(df.columns) == 0:
            raise HTTPException(status_code=400, detail="The uploaded file contains no columns")
        
        original_rows = len(df)
        if len(df) > 100000:
            df = df.sample(n=50000, random_state=42)
        
        total_rows = len(df)
        total_columns = len(df.columns)
        memory_usage = df.memory_usage(deep=True).sum()
        
        total_cells = total_rows * total_columns
        null_cells = df.isnull().sum().sum()
        data_density = round(((total_cells - null_cells) / total_cells) * 100, 2) if total_cells > 0 else 0
        
        if file_type == "CSV":
            estimated_efficiency = "Moderate - Consider Parquet for better compression"
        elif file_type == "JSON":
            estimated_efficiency = "Low - Consider CSV or Parquet for tabular data"
        elif file_type == "SQL":
            estimated_efficiency = "Moderate - SQL provides schema definition, consider Parquet for storage"
        elif file_type == "Parquet":
            estimated_efficiency = "Excellent - Columnar format with efficient compression"
        else:
            estimated_efficiency = "Good - Binary format with compression"
        
        basic_stats = BasicStats(
            total_rows=original_rows,
            total_columns=total_columns,
            file_size=format_file_size(file_size),
            file_type=file_type,
            memory_usage=format_file_size(memory_usage),
            encoding=encoding,
            data_density=data_density,
            estimated_storage_efficiency=estimated_efficiency
        )
        
        column_analyses = []
        for col in df.columns:
            try:
                analysis = analyze_column_comprehensive(df[col], total_rows)
                column_analyses.append(analysis)
            except Exception as e:
                print(f"Error analyzing column {col}: {e}")
                column_analyses.append(ColumnAnalysis(
                    name=col,
                    type="Unknown",
                    null_count=int(df[col].isnull().sum()),
                    null_percentage=round((df[col].isnull().sum() / total_rows) * 100, 2),
                    unique_count=safe_unique_count(df[col]),
                    unique_percentage=round((safe_unique_count(df[col]) / total_rows) * 100, 2),
                    sample_values=safe_unique_values(df[col], 5),
                    data_patterns=["Analysis failed"],
                    recommendations=["Manual review recommended"]
                ))
        
        data_quality = assess_data_quality(df, column_analyses)
        correlation_analysis = analyze_correlations(df)
        
        distribution_analyses = []
        numeric_cols = df.select_dtypes(include=[np.number]).columns[:10]
        for col in numeric_cols:
            dist_analysis = analyze_distribution(df[col])
            distribution_analyses.append(dist_analysis)
        
        anomaly_detection = detect_anomalies(df, column_analyses)
        insights = generate_comprehensive_insights(df, column_analyses, data_quality, correlation_analysis, basic_stats, user_id)
        
        end_time = datetime.now()
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        return DatasetAnalysisResponse(
            basic_stats=basic_stats,
            column_analysis=column_analyses,
            data_quality=data_quality,
            insights=insights,
            correlation_analysis=correlation_analysis,
            distribution_analysis=distribution_analyses,
            anomaly_detection=anomaly_detection,
            analysis_timestamp=end_time.isoformat(),
            processing_time_ms=processing_time_ms
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in dataset analysis: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred during analysis: {str(e)}"
        )
