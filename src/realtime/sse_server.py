"""
Server-Sent Events (SSE) Server for Real-Time News Delivery.

Provides SSE fallback for browsers that don't support WebSocket.
Uses the same event bus as the WebSocket server.

Endpoint: GET /events/stream

Features:
- Automatic reconnection support
- Event filtering by channel
- Heartbeat keep-alive
- JSON event format
"""

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import AsyncGenerator, Optional, Set

from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


# =============================================================================
# SSE EVENT FORMAT
# =============================================================================

@dataclass
class SSEEvent:
    """Server-Sent Event format."""
    event: str  # Event type (article, heartbeat, error)
    data: dict  # Event payload
    id: Optional[str] = None  # Event ID for resumption
    retry: Optional[int] = None  # Reconnection delay in ms
    
    def format(self) -> str:
        """Format as SSE wire format."""
        lines = []
        
        if self.id:
            lines.append(f"id: {self.id}")
        
        if self.retry:
            lines.append(f"retry: {self.retry}")
        
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")
        
        return "\n".join(lines) + "\n\n"


# =============================================================================
# SSE CONNECTION MANAGER
# =============================================================================

class SSEConnectionManager:
    """Manages SSE client connections."""
    
    def __init__(self):
        self._connections: Set[asyncio.Queue] = set()
        self._event_counter = 0
    
    def add_client(self) -> asyncio.Queue:
        """Add a new client connection."""
        queue = asyncio.Queue(maxsize=100)
        self._connections.add(queue)
        logger.info(f"SSE client connected. Total: {len(self._connections)}")
        return queue
    
    def remove_client(self, queue: asyncio.Queue):
        """Remove a client connection."""
        self._connections.discard(queue)
        logger.info(f"SSE client disconnected. Total: {len(self._connections)}")
    
    async def broadcast(self, event: SSEEvent):
        """Broadcast event to all connected clients."""
        self._event_counter += 1
        event.id = str(self._event_counter)
        
        disconnected = []
        
        for queue in self._connections:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Client too slow, disconnect
                disconnected.append(queue)
        
        for queue in disconnected:
            self._connections.discard(queue)
    
    @property
    def client_count(self) -> int:
        return len(self._connections)


# =============================================================================
# SSE SERVER
# =============================================================================

class SSEServer:
    """
    Server-Sent Events server for real-time news.
    
    Integrates with the same event bus as WebSocket server.
    Provides fallback for browsers without WebSocket support.
    """
    
    def __init__(
        self,
        heartbeat_interval: int = 30,
        reconnect_delay: int = 5000,
    ):
        """
        Initialize SSE server.
        
        Args:
            heartbeat_interval: Seconds between heartbeats
            reconnect_delay: Client reconnection delay in ms
        """
        self._heartbeat_interval = heartbeat_interval
        self._reconnect_delay = reconnect_delay
        self._manager = SSEConnectionManager()
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the SSE server."""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("SSE server started")
    
    async def stop(self):
        """Stop the SSE server."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("SSE server stopped")
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to keep connections alive."""
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            
            event = SSEEvent(
                event="heartbeat",
                data={
                    "timestamp": datetime.now(UTC).isoformat(),
                    "clients": self._manager.client_count,
                },
            )
            await self._manager.broadcast(event)
    
    async def stream(
        self,
        channels: Optional[Set[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream events to a client.
        
        Args:
            channels: Optional set of channels to filter
        
        Yields:
            SSE formatted event strings
        """
        queue = self._manager.add_client()
        
        try:
            # Send initial connection event
            yield SSEEvent(
                event="connected",
                data={
                    "message": "Connected to news stream",
                    "channels": list(channels) if channels else ["all"],
                },
                retry=self._reconnect_delay,
            ).format()
            
            while self._running:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=self._heartbeat_interval + 5,
                    )
                    
                    # Filter by channel if specified
                    if channels and event.event not in channels and event.event not in ("heartbeat", "error"):
                        continue
                    
                    yield event.format()
                    
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                    
        finally:
            self._manager.remove_client(queue)
    
    async def push_article(self, article: dict):
        """Push a new article to all SSE clients."""
        event = SSEEvent(
            event="article",
            data=article,
        )
        await self._manager.broadcast(event)
    
    async def push_event(self, event_type: str, data: dict):
        """Push a custom event to all SSE clients."""
        event = SSEEvent(event=event_type, data=data)
        await self._manager.broadcast(event)
    
    @property
    def client_count(self) -> int:
        return self._manager.client_count


# =============================================================================
# FASTAPI INTEGRATION
# =============================================================================

def create_sse_router(sse_server: SSEServer):
    """
    Create FastAPI router for SSE endpoint.
    
    Usage:
        from fastapi import FastAPI
        from src.realtime.sse_server import SSEServer, create_sse_router
        
        app = FastAPI()
        sse = SSEServer()
        app.include_router(create_sse_router(sse))
    """
    try:
        from fastapi import APIRouter
        from fastapi.responses import StreamingResponse
    except ImportError:
        logger.warning("FastAPI not installed - SSE router unavailable")
        return None
    
    router = APIRouter(prefix="/events", tags=["sse"])
    
    @router.get("/stream")
    async def stream_events():
        """SSE endpoint for news stream."""
        return StreamingResponse(
            sse_server.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
            },
        )
    
    @router.get("/stats")
    async def get_stats():
        """Get SSE server statistics."""
        return {
            "connected_clients": sse_server.client_count,
            "server_running": sse_server._running,
        }
    
    return router


# =============================================================================
# STANDALONE RUNNER
# =============================================================================

async def main():
    """Test SSE server."""
    logging.basicConfig(level=logging.INFO)
    
    server = SSEServer()
    await server.start()
    
    # Simulate pushing events
    for i in range(5):
        await asyncio.sleep(2)
        await server.push_article({
            "id": f"article_{i}",
            "title": f"Test Article {i}",
            "url": f"https://example.com/article/{i}",
        })
        print(f"Pushed article {i}")
    
    await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
