"""Threading helpers (§226): QThreadPool-runnable wrappers with signals.

Qt rule respected: no GUI objects are touched off the GUI thread; workers
return plain domain objects which the GUI consumes in slot callbacks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

T = TypeVar("T")


class _Signals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)


class Worker(QRunnable, Generic[T]):
    """Run `fn()` on a pool thread; emit result(T) or error(str)."""

    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.result.emit(self._fn())
        except Exception as exc:  # surfaced as text; GUI maps to friendly copy
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")


class Executor:
    """Tiny facade over the global thread pool."""

    @staticmethod
    def run(
        fn: Callable[[], T],
        on_result: Callable[[T], None],
        on_error: Callable[[str], None] | None = None,
    ) -> Worker[T]:
        worker: Worker[T] = Worker(fn)
        worker.signals.result.connect(on_result)
        if on_error is not None:
            worker.signals.error.connect(on_error)
        pool = QThreadPool.globalInstance()
        if pool is None:  # pool exists after QApplication; defensive only
            raise RuntimeError("QThreadPool unavailable without QApplication")
        pool.start(worker)
        return worker
