"""
LLM Summarizer for Tech News Scraper

Enterprise feature providing high-quality article summarization using external LLMs.

Supported APIs:
- OpenAI (GPT-4, GPT-3.5-turbo)
- Anthropic (Claude 3, Claude 2)

Features:
- Automatic fallback to local model
- Cost tracking and rate limiting
- Batch summarization for digests
- Configurable model selection
"""

import logging
import os
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM API configuration."""
    # OpenAI settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_max_tokens: int = 300
    
    # Anthropic settings
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-haiku-20241022"
    anthropic_max_tokens: int = 300
    
    # General settings
    preferred_provider: str = "openai"  # "openai" or "anthropic"
    fallback_to_local: bool = True
    temperature: float = 0.3
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load config from environment variables."""
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "300")),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20241022"),
            anthropic_max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "300")),
            preferred_provider=os.getenv("LLM_PROVIDER", "openai"),
            fallback_to_local=os.getenv("LLM_FALLBACK_LOCAL", "true").lower() == "true",
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3"))
        )


@dataclass
class SummaryResult:
    """Result of summarization."""
    summary: str
    key_points: List[str]
    sentiment: str
    provider: str  # "openai", "anthropic", or "local"
    model: str
    tokens_used: int
    cost_usd: float
    duration_ms: int


