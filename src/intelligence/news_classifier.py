"""
News Classifier for Tech News Scraper v3.0

Multi-category news classification with:
- 25 predefined tech categories
- Extensible category management (add new, skip existing)
- YAML-based configuration
- Fast local classification with LLM fallback
"""

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from pydantic import BaseModel, Field

from .llm_provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


class NewsCategory(str, Enum):
    """Predefined news categories (25 total)."""
    
    # Core Technology
    TECHNOLOGY_INNOVATION = "Technology & Innovation"
    ARTIFICIAL_INTELLIGENCE = "Artificial Intelligence"
    MACHINE_LEARNING = "Machine Learning"
    CYBERSECURITY = "Cybersecurity"
    CLOUD_COMPUTING = "Cloud Computing"
    
    # Software & Platforms
    ENTERPRISE_SOFTWARE = "Enterprise Software"
    DEVELOPER_TOOLS = "Developer Tools"
    OPEN_SOURCE = "Open Source"
    
    # Hardware & Infrastructure
    SEMICONDUCTORS = "Semiconductors"
    CONSUMER_ELECTRONICS = "Consumer Electronics"
    TELECOMMUNICATIONS = "Telecommunications"
    
    # Emerging Tech
    ROBOTICS_AUTOMATION = "Robotics & Automation"
    AR_VR_METAVERSE = "AR/VR (Metaverse)"
    AUTONOMOUS_VEHICLES = "Autonomous Vehicles"
    SPACE_TECH = "Space Tech"
    
    # Finance & Business
    FINTECH_PAYMENTS = "Fintech & Payments"
    BLOCKCHAIN_CRYPTO = "Blockchain/Crypto"
    STARTUPS_FUNDING = "Startups & Funding"
    BIG_TECH = "Big Tech (FAANG+)"
    
    # Vertical Markets
    HEALTHCARE_TECH = "Healthcare Tech"
    CLIMATE_ENERGY_TECH = "Climate/Energy Tech"
    ECOMMERCE = "E-commerce"
    GAMING_ENTERTAINMENT = "Gaming & Entertainment"
    
    # Regulatory
    REGTECH_COMPLIANCE = "RegTech & Compliance"


@dataclass
class CategoryConfig:
    """Configuration for a custom category."""
    name: str
    keywords: List[str] = field(default_factory=list)
    description: str = ""
    parent_category: Optional[str] = None
    enabled: bool = True


class ClassificationResult(BaseModel):
    """Result of news classification."""
    primary_category: str = Field(description="Most relevant category")
    secondary_categories: List[str] = Field(
        default_factory=list,
        description="Additional relevant categories (max 2)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score for primary category"
    )
    keywords_matched: List[str] = Field(
        default_factory=list,
        description="Keywords that influenced classification"
    )


