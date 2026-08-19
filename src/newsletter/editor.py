"""
AI Editor for Newsletter Story Selection

Uses LLM to intelligently select top stories for the newsletter
based on criticality, disruption potential, and audience relevance.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EditorSelection(BaseModel):
    """Structured output from AI Editor."""
    selected_ids: List[str] = Field(description="Article IDs of selected stories")
    reasoning: str = Field(description="Explanation of selection criteria")
    shortlist_ids: List[str] = Field(default_factory=list, description="IDs for shortlist section")


class AIEditor:
    """
    AI-powered story editor that selects top stories for newsletter.
    
    Uses existing LLMProvider from intelligence module for consistency.
    """
    
    SYSTEM_PROMPT = """You are the Editor-in-Chief of "Tech Intelligence Daily", a premium tech newsletter.

Your job is to select the TOP 4 most impactful stories for today's edition.

SELECTION CRITERIA (in order of priority):
1. **Market Impact** - Stories that significantly affect the tech industry
2. **Criticality Score** - Higher scores mean more important news
3. **Disruption Potential** - News that changes how things work
4. **Reader Value** - What our tech-savvy audience cares about
5. **Diversity** - Cover different topics (AI, Security, Startups, etc.)

AVOID:
- Duplicate or very similar stories
- Minor updates or incremental news
- Stories from the previous newsletter (if provided)
- Pure opinion pieces without news value

You must return your selection as structured JSON."""

    def __init__(self):
        """Initialize AI Editor."""
        self._provider = None
    
    def _get_provider(self):
        """Lazy load LLM provider."""
        if self._provider is None:
            from src.intelligence import get_provider
            self._provider = get_provider()
        return self._provider
    
    async def select_stories(
        self,
        available_stories: List[Dict[str, Any]],
        max_top: int = 4,
        max_shortlist: int = 10,
        previous_newsletter: Optional[str] = None
    ) -> EditorSelection:
        """
        Select top stories for newsletter.
        
        Args:
            available_stories: List of analyzed articles from database
            max_top: Maximum stories for main sections
            max_shortlist: Maximum stories for shortlist
            previous_newsletter: Previous edition to avoid duplicates
            
        Returns:
            EditorSelection with selected story IDs and reasoning
        """
        if not available_stories:
            logger.warning("No stories available for selection")
            return EditorSelection(
                selected_ids=[],
                reasoning="No stories available",
                shortlist_ids=[]
            )
        
        # Format stories for LLM
        stories_text = self._format_stories_for_llm(available_stories)
        
        prompt = f"""Today's date: {available_stories[0].get('scraped_at', 'today')[:10]}

AVAILABLE STORIES ({len(available_stories)} total):

{stories_text}

---

Select the TOP {max_top} stories for the main newsletter sections.
Also select up to {max_shortlist} additional stories for the "Shortlist" section.

{"PREVIOUS NEWSLETTER (avoid these stories):" + previous_newsletter[:500] if previous_newsletter else ""}

Return your selection as JSON:
{{
  "selected_ids": ["id1", "id2", "id3", "id4"],
  "reasoning": "Why these stories were selected...",
  "shortlist_ids": ["id5", "id6", ...]
}}"""

        try:
            provider = self._get_provider()
            result = await provider.analyze(
                prompt=prompt,
                schema=EditorSelection,
                context=self.SYSTEM_PROMPT
            )
            
            if isinstance(result, EditorSelection):
                logger.info(f"AI Editor selected {len(result.selected_ids)} top stories")
                return result
            else:
                # Parse if string returned
                import json
                data = json.loads(result) if isinstance(result, str) else result
                return EditorSelection(**data)
                
        except Exception as e:
            logger.error(f"AI Editor failed: {e}")
            # Fallback: select by criticality score
            return self._fallback_selection(available_stories, max_top, max_shortlist)
    
    def _format_stories_for_llm(
        self,
        stories: List[Dict[str, Any]],
        max_per_story: int = 300
    ) -> str:
        """Format stories for LLM context."""
        lines = []
        
        for i, story in enumerate(stories[:50], 1):  # Limit to 50 for context
            criticality = story.get('criticality', 0)
            disruptive = "🔥" if story.get('disruptive') else ""
            
            # Criticality badge
            if criticality >= 9:
                badge = "🔴 CRITICAL"
            elif criticality >= 7:
                badge = "🟠 HIGH"
            elif criticality >= 4:
                badge = "🟡 MEDIUM"
            else:
                badge = "🟢 LOW"
            
            title = story.get('title', 'Untitled')[:100]
            source = story.get('source', 'Unknown')
            summary = story.get('ai_summary', story.get('justification', ''))[:max_per_story]
            article_id = story.get('id', f'story_{i}')
            categories = story.get('categories', [])
            
            lines.append(f"""
[{i}] ID: {article_id}
    {badge} {disruptive} Criticality: {criticality}/10
    Title: {title}
    Source: {source}
    Categories: {', '.join(categories[:3]) if categories else 'General'}
    Summary: {summary}
""")
        
        return "\n".join(lines)
    
    def _fallback_selection(
        self,
        stories: List[Dict[str, Any]],
        max_top: int,
        max_shortlist: int
    ) -> EditorSelection:
        """Fallback selection based on criticality scores."""
        sorted_stories = sorted(
            stories,
            key=lambda x: (x.get('criticality', 0), x.get('disruptive', False)),
            reverse=True
        )
        
        top_ids = [s.get('id', '') for s in sorted_stories[:max_top] if s.get('id')]
        shortlist_ids = [s.get('id', '') for s in sorted_stories[max_top:max_top + max_shortlist] if s.get('id')]
        
        return EditorSelection(
            selected_ids=top_ids,
            reasoning="Selected by highest criticality scores (AI Editor unavailable)",
            shortlist_ids=shortlist_ids
        )


# Singleton instance
_editor: Optional[AIEditor] = None


def get_editor() -> AIEditor:
    """Get or create AI Editor instance."""
    global _editor
    if _editor is None:
        _editor = AIEditor()
    return _editor
