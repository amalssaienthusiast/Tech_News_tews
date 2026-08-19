"""
WebSocket Server for Real-Time News Delivery.

Provides push-based delivery of news articles to connected clients:
- WebSocket connections with heartbeat
- Connection management (subscribe/unsubscribe)
- Redis pub/sub integration for event distribution
- Message batching for efficiency
- Auto-reconnection support

Usage:
    # Start standalone server
    python -m src.realtime.websocket_server
    
    # Or integrate with existing FastAPI app
    from src.realtime.websocket_server import WebSocketServer
    server = WebSocketServer()
    await server.start()
"""

import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import settings
try:
    from config.settings import (
        WEBSOCKET_HOST,
        WEBSOCKET_PORT,
        WEBSOCKET_HEARTBEAT_INTERVAL,
        WEBSOCKET_MAX_CONNECTIONS,
        WEBSOCKET_MESSAGE_QUEUE_SIZE,
    )
except ImportError:
    WEBSOCKET_HOST = "0.0.0.0"
    WEBSOCKET_PORT = 8765
    WEBSOCKET_HEARTBEAT_INTERVAL = 30
    WEBSOCKET_MAX_CONNECTIONS = 1000
    WEBSOCKET_MESSAGE_QUEUE_SIZE = 100


# =============================================================================
# MESSAGE TYPES
# =============================================================================

class MessageType(str, Enum):
    """WebSocket message types."""
    HELLO = "hello"              # Server greeting
    HEARTBEAT = "heartbeat"      # Keep-alive ping/pong
    SUBSCRIBE = "subscribe"      # Client subscription request
    UNSUBSCRIBE = "unsubscribe"  # Client unsubscription
    ARTICLE = "article"          # New article notification
    BATCH = "batch"              # Batch of articles
    ERROR = "error"              # Error message
    STATS = "stats"              # Statistics update


@dataclass
class WebSocketMessage:
    """Structured WebSocket message."""
    type: MessageType
    data: Any
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        })
    
    @classmethod
    def from_json(cls, raw: str) -> "WebSocketMessage":
        d = json.loads(raw)
        return cls(
            type=MessageType(d.get("type", "error")),
            data=d.get("data"),
            timestamp=d.get("timestamp", ""),
        )


# =============================================================================
# CONNECTION MANAGER
# =============================================================================

@dataclass
class ClientConnection:
    """Represents a connected WebSocket client."""
    id: str
    websocket: Any  # websockets.WebSocketServerProtocol
    connected_at: datetime
    last_heartbeat: datetime
    subscriptions: Set[str] = field(default_factory=set)
    message_count: int = 0
    
    @property
    def is_alive(self) -> bool:
        """Check if connection is still active based on heartbeat."""
        elapsed = (datetime.now(UTC) - self.last_heartbeat).total_seconds()
        return elapsed < WEBSOCKET_HEARTBEAT_INTERVAL * 3


