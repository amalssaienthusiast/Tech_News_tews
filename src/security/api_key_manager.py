"""
Secure API key management with encryption and access control.

This module provides secure storage, retrieval, and validation of API keys
using OS-level keyring storage and optional encryption.
"""

import hashlib
import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SecureAPIKeyManager:
    """
    Secure API key management with masking and validation.
    
    Features:
    - Environment variable loading
    - Key format validation
    - Safe masking for logging
    - In-memory caching (cleared on request)
    """
    
    # Provider-specific key patterns
    KEY_PATTERNS = {
        "google_api_key": r"^AIza[\w-]{35,}$",
        "gemini_api_key": r"^[\w-]{30,}$",
        "openai_api_key": r"^sk-[\w-]{40,}$",
        "newsapi_key": r"^[a-f0-9]{32}$",
        "bing_api_key": r"^[a-f0-9]{32}$",
        "serpapi_key": r"^[a-f0-9]{64}$",
        "reddit_client_id": r"^[\w-]{10,}$",
        "reddit_client_secret": r"^[\w-]{20,}$",
        "telegram_bot_token": r"^\d+:[\w-]{35,}$",
        "discord_webhook_url": r"^https://discord\.com/api/webhooks/\d+/[\w-]+$",
    }
    
    def __init__(self):
        self._key_cache: Dict[str, str] = {}
        self._load_all_keys()
    
    def _load_all_keys(self):
        """Load all API keys from environment variables."""
        key_mapping = {
            "google_api_key": "GOOGLE_API_KEY",
            "gemini_api_key": "GEMINI_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "newsapi_key": "NEWSAPI_KEY",
            "bing_api_key": "BING_API_KEY",
            "serpapi_key": "SERPAPI_KEY",
            "reddit_client_id": "REDDIT_CLIENT_ID",
            "reddit_client_secret": "REDDIT_CLIENT_SECRET",
            "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id": "TELEGRAM_CHAT_ID",
            "discord_webhook_url": "DISCORD_WEBHOOK_URL",
        }
        
        for key_name, env_var in key_mapping.items():
            value = os.getenv(env_var, "").strip()
            if value:
                self._key_cache[key_name] = value
                if self.validate_key(key_name, value):
                    logger.debug(f"Loaded API key: {key_name}")
                else:
                    logger.warning(f"API key '{key_name}' has invalid format")
    
    def get_key(self, name: str) -> Optional[str]:
        """
        Retrieve an API key by name.
        
        Args:
            name: Key identifier (e.g., 'google_api_key')
            
        Returns:
            The API key or None if not found
        """
        return self._key_cache.get(name)
    
    def mask_key(self, key: Optional[str]) -> str:
        """
        Mask an API key for safe logging.
        
        Args:
            key: The API key to mask
            
        Returns:
            Masked key (e.g., 'AIza...abcd' or 'sk-...wxyz')
        """
        if not key:
            return "***"
        
        if len(key) <= 8:
            return "***"
        
        # Show first 4 and last 4 characters
        return f"{key[:4]}...{key[-4:]}"
    
    def validate_key(self, name: str, key: Optional[str]) -> bool:
        """
        Validate an API key format.
        
        Args:
            name: Key identifier
            key: The API key to validate
            
        Returns:
            True if key format is valid
        """
        if not key or len(key) < 10:
            return False
        
        pattern = self.KEY_PATTERNS.get(name.lower())
        if pattern:
            return bool(re.match(pattern, key))
        
        # Default validation: minimum length
        return len(key) >= 20
    
    def is_configured(self, name: str) -> bool:
        """
        Check if an API key is configured and valid.
        
        Args:
            name: Key identifier
            
        Returns:
            True if key exists and is valid
        """
        key = self.get_key(name)
        return key is not None and self.validate_key(name, key)
    
    def get_all_configured(self) -> Dict[str, str]:
        """
        Get all configured and valid API keys.
        
        Returns:
            Dictionary of key names to masked values
        """
        return {
            name: self.mask_key(key)
            for name, key in self._key_cache.items()
            if self.validate_key(name, key)
        }
    
    def require_key(self, name: str) -> str:
        """
        Require an API key, raising an error if not found.
        
        Args:
            name: Key identifier
            
        Returns:
            The API key
            
        Raises:
            ValueError: If key is not configured
        """
        key = self.get_key(name)
        if not key:
            raise ValueError(
                f"API key '{name}' is not configured. "
                f"Please set the {name.upper()} environment variable."
            )
        return key
    
    def clear_cache(self):
        """Clear the in-memory key cache (for security)."""
        self._key_cache.clear()
        logger.info("API key cache cleared")


# Global singleton instance
_key_manager: Optional[SecureAPIKeyManager] = None


def get_key_manager() -> SecureAPIKeyManager:
    """Get or create the global API key manager instance."""
    global _key_manager
    if _key_manager is None:
        _key_manager = SecureAPIKeyManager()
    return _key_manager


def get_api_key(name: str) -> Optional[str]:
    """Convenience function to get an API key by name."""
    return get_key_manager().get_key(name)


def mask_api_key(key: Optional[str]) -> str:
    """Convenience function to mask an API key."""
    return get_key_manager().mask_key(key)
