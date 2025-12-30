import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, Query
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel

SAMPLE_DATASETS_DIR = Path(__file__).parent.parent / 'sample_datasets'

class DatasetInfo(BaseModel):
    id: str
    name: str
    description: str
    format: str
    size: str
    rows: int
    category: str
    filename: str
    lastUpdated: str

class SampleDatasetsResponse(BaseModel):
    datasets: List[DatasetInfo]
    total_count: int
    filter_options: Dict[str, List[str]]

DATASET_CATALOG = [
    {
        "id": "employee_records",
        "name": "Employee Records",
        "description": "Complete employee database with personal information, salaries, departments, and performance metrics",
        "format": "JSON",
        "size": "2.3 MB",
        "rows": 1000,
        "category": "HR",
        "filename": "employee_records.json",
        "lastUpdated": "2024-01-15"
    },
    {
        "id": "sales_transactions",
        "name": "Sales Transactions",
        "description": "E-commerce sales data including customer details, products, orders, and revenue analytics",
        "format": "MySQL",
        "size": "5.1 MB",
        "rows": 2500,
        "category": "Sales",
        "filename": "sales_transactions.sql",
        "lastUpdated": "2024-01-20"
    },
    {
        "id": "customer_analytics",
        "name": "Customer Analytics",
        "description": "Customer behavior data with demographics, purchase history, and engagement metrics",
        "format": "CSV",
        "size": "3.7 MB",
        "rows": 1500,
        "category": "Analytics",
        "filename": "customer_analytics.csv",
        "lastUpdated": "2024-01-18"
    },
    {
        "id": "product_inventory",
        "name": "Product Inventory",
        "description": "Comprehensive product catalog with inventory levels, pricing, and supplier information",
        "format": "JSON",
        "size": "1.8 MB",
        "rows": 800,
        "category": "Inventory",
        "filename": "product_inventory.json",
        "lastUpdated": "2024-01-22"
    },
    {
        "id": "financial_records",
        "name": "Financial Records",
        "description": "Financial transaction data with accounts, budgets, expenses, and revenue tracking",
        "format": "MySQL",
        "size": "4.2 MB",
        "rows": 3000,
        "category": "Finance",
        "filename": "financial_records.sql",
        "lastUpdated": "2024-01-25"
    },
    {
        "id": "medical_patient_data",
        "name": "Medical Patient Data",
        "description": "Anonymized patient records with medical history, treatments, and diagnostic information",
        "format": "JSON",
        "size": "6.5 MB",
        "rows": 2000,
        "category": "Healthcare",
        "filename": "medical_patient_data.json",
        "lastUpdated": "2024-01-12"
    },
    {
        "id": "student_management",
        "name": "Student Management",
        "description": "Educational data including student profiles, grades, courses, and academic performance",
        "format": "Parquet",
        "size": "2.9 MB",
        "rows": 1200,
        "category": "Education",
        "filename": "student_management.parquet",
        "lastUpdated": "2024-01-28"
    },
    {
        "id": "iot_sensor_data",
        "name": "IoT Sensor Data",
        "description": "Time-series data from IoT devices including temperature, humidity, and environmental sensors",
        "format": "JSON",
        "size": "8.1 MB",
        "rows": 5000,
        "category": "IoT",
        "filename": "iot_sensor_data.json",
        "lastUpdated": "2024-01-30"
    },
    {
        "id": "retail_transactions",
        "name": "Retail Transactions",
        "description": "Point-of-sale data with customer purchases, product details, and store analytics",
        "format": "CSV",
        "size": "7.2 MB",
        "rows": 4500,
        "category": "Retail",
        "filename": "retail_transactions.csv",
        "lastUpdated": "2024-02-01"
    },
    {
        "id": "social_media_analytics",
        "name": "Social Media Analytics",
        "description": "Social media engagement data with posts, likes, shares, and user interactions",
        "format": "JSON",
        "size": "5.8 MB",
        "rows": 3200,
        "category": "Marketing",
        "filename": "social_media_analytics.json",
        "lastUpdated": "2024-02-02"
    },
    {
        "id": "supply_chain_logistics",
        "name": "Supply Chain Logistics",
        "description": "Logistics data including shipments, warehouses, suppliers, and delivery tracking",
        "format": "Parquet",
        "size": "4.1 MB",
        "rows": 2800,
        "category": "Logistics",
        "filename": "supply_chain_logistics.parquet",
        "lastUpdated": "2024-02-03"
    },
    {
        "id": "real_estate_listings",
        "name": "Real Estate Listings",
        "description": "Property listings with prices, locations, features, and market analytics",
        "format": "JSON",
        "size": "3.4 MB",
        "rows": 1800,
        "category": "Real Estate",
        "filename": "real_estate_listings.json",
        "lastUpdated": "2024-02-04"
    },
    {
        "id": "telecommunications_usage",
        "name": "Telecommunications Usage",
        "description": "Telecom usage data with call records, data usage, and customer billing information",
        "format": "MySQL",
        "size": "9.1 MB",
        "rows": 6500,
        "category": "Telecommunications",
        "filename": "telecommunications_usage.sql",
        "lastUpdated": "2024-02-05"
    },
    {
        "id": "weather_stations",
        "name": "Weather Stations",
        "description": "Meteorological data from weather stations with temperature, precipitation, and climate patterns",
        "format": "JSON",
        "size": "12.3 MB",
        "rows": 8000,
        "category": "Weather",
        "filename": "weather_stations.json",
        "lastUpdated": "2024-02-06"
    },
    {
        "id": "gaming_analytics",
        "name": "Gaming Analytics",
        "description": "Game player data with sessions, achievements, in-game purchases, and user behavior",
        "format": "CSV",
        "size": "6.7 MB",
        "rows": 4200,
        "category": "Gaming",
        "filename": "gaming_analytics.csv",
        "lastUpdated": "2024-02-07"
    }
]

