import requests
import os
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID") 

class InternetSearchRequest(BaseModel):
    query: str

class Dataset(BaseModel):
    name: str
    description: str
    type: str
    site: str
    link: str

class InternetSearchResponse(BaseModel):
    datasets: List[Dataset]

def google_search(query: str, num_results: int = 10) -> List[dict]:
    if not SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        return []
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "key": SEARCH_API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "num": num_results
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 403:
            return []
        elif response.status_code == 400:
            return []
        
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            return []
            
        items = data.get("items", [])
        return items
        
    except requests.RequestException as e:
        return []
    except Exception as e:
        return []

def extract_file_type_from_link(link: str) -> str:
    common_extensions = ['.csv', '.json', '.xlsx', '.parquet', '.zip', '.sql', '.txt']
    link_lower = link.lower()
    
    for ext in common_extensions:
        if link_lower.endswith(ext):
            return ext[1:].upper() 
    
    return "Unknown"

def search_datasets(query: str) -> List[Dataset]:
    if not SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        return [
            Dataset(
                name="API Configuration Error",
                description="Google Custom Search API credentials are not properly configured. Please check your SEARCH_API_KEY and SEARCH_ENGINE_ID in the environment variables.",
                type="Error",
                site="System",
                link="#"
            )
        ]
    
    all_datasets = []
    
    search_query = f"{query} dataset"
    results = google_search(search_query, num_results=10)
    
    for item in results:
        link = item.get("link")
        title = item.get("title", "Untitled Dataset")
        snippet = item.get("snippet", "No description available")
        site = item.get("displayLink", "Unknown site")
        
        if link and ("dataset" in title.lower() or "data" in title.lower() or 
                    any(ext in link.lower() for ext in ['.csv', '.json', '.xlsx', '.parquet', '.zip', '.sql'])):
            
            clean_title = title.replace(" - ", " ").replace("|", " ").strip()
            if len(clean_title) > 100:
                clean_title = clean_title[:100] + "..."
            
            clean_description = snippet.replace('\n', ' ').strip()
            if len(clean_description) > 200:
                clean_description = clean_description[:200] + "..."
            
            dataset = Dataset(
                name=clean_title,
                description=clean_description,
                type=extract_file_type_from_link(link),
                site=site,
                link=link
            )
            all_datasets.append(dataset)
    
    seen_links = set()
    unique_datasets = []
    for dataset in all_datasets:
        if dataset.link not in seen_links:
            seen_links.add(dataset.link)
            unique_datasets.append(dataset)
    
    return unique_datasets[:10] if unique_datasets else [
        Dataset(
            name="No Datasets Found",
            description=f"No datasets were found for the search term '{query}'. This could be due to: 1) No relevant datasets available online, 2) API quota limits, or 3) Network connectivity issues. Try using different keywords or search terms.",
            type="N/A",
            site="System",
            link="#"
        )
    ]