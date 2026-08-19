"""
Intelligence Module for Tech News Scraper v3.0

This module provides AI-powered market intelligence capabilities:
- LLM Provider abstraction (Gemini + LangChain)
- Market Disruption Analysis
- News Classification (25+ categories)
- Alert Engine with configurable channels
- Criticality Scoring
"""

from .llm_provider import (
    LLMProvider,
    GeminiProvider,
    LangChainGeminiProvider,
    get_provider,
    LLMConfig,
)
from .disruption_analyzer import (
    DisruptionAnalyzer,
    DisruptionAnalysis,
    IndustryContext,
)
from .news_classifier import (
    NewsClassifier,
    CategoryManager,
    NewsCategory,
)
from .alert_engine import (
    AlertEngine,
    Alert,
    AlertChannel,
    AlertConfig,
)

__all__ = [
    # LLM Provider
    "LLMProvider",
    "GeminiProvider", 
    "LangChainGeminiProvider",
    "get_provider",
    "LLMConfig",
    # Disruption Analysis
    "DisruptionAnalyzer",
    "DisruptionAnalysis",
    "IndustryContext",
    # Classification
    "NewsClassifier",
    "CategoryManager",
    "NewsCategory",
    # Alerts
    "AlertEngine",
    "Alert",
    "AlertChannel",
    "AlertConfig",
]