class ConnectionManager:
    """
    Manages WebSocket client connections.
    
    Features:
    - Connection tracking with unique IDs
    - Subscription management (topics/channels)
    - Heartbeat monitoring
    - Broadcast to all or filtered clients
    - Graceful disconnect handling
    """
    
    def __init__(self, max_connections: int = WEBSOCKET_MAX_CONNECTIONS):
        """
        Initialize connection manager.
        
        Args:
            max_connections: Maximum allowed concurrent connections
        """
        self._max_connections = max_connections
        self._connections: Dict[str, ClientConnection] = {}
        self._subscription_index: Dict[str, Set[str]] = {}  # channel -> client_ids
        self._client_counter = 0
        
        # Statistics
        self._stats = {
            "total_connections": 0,
            "peak_connections": 0,
            "messages_sent": 0,
            "messages_received": 0,
        }
    
    def generate_client_id(self) -> str:
        """Generate unique client ID."""
        self._client_counter += 1
        return f"client_{self._client_counter}_{int(time.time())}"
    
    async def connect(self, websocket: Any) -> Optional[str]:
        """
        Register a new client connection.
        
        Args:
            websocket: WebSocket connection object
        
        Returns:
            Client ID if accepted, None if rejected (max connections)
        """
        if len(self._connections) >= self._max_connections:
            logger.warning("Max connections reached, rejecting new client")
            return None
        
        client_id = self.generate_client_id()
        now = datetime.now(UTC)
        
        connection = ClientConnection(
            id=client_id,
            websocket=websocket,
            connected_at=now,
            last_heartbeat=now,
        )
        
        self._connections[client_id] = connection
        self._stats["total_connections"] += 1
        self._stats["peak_connections"] = max(
            self._stats["peak_connections"],
            len(self._connections),
        )
        
        logger.info(f"Client connected: {client_id} (total: {len(self._connections)})")
        
        # Send hello message
        await self.send_to_client(
            client_id,
            WebSocketMessage(
                type=MessageType.HELLO,
                data={"client_id": client_id, "server_time": now.isoformat()},
            ),
        )
        
        return client_id
    
    async def disconnect(self, client_id: str) -> None:
        """
        Remove a client connection.
        
        Args:
            client_id: Client to disconnect
        """
        if client_id not in self._connections:
            return
        
        connection = self._connections[client_id]
        
        # Remove from subscription index
        for channel in connection.subscriptions:
            if channel in self._subscription_index:
                self._subscription_index[channel].discard(client_id)
        
        del self._connections[client_id]
        logger.info(f"Client disconnected: {client_id} (remaining: {len(self._connections)})")
    
    def subscribe(self, client_id: str, channel: str) -> bool:
        """
        Subscribe client to a channel.
        
        Args:
            client_id: Client to subscribe
            channel: Channel name (e.g., 'news:all', 'news:technology')
        
        Returns:
            True if subscribed successfully
        """
        if client_id not in self._connections:
            return False
        
        self._connections[client_id].subscriptions.add(channel)
        
        if channel not in self._subscription_index:
            self._subscription_index[channel] = set()
        self._subscription_index[channel].add(client_id)
        
        logger.debug(f"Client {client_id} subscribed to {channel}")
        return True
    
    def unsubscribe(self, client_id: str, channel: str) -> bool:
        """Unsubscribe client from a channel."""
        if client_id not in self._connections:
            return False
        
        self._connections[client_id].subscriptions.discard(channel)
        
        if channel in self._subscription_index:
            self._subscription_index[channel].discard(client_id)
        
        return True
    
    def update_heartbeat(self, client_id: str) -> None:
        """Update last heartbeat time for client."""
        if client_id in self._connections:
            self._connections[client_id].last_heartbeat = datetime.now(UTC)
    
    async def send_to_client(
        self,
        client_id: str,
        message: WebSocketMessage,
    ) -> bool:
        """
        Send message to specific client.
        
        Args:
            client_id: Target client
            message: Message to send
        
        Returns:
            True if sent successfully
        """
        if client_id not in self._connections:
            return False
        
        try:
            connection = self._connections[client_id]
            await connection.websocket.send(message.to_json())
            connection.message_count += 1
            self._stats["messages_sent"] += 1
            return True
        except Exception as e:
            logger.warning(f"Failed to send to {client_id}: {e}")
            return False
    
    async def broadcast(
        self,
        message: WebSocketMessage,
        channel: str = None,
    ) -> int:
        """
        Broadcast message to all clients or channel subscribers.
        
        Args:
            message: Message to broadcast
            channel: Optional channel to filter recipients
        
        Returns:
            Number of clients that received the message
        """
        if channel:
            client_ids = self._subscription_index.get(channel, set())
        else:
            client_ids = set(self._connections.keys())
        
        sent_count = 0
        failed_clients = []
        
        for client_id in client_ids:
            if await self.send_to_client(client_id, message):
                sent_count += 1
            else:
                failed_clients.append(client_id)
        
        # Clean up failed connections
        for client_id in failed_clients:
            await self.disconnect(client_id)
        
        return sent_count
    
    async def broadcast_article(
        self,
        article: Dict[str, Any],
        channels: List[str] = None,
    ) -> int:
        """
        Broadcast new article to relevant subscribers.
        
        Args:
            article: Article data dictionary
            channels: Channels to broadcast to
        
        Returns:
            Number of clients notified
        """
        message = WebSocketMessage(
            type=MessageType.ARTICLE,
            data=article,
        )
        
        if not channels:
            channels = ["news:all"]
        
        total_sent = 0
        for channel in channels:
            total_sent += await self.broadcast(message, channel)
        
        return total_sent
    
    async def cleanup_stale_connections(self) -> int:
        """
        Remove connections that haven't sent heartbeat.
        
        Returns:
            Number of connections removed
        """
        stale_clients = [
            client_id
            for client_id, conn in self._connections.items()
            if not conn.is_alive
        ]
        
        for client_id in stale_clients:
            await self.disconnect(client_id)
        
        if stale_clients:
            logger.info(f"Cleaned up {len(stale_clients)} stale connections")
        
        return len(stale_clients)
    
    @property
    def connection_count(self) -> int:
        """Get current number of connections."""
        return len(self._connections)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            **self._stats,
            "current_connections": len(self._connections),
            "channels": list(self._subscription_index.keys()),
        }