class CategoryManager:
    """
    Manages news categories with extensibility support.
    
    Categories are loaded from:
    1. Built-in NewsCategory enum (25 categories)
    2. config/categories.yaml (user-defined, optional)
    
    Supports:
    - Adding new categories (skips if already exists)
    - Enabling/disabling categories
    - Keyword-based hints for classification
    """
    
    DEFAULT_CATEGORIES_PATH = Path(__file__).parent.parent.parent / "config" / "categories.yaml"
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self.DEFAULT_CATEGORIES_PATH
        self._categories: Dict[str, CategoryConfig] = {}
        self._load_builtin_categories()
        self._load_custom_categories()
    
    def _load_builtin_categories(self):
        """Load built-in categories from enum."""
        # Keyword hints for each category
        category_keywords = {
            NewsCategory.ARTIFICIAL_INTELLIGENCE: [
                "ai", "artificial intelligence", "gpt", "llm", "openai", 
                "anthropic", "gemini", "neural network", "deep learning"
            ],
            NewsCategory.MACHINE_LEARNING: [
                "machine learning", "ml", "training", "model", "dataset",
                "tensorflow", "pytorch", "huggingface"
            ],
            NewsCategory.CYBERSECURITY: [
                "security", "hack", "breach", "vulnerability", "ransomware",
                "malware", "phishing", "zero-day", "encryption"
            ],
            NewsCategory.CLOUD_COMPUTING: [
                "aws", "azure", "gcp", "cloud", "kubernetes", "docker",
                "serverless", "saas", "iaas", "paas"
            ],
            NewsCategory.FINTECH_PAYMENTS: [
                "fintech", "payment", "stripe", "banking", "neobank",
                "debit", "credit", "wallet", "transaction"
            ],
            NewsCategory.BLOCKCHAIN_CRYPTO: [
                "blockchain", "crypto", "bitcoin", "ethereum", "defi",
                "nft", "web3", "token", "mining"
            ],
            NewsCategory.STARTUPS_FUNDING: [
                "startup", "funding", "series", "vc", "venture",
                "seed", "unicorn", "valuation", "investor"
            ],
            NewsCategory.SEMICONDUCTORS: [
                "chip", "semiconductor", "nvidia", "intel", "amd",
                "tsmc", "processor", "gpu", "cpu"
            ],
            NewsCategory.ROBOTICS_AUTOMATION: [
                "robot", "automation", "industrial", "manufacturing",
                "boston dynamics", "warehouse", "rpa"
            ],
            NewsCategory.HEALTHCARE_TECH: [
                "healthtech", "medtech", "telemedicine", "biotech",
                "genomics", "clinical", "fda", "healthcare"
            ],
        }
        
        for category in NewsCategory:
            keywords = category_keywords.get(category, [])
            self._categories[category.value] = CategoryConfig(
                name=category.value,
                keywords=keywords,
                enabled=True
            )
    
    def _load_custom_categories(self):
        """Load custom categories from YAML config."""
        if not self.config_path.exists():
            return
        
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            
            custom_categories = config.get("categories", [])
            
            for cat_config in custom_categories:
                name = cat_config.get("name")
                if not name:
                    continue
                
                # Skip if already exists (don't overwrite)
                if name in self._categories:
                    logger.debug(f"Category '{name}' already exists, skipping")
                    continue
                
                self._categories[name] = CategoryConfig(
                    name=name,
                    keywords=cat_config.get("keywords", []),
                    description=cat_config.get("description", ""),
                    parent_category=cat_config.get("parent"),
                    enabled=cat_config.get("enabled", True)
                )
                logger.info(f"Loaded custom category: {name}")
                
        except Exception as e:
            logger.warning(f"Failed to load custom categories: {e}")
    
    def add_category(
        self,
        name: str,
        keywords: Optional[List[str]] = None,
        description: str = "",
        save: bool = True
    ) -> bool:
        """
        Add a new category.
        
        Args:
            name: Category name
            keywords: Classification keywords
            description: Category description
            save: Whether to persist to YAML
            
        Returns:
            True if added, False if already exists
        """
        if name in self._categories:
            logger.debug(f"Category '{name}' already exists")
            return False
        
        self._categories[name] = CategoryConfig(
            name=name,
            keywords=keywords or [],
            description=description,
            enabled=True
        )
        
        if save:
            self._save_custom_categories()
        
        logger.info(f"Added new category: {name}")
        return True
    
    def _save_custom_categories(self):
        """Save custom categories to YAML."""
        # Only save categories not in the enum
        builtin_names = {c.value for c in NewsCategory}
        custom = [
            {
                "name": cat.name,
                "keywords": cat.keywords,
                "description": cat.description,
                "enabled": cat.enabled,
            }
            for cat in self._categories.values()
            if cat.name not in builtin_names
        ]
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_path, "w") as f:
            yaml.dump({"categories": custom}, f, default_flow_style=False)
    
    def get_all_categories(self, enabled_only: bool = True) -> List[str]:
        """Get list of all category names."""
        return [
            name for name, config in self._categories.items()
            if not enabled_only or config.enabled
        ]
    
    def get_category_keywords(self, category: str) -> List[str]:
        """Get keywords for a category."""
        config = self._categories.get(category)
        return config.keywords if config else []
    
    def find_categories_by_keywords(
        self, 
        text: str, 
        max_categories: int = 3
    ) -> List[tuple[str, int]]:
        """
        Find matching categories based on keyword presence.
        
        Args:
            text: Text to analyze
            max_categories: Maximum categories to return
            
        Returns:
            List of (category_name, match_count) tuples sorted by match count
        """
        text_lower = text.lower()
        matches = []
        
        for name, config in self._categories.items():
            if not config.enabled:
                continue
            
            match_count = sum(
                1 for kw in config.keywords
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', text_lower)
            )
            
            if match_count > 0:
                matches.append((name, match_count))
        
        # Sort by match count descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:max_categories]


