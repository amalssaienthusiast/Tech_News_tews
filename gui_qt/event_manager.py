"""
Real-Time Event Manager for gui_qt — Qt signal-based bridge between
backend systems and the PyQt6 GUI.

Replaces the Tkinter gui/event_manager.py with native Qt signals and QTimer.
"""

import logging
import queue
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(Enum):
    """Types of events the manager handles."""
    METRICS_UPDATE = auto()
    SYSTEM_ALERT = auto()
    AI_PROCESSING = auto()
    BYPASS_RESULT = auto()
    RESILIENCE_EVENT = auto()
    NEWS_UPDATE = auto()
    CONFIG_CHANGE = auto()
    MODE_SWITCH = auto()
    SERVICE_STATUS = auto()


@dataclass
class GUIEvent:
    """Event payload for GUI updates."""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = 5          # 1 = highest, 10 = lowest
    user_visible: bool = True


# ---------------------------------------------------------------------------
# Event Manager
# ---------------------------------------------------------------------------

class RealTimeEventManager(QObject):
    """
    Thread-safe event manager using a priority queue processed via QTimer.

    Signals
    -------
    event_dispatched(EventType, dict)
        Emitted every time an event is dispatched to subscribers.
    metrics_updated(dict)
        Convenience signal for metric-specific updates.
    system_alert(str, str)
        severity, message
    """

    event_dispatched = pyqtSignal(object, dict)
    metrics_updated = pyqtSignal(dict)
    system_alert = pyqtSignal(str, str)

    def __init__(self, update_interval_ms: int = 100, parent: QObject | None = None):
        super().__init__(parent)
        self._event_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._subscribers: Dict[EventType, List[Callable[[GUIEvent], None]]] = {
            et: [] for et in EventType
        }
        self._running = False
        self._counter = 0
        self._metrics_cache: Dict[str, Any] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(update_interval_ms)
        self._timer.timeout.connect(self._process_events)

        logger.info("RealTimeEventManager initialized (Qt)")

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._timer.start()
        self._connect_to_event_bus()
        logger.info("RealTimeEventManager started")

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        logger.info("RealTimeEventManager stopped")

    # -- pub/sub -------------------------------------------------------------

    def subscribe(self, event_type: EventType, handler: Callable[[GUIEvent], None]) -> None:
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    def publish(self, event_type: EventType, data: Dict[str, Any],
                priority: int = 5, user_visible: bool = True) -> None:
        event = GUIEvent(event_type=event_type, data=data,
                         priority=priority, user_visible=user_visible)
        self._counter += 1
        self._event_queue.put((priority, self._counter, event))

    # -- processing ----------------------------------------------------------

    def _process_events(self) -> None:
        processed = 0
        max_per_cycle = 20
        while not self._event_queue.empty() and processed < max_per_cycle:
            try:
                _, _, event = self._event_queue.get_nowait()
                self._dispatch_event(event)
                processed += 1
            except queue.Empty:
                break
            except Exception as e:  # noqa: BLE001
                logger.error("Error dispatching event: %s", e)

    def _dispatch_event(self, event: GUIEvent) -> None:
        for handler in self._subscribers.get(event.event_type, []):
            try:
                handler(event)
            except Exception as e:  # noqa: BLE001
                logger.error("Handler error: %s", e)

        self.event_dispatched.emit(event.event_type, event.data)

        if event.event_type == EventType.METRICS_UPDATE:
            self._metrics_cache.update(event.data)
            self.metrics_updated.emit(event.data)
        elif event.event_type == EventType.SYSTEM_ALERT:
            severity = event.data.get("severity", "info")
            message = event.data.get("message", "")
            self.system_alert.emit(severity, message)

    # -- core EventBus bridge ------------------------------------------------

    def _connect_to_event_bus(self) -> None:
        try:
            from src.core.events import event_bus
            from src.core.protocol import EventType as CoreEventType

            async def forward_stats(event):
                self.publish(EventType.METRICS_UPDATE, event.data, priority=3)

            async def forward_log(event):
                self.publish(EventType.SYSTEM_ALERT, event.data, priority=5)

            event_bus.subscribe(CoreEventType.STATS_UPDATE, forward_stats)
            event_bus.subscribe(CoreEventType.LOG_MESSAGE, forward_log)
            logger.info("Connected to core EventBus")
        except (ImportError, AttributeError):
            logger.debug("Core EventBus not available — running standalone")
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not connect to EventBus: %s", e)

    # -- utilities -----------------------------------------------------------

    def get_metrics_summary(self) -> Dict[str, Any]:
        return dict(self._metrics_cache)

    def force_refresh(self) -> None:
        self.publish(EventType.METRICS_UPDATE, {"refresh": True}, priority=1)
        self.publish(EventType.RESILIENCE_EVENT, {"refresh": True}, priority=1)

    def clear_queue(self) -> None:
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                break


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_event_manager: Optional[RealTimeEventManager] = None


def get_event_manager(parent: QObject | None = None) -> RealTimeEventManager:
    """Return (or create) the global event manager."""
    global _event_manager
    if _event_manager is None:
        _event_manager = RealTimeEventManager(parent=parent)
    return _event_manager
