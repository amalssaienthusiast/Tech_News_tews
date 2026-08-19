"""
Newsletter Generator Module for Tech News Scraper v4.1

AI-powered newsletter generation using LangGraph:
- Automated story selection via AI Editor
- Human-in-the-loop approval (GUI + Slack)
- Structured section writing
- Scheduled generation
- Export: Markdown, Beehiiv
"""

from .state import NewsletterState
from .editor import AIEditor, EditorSelection
from .writer import NewsletterWriter
from .workflow import (
    NewsletterWorkflow,
    generate_newsletter,
)
from .slack import SlackApproval, get_slack_approval
from .scheduler import NewsletterScheduler, get_scheduler

__all__ = [
    "NewsletterState",
    "AIEditor",
    "EditorSelection",
    "NewsletterWriter",
    "NewsletterWorkflow",
    "generate_newsletter",
    # v4.1 additions
    "SlackApproval",
    "get_slack_approval",
    "NewsletterScheduler",
    "get_scheduler",
]
