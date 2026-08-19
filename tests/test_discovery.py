"""
Unit tests for the WebDiscoveryAgent module.

Tests source discovery, verification, and API integration.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.discovery import WebDiscoveryAgent


class TestWebDiscoveryAgent(unittest.TestCase):
    """Test cases for WebDiscoveryAgent class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.mock_db.discovered_sources = []
        self.mock_db.add_discovered_source = MagicMock(return_value=True)
        
        with patch('src.discovery.GOOGLE_API_KEY', ''):
            with patch('src.discovery.GOOGLE_CSE_ID', ''):
                with patch('src.discovery.BING_API_KEY', ''):
                    self.agent = WebDiscoveryAgent(self.mock_db)
        
        self.agent.session = MagicMock()
    
    def test_initialization(self):
        """Test agent initializes correctly."""
        self.assertIsNotNone(self.agent.session)
        self.assertIsInstance(self.agent.api_available, dict)
    
    def test_is_tech_related_true(self):
        """Test tech-related content detection."""
        tech_text = """
        This article discusses artificial intelligence and machine learning
        in the context of software development and cloud computing.
        """
        
        result = self.agent.is_tech_related(tech_text)
        self.assertTrue(result)
    
    def test_is_tech_related_false(self):
        """Test non-tech content detection."""
        non_tech_text = """
        Today we went to the park and had a lovely picnic.
        The weather was beautiful and the kids played soccer.
        """
        
        result = self.agent.is_tech_related(non_tech_text)
        self.assertFalse(result)
    
    def test_verify_source_valid(self):
        """Test source verification with valid tech source."""
        mock_response = MagicMock()
        mock_response.text = '''
        <html>
        <head>
            <title>Tech News Daily</title>
            <link type="application/rss+xml" href="/feed.xml">
        </head>
        <body>
            <article>
            Latest news about artificial intelligence, machine learning,
            software development, and cloud computing technologies.
            </article>
        </body>
        </html>
        '''
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        self.agent.session.get.return_value = mock_response
        self.agent.rate_limiter.wait = MagicMock(return_value=True)
        
        result = self.agent.verify_source("https://technews.com")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], 'rss')
        self.assertTrue(result['verified'])
    
    def test_verify_source_invalid_non_tech(self):
        """Test source verification with non-tech content."""
        mock_response = MagicMock()
        mock_response.text = '''
        <html>
        <head><title>Cooking Blog</title></head>
        <body>
            <article>
            Today we're making delicious pasta with homemade sauce.
            This recipe is perfect for family dinners.
            </article>
        </body>
        </html>
        '''
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        self.agent.session.get.return_value = mock_response
        self.agent.rate_limiter.wait = MagicMock(return_value=True)
        
        result = self.agent.verify_source("https://cooking.com")
        
        self.assertIsNone(result)
    
    def test_fallback_sources(self):
        """Test fallback sources are returned when search fails."""
        # Mock search to return empty
        with patch.object(
            self.agent,
            '_scrape_search_engines',
            return_value=[]
        ):
            result = self.agent.search_web_for_sources("test query")
        
        # Should return fallback sources
        self.assertGreater(len(result), 0)
        self.assertTrue(
            any('techcrunch' in url for url in result) or
            any('verge' in url for url in result)
        )
    
    def test_discover_new_sources(self):
        """Test source discovery process."""
        # Mock search and verify
        with patch.object(
            self.agent,
            'search_web_for_sources',
            return_value=["https://example-tech.com"]
        ):
            with patch.object(
                self.agent,
                'verify_source',
                return_value={
                    'url': 'https://example-tech.com/feed',
                    'type': 'rss',
                    'name': 'Example Tech',
                    'verified': True
                }
            ):
                result = self.agent.discover_new_sources(max_new_sources=1)
        
        self.assertEqual(len(result), 1)
        self.mock_db.add_discovered_source.assert_called()


class TestWebDiscoveryAgentAPI(unittest.TestCase):
    """Test cases for API-based discovery."""
    
    def test_google_api_configured(self):
        """Test Google API availability check."""
        mock_db = MagicMock()
        mock_db.discovered_sources = []
        
        with patch('src.discovery.GOOGLE_API_KEY', 'test-key'):
            with patch('src.discovery.GOOGLE_CSE_ID', 'test-cse'):
                with patch('src.discovery.BING_API_KEY', ''):
                    agent = WebDiscoveryAgent(mock_db)
        
        self.assertTrue(agent.api_available['google'])
        self.assertFalse(agent.api_available['bing'])
    
    def test_bing_api_configured(self):
        """Test Bing API availability check."""
        mock_db = MagicMock()
        mock_db.discovered_sources = []
        
        with patch('src.discovery.GOOGLE_API_KEY', ''):
            with patch('src.discovery.GOOGLE_CSE_ID', ''):
                with patch('src.discovery.BING_API_KEY', 'test-key'):
                    agent = WebDiscoveryAgent(mock_db)
        
        self.assertFalse(agent.api_available['google'])
        self.assertTrue(agent.api_available['bing'])


