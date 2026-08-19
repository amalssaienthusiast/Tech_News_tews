"""Personalization module for Tech News Scraper."""

from src.personalization.engine import (
    PersonalizationEngine,
    ScoredArticle,
    get_personalization_engine,
)

__all__ = [
    "PersonalizationEngine",
    "ScoredArticle",
    "get_personalization_engine",
]