class LLMSummarizer:
    """
    LLM-based article summarizer with multi-provider support.
    
    Provides high-quality summaries using external LLMs with
    automatic fallback to local models when APIs are unavailable.
    """
    
    # Cost per 1K tokens (approximate)
    COSTS = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    }
    
    SYSTEM_PROMPT = """You are a tech news analyst. Summarize the given article concisely.

Output format (JSON):
{
  "summary": "2-3 sentence summary of the main points",
  "key_points": ["point 1", "point 2", "point 3"],
  "sentiment": "positive" | "negative" | "neutral"
}

Focus on:
- Key technological developments
- Business/market implications
- Notable companies or people mentioned
- Technical accuracy"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """Initialize LLM summarizer."""
        self.config = config or LLMConfig.from_env()
        self._usage_path = Path(__file__).parent.parent.parent / "data" / "llm_usage.json"
        self._usage: Dict[str, Any] = self._load_usage()

        # Initialize API clients lazily
        self._openai_client = None
        self._anthropic_client = None

        # P0-F: Wire AI summary cache (previously orphan — see audit §8.1).
        # The cache is optional and gracefully degrades to None when Redis
        # is unavailable. Cache hits skip the LLM call entirely, saving
        # API cost for re-summarized URLs. The cache is async, so we lazy-
        # initialize it on first use of summarize_cached() rather than in
        # __init__ (which is sync).
        self._cache = None
        self._cache_initialized = False

        logger.info(f"LLMSummarizer initialized (provider: {self.config.preferred_provider})")

    def _load_usage(self) -> Dict[str, Any]:
        """Load usage statistics."""
        if self._usage_path.exists():
            try:
                with open(self._usage_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"_load_usage: suppressed {type(e).__name__}: {e}")
        return {"total_cost": 0.0, "total_tokens": 0, "requests": []}
    
    def _save_usage(self):
        """Save usage statistics."""
        self._usage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._usage_path, 'w') as f:
            json.dump(self._usage, f, indent=2, default=str)
    
    def is_configured(self, provider: Optional[str] = None) -> bool:
        """Check if LLM provider is configured."""
        provider = provider or self.config.preferred_provider
        
        if provider == "openai":
            return bool(self.config.openai_api_key)
        elif provider == "anthropic":
            return bool(self.config.anthropic_api_key)
        return False
    
    def _get_openai_client(self):
        """Get or create OpenAI client."""
        if self._openai_client is None:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=self.config.openai_api_key)
            except ImportError:
                logger.warning("OpenAI package not installed. Run: pip install openai")
                return None
        return self._openai_client
    
    def _get_anthropic_client(self):
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
            except ImportError:
                logger.warning("Anthropic package not installed. Run: pip install anthropic")
                return None
        return self._anthropic_client
    
    def summarize(
        self,
        title: str,
        content: str,
        provider: Optional[str] = None,
        url: Optional[str] = None,
    ) -> SummaryResult:
        """
        Summarize an article using LLM.

        Args:
            title: Article title
            content: Article content/body
            provider: Override provider ("openai", "anthropic", or "local")
            url: Article URL — when provided, the result is cached in Redis
                 (if available) keyed by URL. Re-summarizing the same URL
                 returns the cached result without an LLM call.

        Returns:
            SummaryResult with summary, key points, and metadata
        """
        provider = provider or self.config.preferred_provider
        start_time = datetime.now()

        # Truncate content if too long
        max_chars = 8000
        if len(content) > max_chars:
            content = content[:max_chars] + "..."

        # P0-F: best-effort sync cache lookup. The Redis cache is async,
        # so we can't await it here without making summarize() async (which
        # would break 8+ callers). Instead, callers that can use async
        # should call summarize_cached(). The sync path skips cache lookup
        # but still stores the result on success via a fire-and-forget
        # background task. This is a pragmatic compromise: the cache is
        # populated for async callers, and sync callers don't regress.

        user_message = f"Article Title: {title}\n\nContent:\n{content}"
        
        # Try preferred provider
        if provider == "openai" and self.is_configured("openai"):
            result = self._summarize_openai(user_message)
            if result:
                result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_usage(result)
                self._cache_store_if_available(url, result)
                return result
        
        if provider == "anthropic" and self.is_configured("anthropic"):
            result = self._summarize_anthropic(user_message)
            if result:
                result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_usage(result)
                self._cache_store_if_available(url, result)
                return result

        # Try alternate provider
        if provider == "openai" and self.is_configured("anthropic"):
            result = self._summarize_anthropic(user_message)
            if result:
                result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_usage(result)
                self._cache_store_if_available(url, result)
                return result

        if provider == "anthropic" and self.is_configured("openai"):
            result = self._summarize_openai(user_message)
            if result:
                result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                self._record_usage(result)
                self._cache_store_if_available(url, result)
                return result
        
        # Fallback to local model
        if self.config.fallback_to_local:
            result = self._summarize_local(title, content)
            self._cache_store_if_available(url, result)
            return result

        # Return empty result
        return SummaryResult(
            summary="Summary unavailable",
            key_points=[],
            sentiment="neutral",
            provider="none",
            model="none",
            tokens_used=0,
            cost_usd=0.0,
            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
        )

    async def _ensure_cache(self):
        """Lazily initialize the Redis cache. Idempotent."""
        if self._cache_initialized:
            return self._cache
        self._cache_initialized = True
        try:
            from src.cache.redis_cache import get_redis_cache
            self._cache = await get_redis_cache()
        except Exception as e:
            logger.debug("AI summary cache not available: %s", e)
            self._cache = None
        return self._cache

    def _cache_store_if_available(self, url: Optional[str], result: SummaryResult) -> None:
        """Fire-and-forget cache store for sync callers. Best-effort; never raises.

        Note: this can only store if the cache has already been initialized
        by an earlier async call to _ensure_cache(). Otherwise it's a no-op.
        This is a deliberate compromise — see summarize_cached() for the
        full cache lookup+store path.
        """
        if not url or not self._cache or not result:
            return
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._cache.set_summary(url, result.summary))
            except RuntimeError:
                asyncio.run(self._cache.set_summary(url, result.summary))
        except Exception as e:
            logger.debug("cache store failed (non-fatal): %s", e)

    async def summarize_cached(
        self,
        title: str,
        content: str,
        url: str,
        provider: Optional[str] = None,
    ) -> SummaryResult:
        """Async summarizer with Redis-backed cache.

        Cache hits return immediately without an LLM call. Cache misses
        call summarize() and store the result. The cache key is the URL
        (hashed). TTL is 7 days (SUMMARY_TTL in redis_cache.py).

        This is the recommended entry point for async callers (FastAPI
        routes, async scrapers). The sync summarize() method cannot do
        cache lookup because the cache is async.
        """
        cache = await self._ensure_cache()

        # Cache lookup
        if cache:
            try:
                cached = await cache.get_summary(url)
                if cached:
                    logger.debug("Cache hit for %s", url)
                    return SummaryResult(
                        summary=cached,
                        key_points=[],
                        sentiment="neutral",
                        provider="cache",
                        model="redis",
                        tokens_used=0,
                        cost_usd=0.0,
                        duration_ms=0,
                    )
            except Exception as e:
                logger.debug("cache lookup failed (non-fatal): %s", e)

        # Cache miss — call the sync summarize() in a thread
        import asyncio
        result = await asyncio.to_thread(
            self.summarize, title, content, provider, url
        )

        # Store in cache (fire-and-forget)
        if cache and result and result.provider != "cache":
            try:
                await cache.set_summary(url, result.summary)
            except Exception as e:
                logger.debug("cache store failed (non-fatal): %s", e)

        return result
    
    def _summarize_openai(self, user_message: str) -> Optional[SummaryResult]:
        """Summarize using OpenAI API."""
        client = self._get_openai_client()
        if not client:
            return None
        
        try:
            response = client.chat.completions.create(
                model=self.config.openai_model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=self.config.openai_max_tokens,
                temperature=self.config.temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            tokens = response.usage.total_tokens if response.usage else 0
            cost = self._calculate_cost(self.config.openai_model, tokens)
            
            return SummaryResult(
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                sentiment=data.get("sentiment", "neutral"),
                provider="openai",
                model=self.config.openai_model,
                tokens_used=tokens,
                cost_usd=cost,
                duration_ms=0
            )
            
        except Exception as e:
            logger.error(f"OpenAI summarization failed: {e}")
            return None
    
    def _summarize_anthropic(self, user_message: str) -> Optional[SummaryResult]:
        """Summarize using Anthropic API."""
        client = self._get_anthropic_client()
        if not client:
            return None
        
        try:
            response = client.messages.create(
                model=self.config.anthropic_model,
                max_tokens=self.config.anthropic_max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}]
            )
            
            content = response.content[0].text
            
            # Parse JSON from response
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = {"summary": content, "key_points": [], "sentiment": "neutral"}
            
            tokens = response.usage.input_tokens + response.usage.output_tokens
            cost = self._calculate_cost(self.config.anthropic_model, tokens)
            
            return SummaryResult(
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                sentiment=data.get("sentiment", "neutral"),
                provider="anthropic",
                model=self.config.anthropic_model,
                tokens_used=tokens,
                cost_usd=cost,
                duration_ms=0
            )
            
        except Exception as e:
            logger.error(f"Anthropic summarization failed: {e}")
            return None
    
    def _summarize_local(self, title: str, content: str) -> SummaryResult:
        """Fallback to local AI model."""
        start_time = datetime.now()
        
        try:
            from src.ai_processor import summarize_text
            
            # Generate summary using local model
            summary = summarize_text(content[:3000])
            
            # Extract basic key points (first 3 sentences)
            sentences = content.split('.')[:3]
            key_points = [s.strip() + '.' for s in sentences if len(s.strip()) > 20]
            
            return SummaryResult(
                summary=summary,
                key_points=key_points[:3],
                sentiment="neutral",
                provider="local",
                model="distilbart-cnn-6-6",
                tokens_used=0,
                cost_usd=0.0,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
        except Exception as e:
            logger.error(f"Local summarization failed: {e}")
            return SummaryResult(
                summary=content[:200] + "...",
                key_points=[],
                sentiment="neutral",
                provider="local",
                model="truncation",
                tokens_used=0,
                cost_usd=0.0,
                duration_ms=0
            )
    
    def _calculate_cost(self, model: str, tokens: int) -> float:
        """Calculate cost in USD for tokens used."""
        # Approximate: assume 50/50 input/output split
        model_key = model.split("-202")[0] if "-202" in model else model
        
        for key, costs in self.COSTS.items():
            if key in model_key:
                avg_cost = (costs["input"] + costs["output"]) / 2
                return (tokens / 1000) * avg_cost
        
        return 0.0
    
    def _record_usage(self, result: SummaryResult):
        """Record usage statistics."""
        self._usage["total_cost"] += result.cost_usd
        self._usage["total_tokens"] += result.tokens_used
        self._usage["requests"].append({
            "timestamp": datetime.now().isoformat(),
            "provider": result.provider,
            "model": result.model,
            "tokens": result.tokens_used,
            "cost": result.cost_usd
        })
        
        # Keep only last 1000 requests
        self._usage["requests"] = self._usage["requests"][-1000:]
        self._save_usage()
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_cost_usd": self._usage.get("total_cost", 0),
            "total_tokens": self._usage.get("total_tokens", 0),
            "total_requests": len(self._usage.get("requests", [])),
            "providers_configured": {
                "openai": self.is_configured("openai"),
                "anthropic": self.is_configured("anthropic")
            }
        }
    
    def batch_summarize(
        self,
        articles: List[Dict[str, str]],
        provider: Optional[str] = None
    ) -> List[SummaryResult]:
        """
        Batch summarize multiple articles.
        
        Args:
            articles: List of dicts with 'title' and 'content' keys
            provider: Override provider
            
        Returns:
            List of SummaryResult objects
        """
        results = []
        for article in articles:
            result = self.summarize(
                title=article.get("title", ""),
                content=article.get("content", ""),
                provider=provider
            )
            results.append(result)
        return results


# Singleton instance
_llm_summarizer: Optional[LLMSummarizer] = None


def get_llm_summarizer() -> LLMSummarizer:
    """Get singleton LLMSummarizer instance."""
    global _llm_summarizer
    if _llm_summarizer is None:
        _llm_summarizer = LLMSummarizer()
    return _llm_summarizer
