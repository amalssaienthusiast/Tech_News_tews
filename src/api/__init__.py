# Tech News Scraper API Package
# Authoritative Production FastAPI Application

from .app import app
from .routes.articles import get_article_repository, set_article_repository
from .routes.events import get_event_repository, set_event_repository

__all__ = [
    "app",
    "get_article_repository",
    "set_article_repository",
    "get_event_repository",
    "set_event_repository",
]
