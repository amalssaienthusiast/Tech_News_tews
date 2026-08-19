"""
Custom Source Loader Module.
Manages permanent storage of custom URLs.
"""

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

CUSTOM_SOURCES_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "custom_sources.json"

class CustomSourceManager:
    """Manages reading and writing custom URLs to persistent storage."""
    
    @classmethod
    def load_sources(cls) -> List[str]:
        """Load list of custom sources from config file."""
        if not CUSTOM_SOURCES_FILE.exists():
            return []
        
        try:
            with open(CUSTOM_SOURCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            sources: List[str] = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.strip():
                        sources.append(item.strip())
                    elif isinstance(item, dict) and "url" in item:
                        url = str(item["url"]).strip()
                        if url:
                            sources.append(url)
                return sources
            elif isinstance(data, dict):
                raw_sources = data.get("sources", [])
                if isinstance(raw_sources, list):
                    for item in raw_sources:
                        if isinstance(item, str) and item.strip():
                            sources.append(item.strip())
                        elif isinstance(item, dict) and "url" in item:
                            url = str(item["url"]).strip()
                            if url:
                                sources.append(url)
                    return sources
                logger.error(f"Invalid custom_sources.json dict schema: 'sources' key must be a list, got {type(raw_sources).__name__}")
                return []
            else:
                logger.error(f"Invalid custom_sources.json format: expected list or dict, got {type(data).__name__}")
                return []
        except Exception as e:
            logger.error(f"Failed to load custom sources from {CUSTOM_SOURCES_FILE}: {e}")
            return []

    @classmethod
    def save_sources(cls, sources: List[str]) -> bool:
        """Save list of custom sources to config file."""
        try:
            CUSTOM_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CUSTOM_SOURCES_FILE, "w", encoding="utf-8") as f:
                json.dump({"sources": sources}, f, indent=4)
            logger.info(f"Saved {len(sources)} custom sources.")
            return True
        except Exception as e:
            logger.error(f"Failed to save custom sources: {e}")
            return False

    @classmethod
    def add_source(cls, url: str) -> bool:
        """Add a single source if not exists."""
        url = url.strip()
        if not url: return False
        
        sources = cls.load_sources()
        if url not in sources:
            sources.append(url)
            return cls.save_sources(sources)
        return False

    @classmethod
    def remove_source(cls, url: str) -> bool:
        """Remove a single source if exists."""
        sources = cls.load_sources()
        if url in sources:
            sources.remove(url)
            return cls.save_sources(sources)
        return False
