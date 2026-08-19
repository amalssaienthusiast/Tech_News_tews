"""
Structured JSON Logging Configuration for Tech News Scraper.

Provides:
- JSON-formatted log output for log aggregation (Loki, ELK)
- Correlation IDs for request tracing
- Per-module log level configuration
- Integration with existing logging

Usage:
    from src.monitoring import get_structured_logger
    
    logger = get_structured_logger(__name__)
    
    # Basic logging
    logger.info("Article scraped", url="https://...", duration_ms=150)
    
    # With correlation ID
    with logger.correlation_context("req-abc123"):
        logger.info("Processing request")
"""

import json
import logging
import sys
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, UTC
from typing import Any, Dict, Optional

# Context variable for correlation ID
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


# =============================================================================
# JSON FORMATTER
# =============================================================================

class JSONFormatter(logging.Formatter):
    """
    Format log records as JSON for structured logging.
    
    Output format:
    {
        "timestamp": "2026-01-22T10:30:00Z",
        "level": "INFO",
        "module": "scraper.bypass",
        "correlation_id": "req-abc123",
        "message": "Successfully bypassed Cloudflare",
        "metrics": {"duration_ms": 2450, "technique": "stealth"}
    }
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        
        # Add correlation ID if set
        correlation_id = _correlation_id.get()
        if correlation_id:
            log_data["correlation_id"] = correlation_id
        
        # Add extra fields as metrics
        metrics = {}
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "taskName", "message"
            ) and not key.startswith("_"):
                metrics[key] = value
        
        if metrics:
            log_data["metrics"] = metrics
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


# =============================================================================
# STRUCTURED LOGGER
# =============================================================================

class StructuredLogger:
    """
    Logger wrapper that provides structured logging with metrics.
    
    Adds convenience methods for logging with additional context.
    """
    
    def __init__(self, name: str, level: int = logging.INFO):
        self._logger = logging.getLogger(name)
        self._name = name
        self._level = level
    
    def _log(self, level: int, message: str, **kwargs):
        """Internal log method that adds extra fields."""
        # Create a new LogRecord with extra fields
        extra = {k: v for k, v in kwargs.items()}
        self._logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        """Log at DEBUG level."""
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log at INFO level."""
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log at WARNING level."""
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log at ERROR level."""
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log at CRITICAL level."""
        self._log(logging.CRITICAL, message, **kwargs)
    
    def exception(self, message: str, **kwargs):
        """Log exception with traceback."""
        self._logger.exception(message, extra=kwargs)
    
    class CorrelationContext:
        """Context manager for setting correlation ID."""
        
        def __init__(self, correlation_id: str):
            self._correlation_id = correlation_id
            self._token = None
        
        def __enter__(self):
            self._token = _correlation_id.set(self._correlation_id)
            return self
        
        def __exit__(self, *args):
            _correlation_id.reset(self._token)
    
    def correlation_context(self, correlation_id: str = None):
        """Create a context with correlation ID."""
        if correlation_id is None:
            correlation_id = f"req-{uuid.uuid4().hex[:12]}"
        return self.CorrelationContext(correlation_id)
    
    @staticmethod
    def get_correlation_id() -> Optional[str]:
        """Get current correlation ID."""
        return _correlation_id.get()
    
    @staticmethod
    def set_correlation_id(correlation_id: str):
        """Set correlation ID."""
        _correlation_id.set(correlation_id)


# =============================================================================
# CONFIGURATION
# =============================================================================

class LoggingConfiguration:
    """
    Configure logging for the application.
    
    Supports:
    - JSON or text format output
    - Per-module log levels
    - File and console handlers
    """
    
    DEFAULT_LEVELS = {
        "src.pipeline": "INFO",
        "src.zombies": "INFO",
        "src.bypass": "INFO",
        "src.engine": "INFO",
        "src.api": "INFO",
        "src.intelligence": "INFO",
        "src.monitoring": "DEBUG",
        "aiohttp": "WARNING",
        "urllib3": "WARNING",
    }
    
    @classmethod
    def configure(
        cls,
        json_format: bool = True,
        level: int = logging.INFO,
        module_levels: Dict[str, str] = None,
        log_file: str = None,
    ):
        """
        Configure logging with structured format.
        
        Args:
            json_format: Use JSON format (True) or text format (False)
            level: Default log level
            module_levels: Per-module log level overrides
            log_file: Optional file path for log output
        """
        # Set root logger level
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Create formatter
        if json_format:
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # File handler (optional)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        
        # Apply per-module levels
        levels = {**cls.DEFAULT_LEVELS, **(module_levels or {})}
        for module, level_str in levels.items():
            log_level = getattr(logging, level_str.upper(), logging.INFO)
            logging.getLogger(module).setLevel(log_level)
        
        logging.getLogger(__name__).info(
            "Logging configured",
            extra={"json_format": json_format, "log_file": log_file}
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_loggers: Dict[str, StructuredLogger] = {}
_lock = threading.Lock()


def get_structured_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger for a module."""
    with _lock:
        if name not in _loggers:
            _loggers[name] = StructuredLogger(name)
        return _loggers[name]


def configure_logging(
    json_format: bool = False,  # Default to text for dev, enable JSON in prod
    level: int = logging.INFO,
    module_levels: Dict[str, str] = None,
    log_file: str = None,
):
    """Configure application logging."""
    LoggingConfiguration.configure(
        json_format=json_format,
        level=level,
        module_levels=module_levels,
        log_file=log_file,
    )


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str):
    """Set current correlation ID."""
    _correlation_id.set(correlation_id)