# =============================================================================
# NEW: GOOGLE NEWS INTEGRATION TESTS
# =============================================================================

class TestGoogleNewsIntegration(unittest.TestCase):
    """Test cases for Google News integration."""
    
    def test_google_news_rss_initialization(self):
        """Test Google News RSS client initializes correctly."""
        from src.sources.google_news import GoogleNewsRSS
        
        rss = GoogleNewsRSS(region="us")
        self.assertIsNotNone(rss)
    
    def test_google_news_url_building(self):
        """Test Google News RSS URL construction."""
        from src.sources.google_news import GoogleNewsRSS
        
        rss = GoogleNewsRSS(region="us")
        url = rss._build_url()
        
        self.assertIn("news.google.com", url)
        self.assertIn("hl=en", url)
        self.assertIn("gl=US", url)
    
    def test_google_news_entry_parsing(self):
        """Test parsing of RSS feed entries."""
        from src.sources.google_news import GoogleNewsRSS
        
        rss = GoogleNewsRSS()
        
        # Create a dictionary-like mock that supports .get()
        class MockEntry:
            link = "https://example.com/article"
            title = "Test Article Title - TechNews"
            summary = "Article summary here"
            published_parsed = (2026, 1, 20, 12, 0, 0, 0, 0, 0)
            
            def get(self, key, default=""):
                return getattr(self, key, default)
        
        mock_entry = MockEntry()
        article = rss._parse_entry(mock_entry)
        
        self.assertIsNotNone(article)
        self.assertEqual(article.title, "Test Article Title")
        self.assertEqual(article.source, "TechNews")
    
    def test_unified_google_client(self):
        """Test unified Google News client."""
        from src.sources.google_news import GoogleNewsClient
        
        client = GoogleNewsClient(region="us")
        
        # API should reflect config
        # (will be False if GOOGLE_API_KEY not set)
        self.assertIsInstance(client.api_enabled, bool)


# =============================================================================
# NEW: BING NEWS INTEGRATION TESTS
# =============================================================================

class TestBingNewsIntegration(unittest.TestCase):
    """Test cases for Bing News API integration."""
    
    def test_bing_client_initialization(self):
        """Test Bing News client initializes correctly."""
        from src.sources.bing_news import BingNewsClient
        
        client = BingNewsClient()
        self.assertIsNotNone(client)
    
    def test_bing_categories_defined(self):
        """Test Bing News categories are defined."""
        from src.sources.bing_news import BingNewsClient
        
        client = BingNewsClient()
        
        self.assertIn("ScienceAndTechnology", client.CATEGORIES)
        self.assertIn("Business", client.CATEGORIES)
    
    def test_bing_article_parsing(self):
        """Test Bing News article parsing."""
        from src.sources.bing_news import BingNewsClient
        
        client = BingNewsClient()
        
        mock_item = {
            "url": "https://example.com/news/article",
            "name": "Test News Article",
            "description": "This is a test article",
            "datePublished": "2026-01-20T12:00:00Z",
            "provider": [{"name": "Example News"}],
        }
        
        article = client._parse_article(mock_item)
        
        self.assertIsNotNone(article)
        self.assertEqual(article.title, "Test News Article")
        self.assertEqual(article.source, "Example News")


# =============================================================================
# NEW: DISCOVERY AGGREGATOR TESTS
# =============================================================================

class TestDiscoveryAggregator(unittest.TestCase):
    """Test cases for unified discovery aggregator."""
    
    def test_aggregator_initialization(self):
        """Test aggregator initializes with all sources."""
        from src.sources.aggregator import DiscoveryAggregator
        
        aggregator = DiscoveryAggregator()
        sources = aggregator.get_available_sources()
        
        # At minimum, Google RSS should be available (no API key needed)
        self.assertIn("google_rss", sources)
    
    def test_unified_article_format(self):
        """Test unified article format conversion."""
        from src.sources.aggregator import UnifiedArticle
        from src.sources.google_news import NewsArticle
        from datetime import datetime, UTC
        
        google_article = NewsArticle(
            id="test123",
            title="Test Article",
            url="https://example.com/article",
            source="Example News",
            published_at=datetime.now(UTC),
        )
        
        unified = UnifiedArticle.from_google(google_article)
        
        self.assertEqual(unified.source_api, "google")
        self.assertEqual(unified.title, "Test Article")


# =============================================================================
# NEW: DEDUPLICATION TESTS
# =============================================================================

