"""
Unit tests for RealTimeLogHandler and EventBus integration.

These tests validate:
1. RealTimeLogHandler correctly publishes LogMessage events
2. EventBus.publish() receives correctly formatted events
3. Callback type signatures are enforced
"""

import logging
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.protocol import LogMessage, EventType
from src.core.events import EventBus


class MockEventBus:
    """Mock EventBus for testing publish calls."""
    
    def __init__(self):
        self.published_events = []
        self._running = True
    
    def publish(self, event):
        """Capture published events for assertion."""
        self.published_events = self.published_events or []
        self.published_events.append(event)
    
    def get_last_event(self):
        return self.published_events[-1] if self.published_events else None
    
    def clear(self):
        self.published_events = []


class TestLogMessage(unittest.TestCase):
    """Tests for LogMessage dataclass."""
    
    def test_log_message_has_correct_fields(self):
        """Verify LogMessage uses 'component' not 'source'."""
        msg = LogMessage(
            level="INFO",
            message="Test message",
            component="TestComponent"
        )
        self.assertEqual(msg.component, "TestComponent")
        self.assertEqual(msg.level, "INFO")
        self.assertEqual(msg.message, "Test message")
        self.assertEqual(msg.event_type, EventType.LOG_MESSAGE)
    
    def test_log_message_rejects_source_kwarg(self):
        """Ensure 'source' keyword raises TypeError (security test)."""
        with self.assertRaises(TypeError):
            LogMessage(
                level="INFO",
                message="Test",
                source="BadField"  # This should fail
            )


class TestRealTimeLogHandler(unittest.TestCase):
    """Tests for QtLogHandler in gui_qt/widgets/live_activity_log.py."""

    def test_handler_delivers_record_to_widget(self):
        """Verify QtLogHandler formats and delivers record to target widget."""
        from gui_qt.widgets.live_activity_log import QtLogHandler

        mock_widget = MagicMock()
        handler = QtLogHandler(widget=mock_widget)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test log message",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        mock_widget.info.assert_called_once_with("Test log message", "test.logger")


class TestEventBusPublish(unittest.TestCase):
    """Tests for EventBus.publish() signature."""

    def test_publish_accepts_single_event(self):
        """Verify publish() takes only 1 positional argument."""
        bus = EventBus()
        msg = LogMessage(level="INFO", message="Test", component="Test")

        # This should work (1 argument)
        try:
            bus.publish(msg)
        except TypeError:
            self.fail("publish() should accept a single event argument")

    def test_publish_rejects_two_arguments(self):
        """Verify publish() rejects 2 positional arguments."""
        bus = EventBus()
        msg = LogMessage(level="INFO", message="Test", component="Test")

        # This should fail (2 arguments)
        with self.assertRaises(TypeError):
            bus.publish(EventType.LOG_MESSAGE, msg)


class TestCallbackTypeHints(unittest.TestCase):
    """Tests for callback type hints in orchestrator."""

    def test_article_callback_signature(self):
        """Verify new article callback accepts Article type."""
        from src.core.types import Article
        from src.engine.orchestrator import TechNewsOrchestrator

        orchestrator = TechNewsOrchestrator()

        received_articles = []

        def callback(article: Article) -> None:
            received_articles.append(article)

        # Register callback - should not raise
        orchestrator.register_new_article_callback(callback)
        self.assertEqual(orchestrator._new_article_callback, callback)


if __name__ == '__main__':
    unittest.main()
