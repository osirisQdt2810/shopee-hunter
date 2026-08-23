"""The asyncio ↔ Qt crossing (ADR-003), and the delivery race that lived in it.

`AsyncRunner.submit` returns a task the caller then connects to. Nothing guarantees the
coroutine has not already finished by the time it returns — and a `concurrent.futures`
callback added to an already-done future runs *immediately, on the calling thread*. So the
outcome could be emitted inside `submit`, before a single slot was connected: the result went
nowhere and `busy` never cleared. The window is small on a live scan and wide open in demo
mode, where the fixture source answers instantly.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def runner(qapp):
    from shopee_hunter.gui.tasks import AsyncRunner

    runner = AsyncRunner()
    yield runner
    runner.shutdown()


def _settle(qapp, recorder, timeout_ms: int = 3000) -> None:
    """Turn the Qt event loop until the task reports, or give up.

    `processEvents` with a max-time argument blocks for up to that long waiting for an
    event, which a tight spin does not — a 10ms coroutine outruns 300 empty iterations.
    """
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired() and not recorder.total:
        qapp.processEvents(QEventLoop.AllEvents, 20)


class _Recorder:
    """Connects the way a bridge does: after `submit` has returned."""

    def __init__(self, task):
        self.results: list[object] = []
        self.errors: list[BaseException] = []
        self.cancels = 0
        task.finished.connect(self.results.append)
        task.failed.connect(self.errors.append)
        task.cancelled.connect(self._cancelled)

    def _cancelled(self) -> None:
        self.cancels += 1

    @property
    def total(self) -> int:
        return len(self.results) + len(self.errors) + self.cancels


class TestDeliveryIsNeverMissed:
    def test_an_already_finished_coroutine_still_reaches_a_later_connection(
        self, qapp, runner
    ):
        """The regression. An instant coroutine must not out-run its own caller.

        `add_done_callback` fires synchronously when the future is already done, so the old
        code emitted `finished` from inside `submit()` — into zero connections.
        """

        async def instant() -> str:
            return "done"

        task = runner.submit(instant)
        # Deliberately give the coroutine every chance to finish BEFORE we connect, which is
        # the scenario the old implementation lost.
        task._future.result(timeout=3)
        recorder = _Recorder(task)

        _settle(qapp, recorder)

        assert recorder.results == ["done"], "the result must survive a late connection"

    def test_a_normal_coroutine_delivers_once(self, qapp, runner):
        async def slow() -> int:
            await asyncio.sleep(0.01)
            return 42

        task = runner.submit(slow)
        recorder = _Recorder(task)

        _settle(qapp, recorder)

        assert recorder.results == [42]
        assert recorder.total == 1, "exactly one of finished/failed/cancelled"

    def test_a_failure_is_delivered_as_failed_not_finished(self, qapp, runner):
        async def boom() -> None:
            raise ValueError("nope")

        task = runner.submit(boom)
        task._future.exception(timeout=3)
        recorder = _Recorder(task)

        _settle(qapp, recorder)

        assert not recorder.results
        assert len(recorder.errors) == 1
        assert isinstance(recorder.errors[0], ValueError)
