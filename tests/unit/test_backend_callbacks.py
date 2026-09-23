"""AlpmBackend callback wiring (these units need no pyalpm import).

Physical QA found that ``commit()`` can succeed while every ``unlink()``
fails (read-only root): the DB entry disappears, files stay, no exception.
The backend therefore collects ALPM_LOG_ERROR messages during the
transaction and fails the removal if any appeared — these tests pin the
capture half of that mechanism.
"""

from types import SimpleNamespace

from cachyuninstall.privilege.backend import AlpmBackend, TxEvent


class _Sink:
    def __init__(self) -> None:
        self.events: list[TxEvent] = []

    def emit(self, event: TxEvent) -> None:
        self.events.append(event)


def test_error_level_logs_are_collected() -> None:
    backend = AlpmBackend()
    handle = SimpleNamespace()
    sink = _Sink()
    errors: list[str] = []
    backend._wire_callbacks(handle, object(), sink, errors)

    handle.logcb(1, "cannot remove file '/usr/bin/x': Read-only file system\n")
    handle.logcb(4, "unlinking /usr/bin/x\n")

    # trailing newline stripped for a readable failure message; INFO not kept
    assert errors == ["cannot remove file '/usr/bin/x': Read-only file system"]
    assert [e.kind for e in sink.events] == ["log", "log"]


def test_all_error_logs_are_kept_for_counting() -> None:
    backend = AlpmBackend()
    handle = SimpleNamespace()
    sink = _Sink()
    errors: list[str] = []
    backend._wire_callbacks(handle, object(), sink, errors)

    handle.logcb(1, "first failure")
    handle.logcb(1, "second failure")

    assert len(errors) == 2


def test_callbacks_still_wired_without_error_collection() -> None:
    # Default path (errors=None): log events are emitted, nothing collected.
    backend = AlpmBackend()
    handle = SimpleNamespace()
    sink = _Sink()
    backend._wire_callbacks(handle, object(), sink)

    handle.logcb(1, "boom")
    handle.eventcb(12, None)
    handle.progresscb("pkg", 50, 1, 1)

    assert [e.kind for e in sink.events] == ["log", "stage", "progress"]
    assert sink.events[0].message == "boom"
