"""
Newsletter Writer for Content Generation

Generates newsletter sections, intros, and shortlists using LLM.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .state import StorySelection

logger = logging.getLogger(__name__)


class SectionOutput(BaseModel):
    """Generated newsletter section."""
    headline: str = Field(description="Section headline")
    body: str = Field(description="Section body text")
    key_insight: str = Field(description="Key takeaway for readers")


class SubjectLineOutput(BaseModel):
    """Generated subject lines."""
    primary: str = Field(description="Primary subject line")
    alternatives: List[str] = Field(description="Alternative options")


class NewsletterWriter:
    """
    AI-powered newsletter content writer.
    
    Uses existing LLMProvider and writes structured newsletter sections.
    """
    
    SECTION_PROMPT = """You are writing a newsletter section for "Tech Intelligence Daily".

STORY TO COVER:
Title: {title}
Source: {source}
Criticality: {criticality}/10
Content: {content}

Write a compelling newsletter section following this structure:
1. **Headline** - Engaging, attention-grabbing (max 10 words)
2. **Body** - 2-3 paragraphs covering:
   - What happened
   - Why it matters
   - Impact on tech industry
3. **Key Insight** - One sentence takeaway

Keep it informative but engaging. Write for a tech-savvy audience.
Max 300 words for the body."""

    INTRO_PROMPT = """Write an engaging intro paragraph for today's tech newsletter.

TODAY'S TOP STORIES:
{stories_summary}

Write a 2-3 sentence intro that:
- Greets the reader warmly
- Hints at the exciting content
- Sets the tone for the newsletter

Keep it under 50 words. Be conversational but professional."""

    SHORTLIST_PROMPT = """Create a "Shortlist" section for other notable tech stories.

STORIES:
{stories}

Format as a bulleted list with:
- Story title (linked)
- One sentence description

Keep each item under 25 words."""

    SUBJECT_PROMPT = """Write email subject lines for today's tech newsletter.

TOP STORIES COVERED:
{stories_summary}

Create:
1. One primary subject line (best option)
2. Three alternative subject lines

Requirements:
- Max 60 characters
- Create urgency/curiosity
- Mention the most impactful story
- Avoid spam trigger words"""

    def __init__(self):
        """Initialize writer."""
        self._provider = None
    
    def _get_provider(self):
        """Lazy load LLM provider."""
        if self._provider is None:
            from src.intelligence import get_provider
            self._provider = get_provider()
        return self._provider
    
    async def write_section(
        self,
        story: StorySelection
    ) -> str:
        """
        Write a newsletter section for a story.
        
        Args:
            story: Story to write about
            
        Returns:
            Formatted markdown section
        """
        prompt = self.SECTION_PROMPT.format(
            title=story.title,
            source=story.source,
            criticality=story.criticality,
            content=story.full_content[:3000] or story.summary
        )
        
        try:
            provider = self._get_provider()
            result = await provider.analyze(prompt, schema=SectionOutput)
            
            if isinstance(result, SectionOutput):
                return self._format_section(result, story.url)
            elif isinstance(result, dict):
                return self._format_section(SectionOutput(**result), story.url)
            else:
                # Parse string response
                return self._fallback_section(story)
                
        except Exception as e:
            logger.error(f"Failed to write section: {e}")
            return self._fallback_section(story)
    
    def _format_section(self, section: SectionOutput, url: str) -> str:
        """Format section as markdown."""
        return f"""## {section.headline}

{section.body}

💡 **Key Insight:** {section.key_insight}

🔗 [Read more]({url})

---
"""
    
    def _fallback_section(self, story: StorySelection) -> str:
        """Simple fallback section formatting."""
        return f"""## {story.title}

{story.summary or "Read the full article for details."}

🔗 [Read more]({story.url})

