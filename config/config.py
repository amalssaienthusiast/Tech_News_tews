
import json
import os
from pathlib import Path
from typing import Dict, Any

def load_config() -> Dict[str, Any]:
    """Load configuration from JSON file"""
    config_path = Path(__file__).parent / 'news_sources.json'
    
    if not config_path.exists():
        # Fallback default or error
        return {
            "sources": [],
            "general": {
                "max_concurrent_scrapers": 5,
                "request_timeout": 30
            }
        }
        
    with open(config_path, 'r') as f:
        return json.load(f)
