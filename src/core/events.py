"""
Async Event Bus Infrastructure.

Provides a robust publish-subscribe mechanism for system-wide events,
enabling decoupled, real-time communication between components.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Type, TypeVar

from src.core.protocol import SystemEvent, EventType

logger = logging.getLogger(__name__)

# Type for event handlers
T = TypeVar('T', bound=SystemEvent)
EventHandler = Callable[[T], Awaitable[None]]


class EventBus:
    """
    Asynchronous Event Bus for real-time system communication.
    
    Implements a robust Pub/Sub pattern allowing components to react
    to system events without tight coupling.
    """
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
            cls._instance._subscribers = defaultdict(list)
            cls._instance._running = False
            cls._instance._queue = None
            cls._instance._worker_task = None
        return cls._instance
    
    def __init__(self):
        # Already initialized in __new__ (singleton pattern)
        pass
    
    async def start(self):
        """Start the event processing worker."""
        if self._running:
            return
            
        self._running = True
        if self._queue is None:
            self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._process_events())
        logger.info("EventBus started")

    
    async def stop(self):
        """Stop the event processing worker."""
        self._running = False
        if self._worker_task:
            await self._queue.put(None)  # Sentinel
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("EventBus stopped")
    
    def subscribe(self, event_type: EventType, handler: EventHandler):
        """
        Subscribe a handler to a specific event type.
        
        Args:
            event_type: EventType to listen for
            handler: Async function to call when event occurs
        """
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type.name}")
    
    def publish(self, event: SystemEvent):
        """
        Publish an event to the bus.
        
        This is non-blocking (fire and forget).
        """
        if not self._running or self._queue is None:
            return
            
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error(f"EventBus queue full, dropped {event.event_type.name}")
    
    async def _process_events(self):
        """Background worker to process events from queue."""
        while self._running:
            try:
                event = await self._queue.get()
                
                if event is None:  # Sentinel
                    break
                
                # Get handlers for this event type
                handlers = self._subscribers.get(event.event_type, [])
                
                # Execute handlers concurrently
                if handlers:
                    # Create tasks for all handlers
                    tasks = [self._safe_execute(h, event) for h in handlers]
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                self._queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in EventBus worker: {e}", exc_info=True)
    
    async def _safe_execute(self, handler: EventHandler, event: SystemEvent):
        """Execute a handler with error protection."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in event handler {handler.__name__}: {e}")

# Global instance
event_bus = EventBus()
