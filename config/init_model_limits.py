import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")

def initialize_model_limits():
    client = MongoClient(MONGODB_URL)
    db = client[MONGODB_DATABASE]
    collection = db["model_limits"]
    
    model_limits_config = [
        {
            "_id": "gpt-4.1",
            "daily_limit": 8,
            "enabled": True,
            "fallback_models": ["gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"],
            "display_name": "GPT-4.1",
            "category": "selectable",
            "description": "Strongest Reasoning"
        },
        {
            "_id": "gpt-4o",
            "daily_limit": 8,
            "enabled": True,
            "fallback_models": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
            "display_name": "GPT-4o",
            "category": "selectable",
            "description": "Most Creative"
        },
        {
            "_id": "gpt-4.1-mini",
            "daily_limit": 16,
            "enabled": True,
            "fallback_models": ["gpt-4o-mini"],
            "display_name": "GPT-4.1 Mini",
            "category": "selectable",
            "description": "Balanced Performance"
        },
        {
            "_id": "gpt-4o-mini",
            "daily_limit": 16,
            "enabled": True,
            "fallback_models": ["gpt-4.1-mini"],
            "display_name": "GPT-4o Mini",
            "category": "selectable",
            "description": "Fast & Creative"
        },
        {
            "_id": "gpt-4.1-nano",
            "daily_limit": 16,
            "enabled": True,
            "fallback_models": [],
            "display_name": "GPT-4.1 Nano",
            "category": "internal",
            "description": "Internal - Keyword suggestion, enhance prompt, column auto fill, custom generator preview"
        },
        {
            "_id": "meta/Meta-Llama-3.1-8B-Instruct",
            "daily_limit": 16,
            "enabled": True,
            "fallback_models": [],
            "display_name": "Llama 3.1 8B",
            "category": "analytics",
            "description": "Dataset Analytics Only"
        }
    ]
    
    for config in model_limits_config:
        try:
            collection.update_one(
                {"_id": config["_id"]},
                {"$set": config},
                upsert=True
            )
            print(f"✓ Configured {config['_id']}")
        except Exception as e:
            print(f"✗ Error configuring {config['_id']}: {e}")
    
    client.close()
    print("\n✓ Model limits initialized successfully")

if __name__ == "__main__":
    initialize_model_limits()