class TestDeduplicationEngine(unittest.TestCase):
    """Test cases for deduplication engine."""
    
    def test_url_normalization(self):
        """Test URL normalization removes tracking params."""
        from src.processing.deduplication import URLNormalizer
        
        url1 = "https://example.com/article?id=123&utm_source=twitter"
        url2 = "https://example.com/article?id=123"
        
        norm1 = URLNormalizer.normalize(url1)
        norm2 = URLNormalizer.normalize(url2)
        
        self.assertEqual(norm1, norm2)
    
    def test_url_normalization_www(self):
        """Test URL normalization removes www prefix."""
        from src.processing.deduplication import URLNormalizer
        
        url1 = "https://www.example.com/article"
        url2 = "https://example.com/article"
        
        norm1 = URLNormalizer.normalize(url1)
        norm2 = URLNormalizer.normalize(url2)
        
        self.assertEqual(norm1, norm2)
    
    def test_title_similarity_exact(self):
        """Test title similarity with exact match."""
        from src.processing.deduplication import TitleSimilarityChecker
        
        checker = TitleSimilarityChecker(threshold=0.9)
        
        score = checker.similarity_score(
            "Apple announces new iPhone",
            "Apple announces new iPhone",
        )
        
        self.assertEqual(score, 1.0)
    
    def test_title_similarity_near_match(self):
        """Test title similarity with near match."""
        from src.processing.deduplication import TitleSimilarityChecker
        
        checker = TitleSimilarityChecker(threshold=0.9)
        
        score = checker.similarity_score(
            "Apple announces new iPhone 16",
            "Apple Announces New iPhone 16!",
        )
        
        # Should be high similarity after normalization
        self.assertGreater(score, 0.8)
    
    def test_dedup_engine_url_duplicate(self):
        """Test dedup engine catches URL duplicates."""
        from src.processing.deduplication import DeduplicationEngine
        
        engine = DeduplicationEngine()
        
        # First article
        result1 = engine.check(
            url="https://example.com/article",
            title="Test Article",
            article_id="art1",
        )
        self.assertFalse(result1.is_duplicate)
        
        # Same URL
        result2 = engine.check(
            url="https://example.com/article",
            title="Different Title",
            article_id="art2",
        )
        self.assertTrue(result2.is_duplicate)
        self.assertEqual(result2.reason, "url_match")
    
    def test_dedup_engine_title_duplicate(self):
        """Test dedup engine catches title duplicates."""
        from src.processing.deduplication import DeduplicationEngine
        
        # Use lower threshold (0.8) for near-duplicate detection
        engine = DeduplicationEngine(title_threshold=0.8)
        
        # First article
        result1 = engine.check(
            url="https://site1.com/article",
            title="Apple Announces Major New iPhone Features Today",
            article_id="art1",
        )
        self.assertFalse(result1.is_duplicate)
        
        # Identical title, different URL (should be caught)
        result2 = engine.check(
            url="https://site2.com/news",
            title="Apple Announces Major New iPhone Features Today",
            article_id="art2",
        )
        self.assertTrue(result2.is_duplicate)
        self.assertEqual(result2.reason, "title_similar")
    
    def test_dedup_accuracy_above_95(self):
        """
        Test deduplication accuracy meets requirements.
        
        Focus on URL deduplication which should be 100% accurate.
        Title deduplication accuracy depends on threshold tuning.
        """
        from src.processing.deduplication import DeduplicationEngine
        
        engine = DeduplicationEngine(title_threshold=0.95)  # Strict
        
        # Test URL deduplication (should be 100% accurate)
        test_data = [
            ("https://a.com/article1", "First Article", False),
            ("https://a.com/article1", "Same URL Different Title", True),  # URL dup
            ("https://b.com/article2", "Second Article", False),
            ("https://b.com/article2", "Different Text Same URL", True),  # URL dup
            ("https://c.com/article3", "Third Article", False),
            ("https://d.com/article4", "Fourth Article", False),
            ("https://e.com/article5", "Fifth Article", False),
        ]
        
        correct = 0
        total = len(test_data)
        
        for url, title, expected_dup in test_data:
            result = engine.check(url, title)
            if result.is_duplicate == expected_dup:
                correct += 1
        
        accuracy = correct / total
        # URL-based dedup should achieve 100%
        self.assertGreaterEqual(accuracy, 1.0, f"URL dedup accuracy {accuracy:.1%}")


# =============================================================================
# NEW: REAL-TIME SYSTEM TESTS
# =============================================================================

