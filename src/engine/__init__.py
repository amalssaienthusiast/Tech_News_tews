"""
Engine module - Core business logic.

Provides the intelligent components for the scraper:
- QueryEngine: Query understanding and validation
- DeepScraper: Multi-layer web scraping
- URLAnalyzer: Deep content analysis
- TechNewsOrchestrator: Central coordination
"""

from src.engine.query_engine import (
    QueryEngine,
    QueryType,
    ExpandedQuery,
)

from src.engine.deep_scraper import (
    DeepScraper,
    ContentExtractor,
    LinkDiscoveryAlgorithm,
    ScrapedContent,
    LinkScore,
)

from src.engine.url_analyzer import (
    URLAnalyzer,
    URLAnalysisResult,
    EntityExtraction,
    KeyPoint,
    EntityExtractor,
    KeyPointExtractor,
    SentimentAnalyzer,
)

from src.engine.orchestrator import (
    TechNewsOrchestrator,
    SearchResult,
    PREMIUM_SOURCES,
    QUALITY_SOURCES,
)

from src.engine.enhanced_feeder import (
    EnhancedRealtimeFeeder,
    EnhancedNewsPipeline,
)

__all__ = [
    # Query Engine
    "QueryEngine",
    "QueryType",
    "ExpandedQuery",
    # Deep Scraper
    "DeepScraper",
    "ContentExtractor",
    "LinkDiscoveryAlgorithm",
    "ScrapedContent",
    "LinkScore",
    # URL Analyzer
    "URLAnalyzer",
    "URLAnalysisResult",
    "EntityExtraction",
    "KeyPoint",
    "EntityExtractor",
    "KeyPointExtractor",
    "SentimentAnalyzer",
    # Orchestrator
    "TechNewsOrchestrator",
    "SearchResult",
    "PREMIUM_SOURCES",
    "QUALITY_SOURCES",
    # Enhanced Pipeline
    "EnhancedRealtimeFeeder",
    "EnhancedNewsPipeline",
]