def get_sample_datasets(category: Optional[str] = None, format_filter: Optional[str] = None) -> SampleDatasetsResponse:
    try:
        filtered_datasets = DATASET_CATALOG.copy()
        
        if category and category.lower() != 'all':
            filtered_datasets = [
                dataset for dataset in filtered_datasets 
                if dataset['category'].lower() == category.lower()
            ]
        
        if format_filter and format_filter.lower() != 'all':
            filtered_datasets = [
                dataset for dataset in filtered_datasets 
                if dataset['format'].lower() == format_filter.lower()
            ]
        
        all_categories = sorted(list(set(dataset['category'] for dataset in DATASET_CATALOG)))
        all_formats = sorted(list(set(dataset['format'] for dataset in DATASET_CATALOG)))
        
        return SampleDatasetsResponse(
            datasets=[DatasetInfo(**dataset) for dataset in filtered_datasets],
            total_count=len(filtered_datasets),
            filter_options={
                'categories': ['All'] + all_categories,
                'formats': ['All'] + all_formats
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to retrieve sample datasets: {str(e)}')

def download_sample_dataset(dataset_id: str):
    try:
        dataset = None
        for ds in DATASET_CATALOG:
            if ds['id'] == dataset_id:
                dataset = ds
                break
        
        if not dataset:
            raise HTTPException(status_code=404, detail='Dataset not found')
        
        file_path = SAMPLE_DATASETS_DIR / dataset['filename']
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail='Dataset file not found')
        
        media_type = 'application/octet-stream'
        if dataset['format'].lower() == 'json':
            media_type = 'application/json'
        elif dataset['format'].lower() == 'mysql':
            media_type = 'text/plain'
        elif dataset['format'].lower() == 'csv':
            media_type = 'text/csv'
        elif dataset['format'].lower() == 'parquet':
            media_type = 'application/octet-stream'

        # Handle Parquet files differently (binary files)
        if dataset['format'].lower() == 'parquet':
            with open(file_path, 'rb') as f:
                content = f.read()
        else:
            # Text-based files
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

        return Response(
            content=content,
            media_type=media_type,
            headers={
                'Content-Disposition': f'attachment; filename="{dataset["filename"]}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to download dataset: {str(e)}')

def get_dataset_categories() -> Dict[str, List[str]]:
    try:
        categories = sorted(list(set(dataset['category'] for dataset in DATASET_CATALOG)))
        return {'categories': ['All'] + categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get categories: {str(e)}')

def get_dataset_formats() -> Dict[str, List[str]]:
    try:
        formats = sorted(list(set(dataset['format'] for dataset in DATASET_CATALOG)))
        return {'formats': ['All'] + formats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get formats: {str(e)}')
