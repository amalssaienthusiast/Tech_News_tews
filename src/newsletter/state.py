"""
Newsletter State Schema for LangGraph

Defines the state that flows through the newsletter generation workflow.
"""

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


class StorySelection(BaseModel):
    """A selected story for the newsletter."""
    article_id: str
    title: str
    url: str
    source: str
    criticality: int = 1
    is_disruptive: bool = False
    summary: str = ""
    full_content: str = ""
    section_text: str = ""  # Generated newsletter section


class NewsletterState(TypedDict):
    """
    State schema for newsletter generation workflow.
    
    This state flows through all nodes in the LangGraph workflow.
    """
    
    # ─── Inputs ───
    target_date: str
    previous_newsletter: Optional[str]
    newsletter_name: str
    
    # ─── Story Loading ───
    available_stories: List[Dict[str, Any]]  # Raw from database
    analyzed_count: int
    
    # ─── AI Editor Output ───
    top_stories: List[StorySelection]
    editor_reasoning: str
    shortlist_stories: List[Dict[str, Any]]  # Other notable stories
    
    # ─── Human Review ───
    human_approved: bool
    human_feedback: Optional[str]
    review_attempts: int
    
    # ─── Content Generation ───
    subject_line: str
    subject_alternatives: List[str]
    intro_text: str
    sections: List[str]  # One per top story
    shortlist_text: str
    outro_text: str
    
    # ─── Final Output ───
    final_markdown: str
    export_path: str
    generated_at: str
    
    # ─── Status ───
    current_step: str
    error: Optional[str]


def create_initial_state(
    target_date: Optional[str] = None,
    newsletter_name: str = "Tech Intelligence Daily"
) -> NewsletterState:
    """Create initial state for newsletter generation."""
    return NewsletterState(
        target_date=target_date or datetime.now().strftime("%Y-%m-%d"),
        previous_newsletter=None,
        newsletter_name=newsletter_name,
        available_stories=[],
        analyzed_count=0,
        top_stories=[],
        editor_reasoning="",
        shortlist_stories=[],
        human_approved=False,
        human_feedback=None,
        review_attempts=0,
        subject_line="",
        subject_alternatives=[],
        intro_text="",
        sections=[],
        shortlist_text="",
        outro_text="",
        final_markdown="",
        export_path="",
        generated_at="",
        current_step="initialized",
        error=None
    )
