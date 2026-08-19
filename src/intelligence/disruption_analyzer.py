"""
Market Disruption Analyzer for Tech News Scraper v3.0

Analyzes articles for market disruption potential using LLM-powered analysis.
Provides structured output with:
- Disruption assessment (boolean)
- Criticality score (1-10)
- Justification
- Affected markets and companies
- Sentiment analysis
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .llm_provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


class Sentiment(str, Enum):
    """Article sentiment classifications."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class DisruptionAnalysis(BaseModel):
    """
    Structured output for disruption analysis.
    
    This schema is passed to the LLM for structured JSON output.
    """
    disruptive: bool = Field(
        description="Whether the news represents a significant market disruption"
    )
    criticality: int = Field(
        ge=1, le=10,
        description="Criticality score from 1 (low) to 10 (critical)"
    )
    justification: str = Field(
        description="Explanation of why this is/isn't disruptive"
    )
    affected_markets: List[str] = Field(
        default_factory=list,
        description="List of markets/industries affected by this news"
    )
    affected_companies: List[str] = Field(
        default_factory=list,
        description="List of companies directly or indirectly affected"
    )
    sentiment: Literal["positive", "negative", "neutral", "mixed"] = Field(
        default="neutral",
        description="Overall sentiment of the news for the tech industry"
    )
    key_insights: List[str] = Field(
        default_factory=list,
        description="Key takeaways from the article (max 3)"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "disruptive": True,
                "criticality": 8,
                "justification": "OpenAI's new platform could replace existing dev tools",
                "affected_markets": ["AI tooling", "Developer platforms", "IDE market"],
                "affected_companies": ["GitHub", "JetBrains", "Microsoft"],
                "sentiment": "mixed",
                "key_insights": [
                    "Platform targets enterprise developers",
                    "Free tier available for startups",
                    "Integrates with existing CI/CD pipelines"
                ]
            }
        }
    }


@dataclass
class IndustryContext:
    """
    Context for industry-specific disruption analysis.
    
    Primary industry is always Tech, with optional secondary industries.
    """
    primary: str = "Technology"
    secondary: List[str] = None
    competitors: List[str] = None
    keywords: List[str] = None
    
    def __post_init__(self):
        if self.secondary is None:
            self.secondary = []
        if self.competitors is None:
            self.competitors = []
        if self.keywords is None:
            self.keywords = []
    
    def to_prompt_context(self) -> str:
        """Generate context string for LLM prompt."""
        parts = [f"Primary Industry: {self.primary}"]
        
        if self.secondary:
            parts.append(f"Secondary Industries: {', '.join(self.secondary)}")
        if self.competitors:
            parts.append(f"Key Competitors to Monitor: {', '.join(self.competitors)}")
        if self.keywords:
            parts.append(f"Relevant Keywords: {', '.join(self.keywords)}")
        
        return "\n".join(parts)


# Default industry contexts
DEFAULT_TECH_CONTEXT = IndustryContext(
    primary="Technology",
    secondary=[
        "Artificial Intelligence",
        "Cloud Computing",
        "Enterprise Software",
        "Cybersecurity",
        "Fintech"
    ],
    competitors=[
        "Google", "Microsoft", "Amazon", "Apple", "Meta",
        "OpenAI", "Anthropic", "NVIDIA", "Salesforce"
    ],
    keywords=[
        "AI", "machine learning", "cloud", "SaaS", "startup",
        "funding", "acquisition", "IPO", "layoffs", "regulation"
    ]
)