---
"""
    
    async def write_intro(
        self,
        stories: List[StorySelection],
        newsletter_name: str = "Tech Intelligence Daily"
    ) -> str:
        """
        Write newsletter intro paragraph.
        
        Args:
            stories: Top stories being featured
            newsletter_name: Name of newsletter
            
        Returns:
            Intro text
        """
        stories_summary = "\n".join([
            f"- {s.title} ({s.source})"
            for s in stories[:4]
        ])
        
        prompt = self.INTRO_PROMPT.format(stories_summary=stories_summary)
        
        try:
            provider = self._get_provider()
            result = await provider.analyze(prompt)
            return str(result).strip()
        except Exception as e:
            logger.error(f"Failed to write intro: {e}")
            return f"Welcome to {newsletter_name}! Here's what's making waves in tech today."
    
    async def write_shortlist(
        self,
        stories: List[Dict[str, Any]]
    ) -> str:
        """
        Write the shortlist section.
        
        Args:
            stories: Additional notable stories
            
        Returns:
            Formatted shortlist markdown
        """
        if not stories:
            return ""
        
        stories_text = "\n".join([
            f"- {s.get('title', 'Untitled')}: {s.get('ai_summary', '')[:100]}"
            for s in stories[:10]
        ])
        
        prompt = self.SHORTLIST_PROMPT.format(stories=stories_text)
        
        try:
            provider = self._get_provider()
            result = await provider.analyze(prompt)
            
            # Format as markdown
            return f"""## 📋 The Shortlist

Other stories worth your attention:

{result}
"""
        except Exception as e:
            logger.error(f"Failed to write shortlist: {e}")
            # Fallback: simple list
            items = "\n".join([
                f"- [{s.get('title', 'Story')[:50]}]({s.get('url', '#')})"
                for s in stories[:10]
            ])
            return f"""## 📋 The Shortlist

{items}
"""
    
    async def generate_subject_line(
        self,
        stories: List[StorySelection]
    ) -> tuple[str, List[str]]:
        """
        Generate subject line for newsletter email.
        
        Args:
            stories: Top stories
            
        Returns:
            Tuple of (primary_subject, alternatives)
        """
        stories_summary = "\n".join([
            f"- {s.title} (Criticality: {s.criticality}/10)"
            for s in stories[:4]
        ])
        
        prompt = self.SUBJECT_PROMPT.format(stories_summary=stories_summary)
        
        try:
            provider = self._get_provider()
            result = await provider.analyze(prompt, schema=SubjectLineOutput)
            
            if isinstance(result, SubjectLineOutput):
                return result.primary, result.alternatives
            elif isinstance(result, dict):
                output = SubjectLineOutput(**result)
                return output.primary, output.alternatives
            else:
                # Parse from text
                return str(result)[:60], []
                
        except Exception as e:
            logger.error(f"Failed to generate subject: {e}")
            if stories:
                return f"🔥 {stories[0].title[:50]}", []
            return "Today's Tech Intelligence Briefing", []
    
    def assemble_newsletter(
        self,
        newsletter_name: str,
        date: str,
        subject: str,
        intro: str,
        sections: List[str],
        shortlist: str
    ) -> str:
        """
        Assemble final newsletter markdown.
        
        Args:
            newsletter_name: Newsletter title
            date: Edition date
            subject: Email subject
            intro: Intro paragraph
            sections: List of story sections
            shortlist: Shortlist section
            
        Returns:
            Complete newsletter as markdown
        """
        date_formatted = datetime.strptime(date, "%Y-%m-%d").strftime("%B %d, %Y")
        
        sections_text = "\n".join(sections)
        
        return f"""# {newsletter_name}

**{date_formatted}**

*Subject: {subject}*

---

{intro}

---

{sections_text}

{shortlist}

---

*That's all for today! Forward this to a friend who loves tech, or reply with your thoughts.*

---

📧 *{newsletter_name} - AI-Curated Tech Intelligence*
*Generated by Tech News Scraper v4.0*
"""


# Singleton instance
_writer: Optional[NewsletterWriter] = None


def get_writer() -> NewsletterWriter:
    """Get or create writer instance."""
    global _writer
    if _writer is None:
        _writer = NewsletterWriter()
    return _writer
