"""
Async Bridge - QThread integration for asyncio operations.

Provides a clean bridge between Qt's event loop and Python asyncio,
allowing async operations without blocking the UI.

Usage:
    from gui_qt.utils.async_bridge import AsyncWorker, run_async

    # Method 1: Run with callback
    run_async(fetch_articles(), on_complete=self.display_articles)

    # Method 2: Worker with signals
    worker = AsyncWorker(fetch_articles())
    worker.finished.connect(self.display_articles)
    worker.error.connect(self.show_error)
    worker.start()
"""

import asyncio
import logging
import sys
import threading
import traceback
from typing import Any, Callable, Coroutine, Optional

from PyQt6.QtCore import (
    Qt,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals for async worker communication."""

    # Emitted when the coroutine completes successfully
    finished = pyqtSignal(object)

    # Emitted when an error occurs
    error = pyqtSignal(Exception)

    # Emitted with progress updates (optional)
    progress = pyqtSignal(int, str)  # (percent, message)

    # Emitted with partial results
    result = pyqtSignal(object)


class AsyncWorker(QRunnable):
    """
    Worker for running async coroutines in a thread pool.

    Usage:
        worker = AsyncWorker(my_async_function())
        worker.signals.finished.connect(self.on_complete)
        worker.signals.error.connect(self.on_error)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(
        self,
        coro: Coroutine,
        callback: Optional[Callable[[Any], None]] = None,
        error_callback: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """
        Initialize async worker.

        Args:
            coro: Coroutine to execute
            callback: Optional callback for result
            error_callback: Optional callback for errors
        """
        super().__init__()
        self.coro = coro
        self.signals = WorkerSignals()

        # Connect callbacks through signals (ensures Qt main thread invocation)
        if callback:
            self.signals.finished.connect(
                callback, type=Qt.ConnectionType.QueuedConnection
            )
        if error_callback:
            self.signals.error.connect(
                error_callback, type=Qt.ConnectionType.QueuedConnection
            )

        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        """Execute the coroutine in a new event loop."""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                result = loop.run_until_complete(self.coro)
                self.signals.finished.emit(result)
            finally:
                # Clean up the loop properly
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception as e:
                    logger.debug(f"AsyncWorker: shutdown_asyncgens cleanup failed: {e}")
                loop.close()

        except Exception as e:
            logger.error(f"AsyncWorker error: {e}")
            logger.debug(traceback.format_exc())
            self.signals.error.emit(e)


class _MainThreadDispatcher(QObject):
    """Safely dispatches background thread callbacks to the Qt main thread via signals."""

    callback_signal = pyqtSignal(object, object)
    error_signal = pyqtSignal(object, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.callback_signal.connect(self._handle_callback, type=Qt.ConnectionType.QueuedConnection)
        self.error_signal.connect(self._handle_error, type=Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object, object)
    def _handle_callback(self, fn: Any, result: Any) -> None:
        try:
            if callable(fn):
                fn(result)
        except Exception as exc:
            logger.error("Main thread callback error: %s", exc, exc_info=True)

    @pyqtSlot(object, object)
    def _handle_error(self, fn: Any, exc: Any) -> None:
        try:
            if callable(fn):
                fn(exc)
        except Exception as e:
            logger.error("Main thread error callback error: %s", e, exc_info=True)


class AsyncBridge(QObject):
    """
    Bridge between Qt and asyncio with a persistent event loop.

    Runs an asyncio event loop in a background thread and allows
    scheduling coroutines from the main thread.

    Callbacks are marshaled to the Qt main thread via pyqtSignal
    (QueuedConnection), which works correctly from the background asyncio
    thread — unlike QTimer.singleShot, which requires a Qt event loop in
    the emitting thread and silently drops callbacks when there isn't one.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[QThread] = None
        self._running = False
        self._loop_ready = threading.Event()  # set once the loop is actually running
        self._dispatcher = _MainThreadDispatcher(self)

    def start(self) -> None:
        """Start the background event loop thread and block until it is ready."""
        if self._running:
            return

        self._loop_ready.clear()
        self._thread = QThread()
        self._thread.run = self._run_loop  # type: ignore[method-assign]
        self._thread.start()

        # Wait up to 5 s for the loop to be live before returning to callers
        if not self._loop_ready.wait(timeout=5):
            logger.error("AsyncBridge: event loop did not start within 5 seconds")

        self._running = True
        logger.debug("AsyncBridge started")

    def stop(self) -> None:
        """Stop the background event loop."""
        if not self._running:
            return

        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            self._thread.quit()
            if self._thread != QThread.currentThread():
                self._thread.wait(5000)


        self._running = False
        logger.debug("AsyncBridge stopped")

    def _run_loop(self) -> None:
        """Run the event loop (called in background thread)."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Signal the main thread that the loop is live and ready
        self._loop.call_soon(self._loop_ready.set)

        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def run_coro(
        self,
        coro: Coroutine,
        callback: Optional[Callable[[Any], None]] = None,
        error_callback: Optional[Callable[[Exception], None]] = None,
    ) -> asyncio.Future:
        """
        Schedule a coroutine to run in the background loop.

        Args:
            coro: Coroutine to execute
            callback: Optional callback for result (runs on Qt main thread)
            error_callback: Optional callback for errors (runs on Qt main thread)

        Returns:
            Future that can be used to track completion

        Note: callbacks are marshaled to the Qt main thread via pyqtSignal
        with QueuedConnection. This is the fix for the cross-thread bug where
        QTimer.singleShot was being called from the background asyncio thread
        (which has no Qt event loop) and silently dropping all callbacks.
        """
        if not self._running or not self._loop:
            raise RuntimeError("AsyncBridge not running")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        if callback or error_callback:
            def on_done(f):
                try:
                    from PyQt6 import sip
                    if not self._dispatcher or sip.isdeleted(self._dispatcher):
                        logger.debug("AsyncBridge _dispatcher is deleted or shutting down, ignoring callback")
                        return
                except Exception:
                    pass

                try:
                    result = f.result()
                    if callback:
                        try:
                            from PyQt6 import sip
                            if not sip.isdeleted(self._dispatcher):
                                self._dispatcher.callback_signal.emit(callback, result)
                        except RuntimeError:
                            logger.debug("Dispatcher deleted prior to callback emit")
                except Exception as e:
                    if error_callback:
                        try:
                            from PyQt6 import sip
                            if not sip.isdeleted(self._dispatcher):
                                self._dispatcher.error_signal.emit(error_callback, e)
                        except RuntimeError:
                            logger.debug("Dispatcher deleted prior to error emit")

            future.add_done_callback(on_done)

        return future



# Global thread pool for async workers
_thread_pool: Optional[QThreadPool] = None


def get_thread_pool() -> QThreadPool:
    """Get or create the global thread pool."""
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = QThreadPool.globalInstance()
        _thread_pool.setMaxThreadCount(8)
    return _thread_pool


def run_async(
    coro: Coroutine,
    on_complete: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> AsyncWorker:
    """
    Run an async coroutine with optional callbacks.

    Args:
        coro: Coroutine to execute
        on_complete: Callback with result on success
        on_error: Callback with exception on error

    Returns:
        The worker (already started)

    Example:
        run_async(fetch_articles(), on_complete=self.display_articles)
    """
    worker = AsyncWorker(coro, callback=on_complete, error_callback=on_error)
    get_thread_pool().start(worker)
    return worker


# Singleton async bridge
_async_bridge: Optional[AsyncBridge] = None


def get_async_bridge() -> AsyncBridge:
    """Get or create the global async bridge."""
    global _async_bridge
    if _async_bridge is None:
        _async_bridge = AsyncBridge()
        _async_bridge.start()
    return _async_bridge


def cleanup() -> None:
    """Cleanup async resources (call on app exit)."""
    global _async_bridge, _thread_pool

    if _async_bridge:
        _async_bridge.stop()
        _async_bridge = None

    if _thread_pool:
        _thread_pool.waitForDone(3000)
        _thread_pool = None