class NewsClassifier:
    """
    Classifies news articles into categories.
    
    Uses hybrid approach:
    1. Keyword matching for fast initial classification
    2. LLM for ambiguous cases or when high accuracy needed
    """
    
    CLASSIFICATION_PROMPT = """Classify the following news article into the most appropriate categories.

Available categories:
{categories}

ARTICLE TITLE: {title}
ARTICLE SUMMARY: {summary}

Return your classification as JSON with:
- primary_category: The single most relevant category
- secondary_categories: Up to 2 additional relevant categories (array)
- confidence: Your confidence in the primary category (0.0-1.0)
- keywords_matched: Key terms that influenced your decision (array)

Be precise. Only select categories that genuinely apply."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        category_manager: Optional[CategoryManager] = None
    ):
        self._provider = provider
        self.categories = category_manager or CategoryManager()
    
    @property
    def provider(self) -> LLMProvider:
        """Lazy initialization of LLM provider."""
        if self._provider is None:
            self._provider = get_provider()
        return self._provider
    
    async def classify(
        self,
        title: str,
        summary: str = "",
        use_llm: bool = False
    ) -> ClassificationResult:
        """
        Classify an article into categories.
        
        Args:
            title: Article title
            summary: Article summary or content snippet
            use_llm: Force LLM classification (slower, more accurate)
            
        Returns:
            ClassificationResult with categories and confidence
        """
        combined_text = f"{title} {summary}"
        
        # First, try keyword matching
        keyword_matches = self.categories.find_categories_by_keywords(combined_text)
        
        if keyword_matches and not use_llm:
            # Use keyword-based classification
            primary = keyword_matches[0][0]
            secondary = [m[0] for m in keyword_matches[1:3]]
            
            # Confidence based on keyword match strength
            max_matches = keyword_matches[0][1]
            confidence = min(0.9, 0.5 + (max_matches * 0.1))
            
            return ClassificationResult(
                primary_category=primary,
                secondary_categories=secondary,
                confidence=confidence,
                keywords_matched=[
                    kw for kw in self.categories.get_category_keywords(primary)
                    if kw.lower() in combined_text.lower()
                ][:5]
            )
        
        # Use LLM for classification
        try:
            categories_list = "\n".join(
                f"- {cat}" for cat in self.categories.get_all_categories()
            )
            
            prompt = self.CLASSIFICATION_PROMPT.format(
                categories=categories_list,
                title=title,
                summary=summary[:500]
            )
            
            result = await self.provider.analyze(
                prompt=prompt,
                schema=ClassificationResult
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            # Fallback to generic category
            return ClassificationResult(
                primary_category=NewsCategory.TECHNOLOGY_INNOVATION.value,
                secondary_categories=[],
                confidence=0.3,
                keywords_matched=[]
            )
    
    async def batch_classify(
        self,
        articles: List[Dict[str, Any]],
        use_llm: bool = False
    ) -> List[ClassificationResult]:
        """Classify multiple articles."""
        import asyncio
        
        tasks = [
            self.classify(
                title=article.get("title", ""),
                summary=article.get("ai_summary") or article.get("content", "")[:300],
                use_llm=use_llm
            )
            for article in articles
        ]
        
        return await asyncio.gather(*tasks)


# Default classifier instance
_default_classifier: Optional[NewsClassifier] = None


def get_classifier() -> NewsClassifier:
    """Get or create the default news classifier."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = NewsClassifier()
    return _default_classifier
