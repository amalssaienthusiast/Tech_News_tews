"""Tests for the AI summary cache wiring (P0-F)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_llm_summarizer_has_cache_attribute():
    """LLMSummarizer has the _cache and _cache_initialized attributes."""
    from src.intelligence.llm_summarizer import LLMSummarizer
    s = LLMSummarizer()
    assert hasattr(s, "_cache")
    assert hasattr(s, "_cache_initialized")
    assert s._cache is None  # not initialized until _ensure_cache() is called
    assert s._cache_initialized is False


def test_llm_summarizer_has_summarize_cached():
    """LLMSummarizer has the async summarize_cached method."""
    from src.intelligence.llm_summarizer import LLMSummarizer
    s = LLMSummarizer()
    assert hasattr(s, "summarize_cached")
    assert asyncio.iscoroutinefunction(s.summarize_cached)


def test_summarize_accepts_url_param():
    """The sync summarize() method accepts an optional url kwarg."""
    import inspect
    from src.intelligence.llm_summarizer import LLMSummarizer
    sig = inspect.signature(LLMSummarizer.summarize)
    assert "url" in sig.parameters
    assert sig.parameters["url"].default is None


def test_ensure_cache_is_idempotent():
    """_ensure_cache() only initializes once."""
    from src.intelligence.llm_summarizer import LLMSummarizer
    s = LLMSummarizer()

    # Mock the get_redis_cache import to return a mock cache
    async def mock_get_redis_cache():
        return MagicMock()

    with patch("src.cache.redis_cache.get_redis_cache", mock_get_redis_cache):
        # First call — initializes
        cache1 = asyncio.run(s._ensure_cache())
        assert s._cache_initialized is True
        assert cache1 is not None

        # Second call — returns the same instance without re-initializing
        cache2 = asyncio.run(s._ensure_cache())
        assert cache2 is cache1


def test_ensure_cache_handles_failure():
    """_ensure_cache() gracefully handles Redis unavailability."""
    from src.intelligence.llm_summarizer import LLMSummarizer
    s = LLMSummarizer()

    async def failing_get_redis_cache():
        raise ConnectionError("Redis not available")

    with patch("src.cache.redis_cache.get_redis_cache", failing_get_redis_cache):
        cache = asyncio.run(s._ensure_cache())
        assert cache is None
        assert s._cache is None  # degraded gracefully


def test_summarize_cached_returns_cache_hit():
    """summarize_cached() returns cached result without LLM call."""
    from src.intelligence.llm_summarizer import LLMSummarizer, SummaryResult
    s = LLMSummarizer()

    # Pre-populate the cache
    mock_cache = MagicMock()
    mock_cache.get_summary = AsyncMock(return_value="Cached summary text")
    s._cache = mock_cache
    s._cache_initialized = True

    result = asyncio.run(s.summarize_cached(
        title="Test",
        content="content",
        url="https://example.com/test",
    ))
    assert result.provider == "cache"
    assert result.summary == "Cached summary text"
    assert result.duration_ms == 0
    assert result.cost_usd == 0.0
    # The cache lookup was called
    mock_cache.get_summary.assert_called_once_with("https://example.com/test")


def test_summarize_cached_falls_back_when_cache_miss():
    """summarize_cached() calls summarize() on cache miss."""
    from src.intelligence.llm_summarizer import LLMSummarizer, SummaryResult
    s = LLMSummarizer()

    # Cache returns None (miss)
    mock_cache = MagicMock()
    mock_cache.get_summary = AsyncMock(return_value=None)
    mock_cache.set_summary = AsyncMock(return_value=True)
    s._cache = mock_cache
    s._cache_initialized = True

    # Mock the sync summarize() to return a fake result
    fake_result = SummaryResult(
        summary="LLM summary",
        key_points=["point"],
        sentiment="neutral",
        provider="openai",
        model="gpt-4o-mini",
        tokens_used=100,
        cost_usd=0.001,
        duration_ms=500,
    )
    s.summarize = MagicMock(return_value=fake_result)

    result = asyncio.run(s.summarize_cached(
        title="Test",
        content="content",
        url="https://example.com/test",
    ))
    assert result.provider == "openai"
    assert result.summary == "LLM summary"
    # Cache store was attempted
    mock_cache.set_summary.assert_called_once_with(
        "https://example.com/test", "LLM summary"
    )


def test_cache_store_if_available_is_safe_noop():
    """_cache_store_if_available is a safe no-op when cache is None."""
    from src.intelligence.llm_summarizer import LLMSummarizer, SummaryResult
    s = LLMSummarizer()
    s._cache = None  # no cache
    result = SummaryResult(
        summary="test", key_points=[], sentiment="neutral",
        provider="openai", model="gpt-4o-mini",
        tokens_used=10, cost_usd=0.001, duration_ms=10,
    )
    # Should not raise
    s._cache_store_if_available("https://example.com", result)
    s._cache_store_if_available(None, result)  # no URL
    s._cache_store_if_available("https://example.com", None)  # no result


if __name__ == "__main__":
    test_llm_summarizer_has_cache_attribute()
    test_llm_summarizer_has_summarize_cached()
    test_summarize_accepts_url_param()
    test_ensure_cache_is_idempotent()
    test_ensure_cache_handles_failure()
    test_summarize_cached_returns_cache_hit()
    test_summarize_cached_falls_back_when_cache_miss()
    test_cache_store_if_available_is_safe_noop()
    print("All AI summary cache wiring tests passed.")
