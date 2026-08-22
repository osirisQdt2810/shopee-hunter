"""The one sanctioned crossing between asyncio and the Qt main thread (ADR-003).

One asyncio loop runs for the app's lifetime on one worker thread. Coroutines are submitted
to it from the GUI thread, and their results come back as Qt signals — which Qt delivers on
the receiver's own thread, so a callback never touches a QObject from the wrong thread.

That is the whole design, and it is deliberately the *only* option: no ``QThread``
subclasses in feature code, no ``asyncio.run`` inside a slot (it would deadlock the loop
that is already running), no ``QApplication.processEvents`` while waiting.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from ..core.logging import get_logger

log = get_logger("gui.tasks")


class AsyncTask(QObject):
    """Handle for one submitted coroutine: emits exactly one of finished/failed/cancelled.

    Held by the caller so a running scan can be cancelled from a button, and so the result
    lands on the GUI thread through a normal queued signal connection.
    """

    finished = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._future: Optional[Any] = None

    def _attach(self, future: Any) -> None:
        self._future = future
        future.add_done_callback(self._on_done)

    def _on_done(self, future: Any) -> None:
        # Runs on the ASYNCIO thread. Emitting a signal is the only safe thing to do here —
        # Qt marshals it to whichever thread the receiver lives on.
        if future.cancelled():
            self.cancelled.emit()
            return
        error = future.exception()
        if error is not None:
            log.debug("async task failed: %r", error)
            self.failed.emit(error)
            return
        self.finished.emit(future.result())

    @property
    def running(self) -> bool:
        return self._future is not None and not self._future.done()

    def cancel(self) -> bool:
        """Request cancellation. The coroutine sees ``asyncio.CancelledError``."""
        return bool(self._future is not None and self._future.cancel())


class AsyncRunner(QObject):
    """Owns the asyncio loop and its thread.

    Created once in ``app.py`` and handed to the bridges. ``submit`` is safe to call from the
    GUI thread; everything inside a submitted coroutine runs off it.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, name="sale-hunter-asyncio", daemon=True
        )
        self._thread.start()
        # Block briefly so the first submit cannot race the loop's startup.
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            # Drain what is still pending so an aclose() in a `finally` actually runs; a
            # half-closed httpx client leaks sockets and a half-closed sqlite leaks a WAL.
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        parent: Optional[QObject] = None,
    ) -> AsyncTask:
        """Schedule ``factory()`` on the loop and return its handle.

        Takes a *factory*, not a coroutine object: building the coroutine on the GUI thread
        and awaiting it on another is legal but makes it far too easy to capture something
        thread-affine by accident. A callable makes the boundary obvious.
        """
        task = AsyncTask(parent)
        future = asyncio.run_coroutine_threadsafe(_wrap(factory), self._loop)
        task._attach(future)
        return task

    def run_sync(
        self, factory: Callable[[], Awaitable[Any]], timeout: float = 30.0
    ) -> Any:
        """Run a coroutine and block until it finishes.

        Only for startup and shutdown, where there is no window to keep responsive. Calling
        this from a slot is a bug — it blocks the GUI thread, which is the thing this whole
        module exists to prevent.
        """
        return asyncio.run_coroutine_threadsafe(_wrap(factory), self._loop).result(
            timeout
        )

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the loop and join its thread. Idempotent."""
        if not self._thread.is_alive():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("asyncio thread did not stop within %.1fs", timeout)


async def _wrap(factory: Callable[[], Awaitable[Any]]) -> Any:
    return await factory()
