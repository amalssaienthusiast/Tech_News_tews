"""
Real-time delivery module for news streaming.

Provides:
- WebSocket server for push-based delivery
- Server-Sent Events (SSE) fallback
- Connection management with heartbeat
- Redis pub/sub integration
"""

from src.realtime.websocket_server import (
    WebSocketServer,
    ConnectionManager,
    start_websocket_server,
)

# SSE fallback
try:
    from src.realtime.sse_server import (
        SSEServer,
        SSEConnectionManager,
        SSEEvent,
        create_sse_router,
    )
    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False

__all__ = [
    "WebSocketServer",
    "ConnectionManager",
    "start_websocket_server",
    # SSE
    "SSEServer",
    "SSEConnectionManager",
    "SSEEvent",
    "create_sse_router",
    "SSE_AVAILABLE",
]