# =============================================================================
# WEBSOCKET SERVER
# =============================================================================

class WebSocketServer:
    """
    WebSocket server for real-time news delivery.
    
    Integrates with:
    - Redis event bus for receiving new articles
    - Connection manager for client handling
    - RealtimeNewsFeeder for article callbacks
    
    Example:
        server = WebSocketServer()
        await server.start()
        
        # Broadcast article when discovered
        await server.broadcast_article(article_data)
    """
    
    def __init__(
        self,
        host: str = WEBSOCKET_HOST,
        port: int = WEBSOCKET_PORT,
        heartbeat_interval: int = WEBSOCKET_HEARTBEAT_INTERVAL,
    ):
        """
        Initialize WebSocket server.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            heartbeat_interval: Seconds between heartbeat checks
        """
        self._host = host
        self._port = port
        self._heartbeat_interval = heartbeat_interval
        
        self._connection_manager = ConnectionManager()
        self._server = None
        self._running = False
        
        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._redis_task: Optional[asyncio.Task] = None
        
        # Redis event bus (optional)
        self._event_bus = None
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def connection_count(self) -> int:
        return self._connection_manager.connection_count
    
    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._running:
            return
        
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Install with: pip install websockets")
            return
        
        self._running = True
        
        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Try to connect to Redis event bus
        await self._connect_redis()
        
        # Start WebSocket server
        self._server = await websockets.serve(
            self._handle_client,
            self._host,
            self._port,
        )
        
        logger.info(f"WebSocket server started on ws://{self._host}:{self._port}")
    
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        
        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        
        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        # Disconnect event bus
        if self._event_bus:
            await self._event_bus.disconnect()
        
        logger.info("WebSocket server stopped")
    
    async def _handle_client(self, websocket, path: str = "") -> None:
        """
        Handle individual WebSocket client connection.
        
        Args:
            websocket: WebSocket connection
            path: Request path (can be used for routing)
        """
        client_id = await self._connection_manager.connect(websocket)
        
        if not client_id:
            await websocket.close(1013, "Max connections reached")
            return
        
        # Default subscription
        self._connection_manager.subscribe(client_id, "news:all")
        
        try:
            async for raw_message in websocket:
                await self._handle_message(client_id, raw_message)
                
        except Exception as e:
            logger.debug(f"Client {client_id} error: {e}")
        finally:
            await self._connection_manager.disconnect(client_id)
    
    async def _handle_message(self, client_id: str, raw_message: str) -> None:
        """
        Handle incoming message from client.
        
        Args:
            client_id: Sender client ID
            raw_message: Raw JSON message string
        """
        try:
            message = WebSocketMessage.from_json(raw_message)
            self._connection_manager._stats["messages_received"] += 1
            
            if message.type == MessageType.HEARTBEAT:
                # Update heartbeat and respond
                self._connection_manager.update_heartbeat(client_id)
                await self._connection_manager.send_to_client(
                    client_id,
                    WebSocketMessage(type=MessageType.HEARTBEAT, data="pong"),
                )
            
            elif message.type == MessageType.SUBSCRIBE:
                # Subscribe to channel
                channel = message.data.get("channel", "news:all")
                self._connection_manager.subscribe(client_id, channel)
            
            elif message.type == MessageType.UNSUBSCRIBE:
                # Unsubscribe from channel
                channel = message.data.get("channel")
                if channel:
                    self._connection_manager.unsubscribe(client_id, channel)
            
            elif message.type == MessageType.STATS:
                # Send server stats
                stats = self.get_stats()
                await self._connection_manager.send_to_client(
                    client_id,
                    WebSocketMessage(type=MessageType.STATS, data=stats),
                )
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from {client_id}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")
    
    async def _heartbeat_loop(self) -> None:
        """Background task for heartbeat and cleanup."""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                
                # Clean up stale connections
                await self._connection_manager.cleanup_stale_connections()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
    
    async def _connect_redis(self) -> None:
        """Connect to Redis event bus for article notifications."""
        try:
            from src.infrastructure.redis_event_bus import create_event_bus
            
            self._event_bus = await create_event_bus(fallback_to_local=True)
            
            if self._event_bus.is_connected:
                # Start listening for articles
                self._redis_task = asyncio.create_task(self._redis_listener())
                logger.info("Connected to Redis event bus")
            else:
                logger.info("Using local event bus (Redis unavailable)")
                
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
    
    async def _redis_listener(self) -> None:
        """Listen for articles from Redis and broadcast to clients."""
        try:
            async for message in self._event_bus.subscribe("news:all", use_patterns=False):
                await self.broadcast_article(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis listener error: {e}")
    
    async def broadcast_article(
        self,
        article: Dict[str, Any],
        channels: List[str] = None,
    ) -> int:
        """
        Broadcast article to connected clients.
        
        Args:
            article: Article data
            channels: Channels to broadcast to
        
        Returns:
            Number of clients notified
        """
        return await self._connection_manager.broadcast_article(article, channels)
    
    async def broadcast(
        self,
        message: WebSocketMessage,
        channel: str = None,
    ) -> int:
        """
        Broadcast message to connected clients.
        
        Args:
            message: Message to broadcast
            channel: Optional channel filter
        
        Returns:
            Number of clients that received the message
        """
        return await self._connection_manager.broadcast(message, channel)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        return {
            "running": self._running,
            "host": self._host,
            "port": self._port,
            "redis_connected": self._event_bus.is_connected if self._event_bus else False,
            **self._connection_manager.get_stats(),
        }


# =============================================================================
# STANDALONE SERVER RUNNER
# =============================================================================

async def start_websocket_server(
    host: str = WEBSOCKET_HOST,
    port: int = WEBSOCKET_PORT,
) -> WebSocketServer:
    """
    Start WebSocket server (convenience function).
    
    Args:
        host: Host to bind to
        port: Port to listen on
    
    Returns:
        Running WebSocketServer instance
    """
    server = WebSocketServer(host=host, port=port)
    await server.start()
    return server


async def main():
    """Run standalone WebSocket server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    server = await start_websocket_server()
    
    try:
        # Keep server running
        while server.is_running:
            await asyncio.sleep(10)
            stats = server.get_stats()
            logger.info(f"Connections: {stats['current_connections']}, Messages sent: {stats['messages_sent']}")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
