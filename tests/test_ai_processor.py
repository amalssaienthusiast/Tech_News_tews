"""
Unit tests for the AI Processor module.

Tests AI model initialization, summarization, and semantic search.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestAIProcessor(unittest.TestCase):
    """Test cases for AI processing functions."""
    
    def test_summarize_short_text(self):
        """Test summarization with short text returns placeholder."""
        from src.ai_processor import summarize_text
        
        result = summarize_text("Short text.")
        
        # When model not initialized, returns disabled message
        self.assertTrue(
            "too short" in result.lower() or "disabled" in result.lower()
        )
    
    def test_summarize_empty_text(self):
        """Test summarization with empty text."""
        from src.ai_processor import summarize_text
        
        result = summarize_text("")
        
        # When model not initialized, returns disabled message
        self.assertTrue(
            "no content" in result.lower() or "disabled" in result.lower()
        )
    
    def test_is_initialized_before_init(self):
        """Test initialization check."""
        # Reset global state
        import src.ai_processor as ai
        ai._models_initialized = False
        ai._summarizer = None
        ai._search_model = None
        
        self.assertFalse(ai.is_initialized())
    
    def test_get_device(self):
        """Test device retrieval."""
        from src.ai_processor import get_device
        
        device = get_device()
        
        self.assertIn(device, ['cpu', 'cuda'])


class TestAIProcessorWithMocks(unittest.TestCase):
    """Test cases with mocked AI models."""
    
    def setUp(self):
        """Set up mocked AI models."""
        import src.ai_processor as ai
        
        # Mock summarizer
        self.mock_summarizer = MagicMock()
        self.mock_summarizer.return_value = [{"summary_text": "Mock summary"}]
        
        ai._summarizer = self.mock_summarizer
        ai._models_initialized = True
    
    def tearDown(self):
        """Reset AI processor state."""
        import src.ai_processor as ai
        ai._summarizer = None
        ai._search_model = None
        ai._models_initialized = False
    
    def test_summarize_with_mock(self):
        """Test summarization with mocked model."""
        from src.ai_processor import summarize_text
        
        long_text = "This is a test article. " * 50  # Make it long enough
        
        result = summarize_text(long_text)
        
        self.assertEqual(result, "Mock summary")
        self.mock_summarizer.assert_called_once()


class TestSemanticSearch(unittest.TestCase):
    """Test cases for semantic search functionality."""
    
    def test_search_without_model(self):
        """Test search returns empty when model unavailable."""
        import src.ai_processor as ai
        ai._search_model = None
        ai._models_initialized = False
        
        from src.ai_processor import semantic_search
        
        result = semantic_search("test query", None, [])
        
        self.assertEqual(result, [])
    
    def test_search_empty_articles(self):
        """Test search with empty article list."""
        from src.ai_processor import semantic_search
        
        result = semantic_search("test query", None, [])
        
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