class DisruptionAnalyzer:
    """
    Analyzes articles for market disruption using LLM-powered analysis.
    
    Uses the Hybrid LLM provider (Gemini for analysis, local for summaries).
    """
    
    ANALYSIS_PROMPT_TEMPLATE = """You are a senior technology market analyst. Analyze the following news article for market disruption potential.

{context}

ARTICLE TITLE: {title}

ARTICLE CONTENT:
{content}

Analyze this article and determine:
1. Is this news disruptive to the technology market or related industries?
2. Rate the criticality from 1-10 (10 = major market shift, 1 = minor news)
3. Explain your reasoning in the justification
4. Identify affected markets/industries
5. Identify affected companies (both positively and negatively)
6. Determine overall sentiment for the tech industry
7. Extract 2-3 key insights

Be specific and analytical. Consider:
- Competitive implications
- Market timing and maturity
- Potential for widespread adoption
- Impact on existing players
- Investment/funding implications

Respond with valid JSON matching the requested schema."""

    def __init__(
        self, 
        provider: Optional[LLMProvider] = None,
        default_context: Optional[IndustryContext] = None
    ):
        """
        Initialize the disruption analyzer.
        
        Args:
            provider: LLM provider (defaults to Hybrid)
            default_context: Default industry context for analysis
        """
        self._provider = provider
        self._default_context = default_context or DEFAULT_TECH_CONTEXT
        
    @property
    def provider(self) -> LLMProvider:
        """Lazy initialization of LLM provider."""
        if self._provider is None:
            self._provider = get_provider()
        return self._provider
    
    async def analyze(
        self,
        title: str,
        content: str,
        context: Optional[IndustryContext] = None,
        url: Optional[str] = None
    ) -> DisruptionAnalysis:
        """
        Analyze an article for market disruption.
        
        Args:
            title: Article title
            content: Article content (full text or summary)
            context: Optional industry context (uses default if None)
            url: Optional URL for logging
            
        Returns:
            DisruptionAnalysis with structured assessment
        """
        ctx = context or self._default_context
        
        # Truncate content to avoid token limits
        truncated_content = content[:4000] if len(content) > 4000 else content
        
        prompt = self.ANALYSIS_PROMPT_TEMPLATE.format(
            context=ctx.to_prompt_context(),
            title=title,
            content=truncated_content
        )
        
        try:
            logger.info(f"Analyzing disruption for: {title[:50]}...")
            
            analysis = await self.provider.analyze(
                prompt=prompt,
                schema=DisruptionAnalysis
            )
            
            logger.info(
                f"Analysis complete: disruption={analysis.disruptive}, "
                f"criticality={analysis.criticality}"
            )
            
            return analysis
            
        except Exception as e:
            logger.error(f"Disruption analysis failed for '{title}': {e}")
            # Return a default non-disruptive analysis on error
            return DisruptionAnalysis(
                disruptive=False,
                criticality=1,
                justification=f"Analysis failed: {str(e)[:100]}",
                affected_markets=[],
                affected_companies=[],
                sentiment="neutral",
                key_insights=[]
            )
    
    async def batch_analyze(
        self,
        articles: List[Dict[str, Any]],
        context: Optional[IndustryContext] = None,
        max_concurrent: int = 5
    ) -> List[DisruptionAnalysis]:
        """
        Analyze multiple articles concurrently.
        
        Args:
            articles: List of article dicts with 'title' and 'content' keys
            context: Optional industry context
            max_concurrent: Maximum concurrent analyses
            
        Returns:
            List of DisruptionAnalysis results
        """
        import asyncio
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_with_semaphore(article: Dict[str, Any]) -> DisruptionAnalysis:
            async with semaphore:
                return await self.analyze(
                    title=article.get("title", ""),
                    content=article.get("content") or article.get("ai_summary", ""),
                    context=context,
                    url=article.get("url")
                )
        
        tasks = [analyze_with_semaphore(article) for article in articles]
        return await asyncio.gather(*tasks)
    
    def get_criticality_label(self, criticality: int) -> str:
        """Get human-readable label for criticality score."""
        if criticality >= 9:
            return "🔴 CRITICAL"
        elif criticality >= 7:
            return "🟠 HIGH"
        elif criticality >= 4:
            return "🟡 MEDIUM"
        else:
            return "🟢 LOW"


# Create default analyzer instance
_default_analyzer: Optional[DisruptionAnalyzer] = None


def get_analyzer() -> DisruptionAnalyzer:
    """Get or create the default disruption analyzer."""
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = DisruptionAnalyzer()
    return _default_analyzer