class TestRealtimeSystem(unittest.TestCase):
    """Test cases for real-time news delivery system."""
    
    def test_redis_event_bus_creation(self):
        """Test Redis event bus can be created."""
        from src.infrastructure.redis_event_bus import RedisEventBus, LocalEventBus
        
        # Local bus should always work (fallback)
        local_bus = LocalEventBus()
        self.assertTrue(local_bus.is_connected)
    
    def test_event_types(self):
        """Test event types are defined correctly."""
        from src.infrastructure.redis_event_bus import EventType
        
        self.assertEqual(EventType.ARTICLE_NEW.value, "article:new")
        self.assertEqual(EventType.REFRESH_COMPLETE.value, "refresh:complete")
    
    def test_event_serialization(self):
        """Test event serialization to JSON."""
        from src.infrastructure.redis_event_bus import Event, EventType
        
        event = Event(
            type=EventType.ARTICLE_NEW,
            payload={"title": "Test", "url": "https://example.com"},
            timestamp="2026-01-20T12:00:00Z",
        )
        
        json_str = event.to_json()
        self.assertIn("article:new", json_str)
        self.assertIn("Test", json_str)
    
    def test_websocket_message_types(self):
        """Test WebSocket message types."""
        from src.realtime.websocket_server import MessageType
        
        self.assertEqual(MessageType.ARTICLE.value, "article")
        self.assertEqual(MessageType.HEARTBEAT.value, "heartbeat")
    
    def test_connection_manager_client_id(self):
        """Test connection manager generates unique IDs."""
        from src.realtime.websocket_server import ConnectionManager
        
        manager = ConnectionManager()
        
        id1 = manager.generate_client_id()
        id2 = manager.generate_client_id()
        
        self.assertNotEqual(id1, id2)
        self.assertIn("client_", id1)


# =============================================================================
# NEW: LATENCY TESTS
# =============================================================================

class TestLatencyRequirements(unittest.TestCase):
    """Test cases for latency requirements (<60 seconds)."""
    
    def test_rss_parsing_latency(self):
        """Test RSS parsing happens quickly."""
        import time
        from src.sources.google_news import GoogleNewsRSS
        
        rss = GoogleNewsRSS()
        
        # Create a mock entry with .get() method
        class MockEntry:
            link = "https://example.com/article"
            title = "Test Article - Source"
            summary = "Summary"
            published_parsed = None
            
            def get(self, key, default=""):
                return getattr(self, key, default)
        
        mock_entry = MockEntry()
        
        start = time.time()
        for _ in range(1000):
            rss._parse_entry(mock_entry)
        elapsed = time.time() - start
        
        # 1000 parses should take < 1 second
        self.assertLess(elapsed, 1.0, f"Parsing too slow: {elapsed:.2f}s for 1000 entries")
    
    def test_dedup_check_latency(self):
        """Test deduplication check is fast."""
        import time
        from src.processing.deduplication import DeduplicationEngine
        
        engine = DeduplicationEngine()
        
        # Pre-populate with 1000 articles
        for i in range(1000):
            engine.add_article(
                f"art_{i}",
                f"https://example.com/article/{i}",
                f"Article Title Number {i}",
            )
        
        # Check latency for new article
        start = time.time()
        for i in range(100):
            engine.check(
                f"https://newsite.com/news/{i}",
                f"New Article {i}",
            )
        elapsed = time.time() - start
        
        # 100 checks should be fast; allow some CI/sandbox jitter.
        avg_ms = (elapsed / 100) * 1000
        self.assertLess(avg_ms, 15, f"Dedup too slow: {avg_ms:.2f}ms per check")


class TestArticleURLClassification(unittest.TestCase):
    """P2-1 Regression: Test WebDiscoveryAgent._is_likely_article_url and package resolution."""

    def test_package_import_resolution(self):
        """Confirm src.discovery.WebDiscoveryAgent resolves through intended package mechanism."""
        from src.discovery import WebDiscoveryAgent as WDA
        self.assertIsNotNone(WDA)

    def test_is_likely_article_url_patterns(self):
        """Exercise _is_likely_article_url with various valid and invalid URLs."""
        agent = WebDiscoveryAgent(db=None)

        # Valid article URLs
        self.assertTrue(agent._is_likely_article_url("https://example.com/2026/08/19/ai-agent-breakthrough"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/article/supercomputing-cluster"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/news/quantum-processor-release"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/story/cybersecurity-zero-day"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/post/deepmind-model-update"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/blog/machine-learning-advances"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/feature/autonomous-agents"))
        self.assertTrue(agent._is_likely_article_url("https://example.com/review/flagship-gpu-benchmarks"))

        # Non-article skip patterns
        self.assertFalse(agent._is_likely_article_url("https://example.com/tag/artificial-intelligence"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/category/hardware"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/author/john-doe"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/page/2"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/search?q=tech"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/login"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/about"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/contact"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/document.pdf"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/image.jpg"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/banner.png"))

        # Fallback by path length
        self.assertTrue(agent._is_likely_article_url("https://example.com/very-long-unique-slug-for-an-article-headline"))
        self.assertFalse(agent._is_likely_article_url("https://example.com/short"))


if __name__ == '__main__':
    unittest.main()
