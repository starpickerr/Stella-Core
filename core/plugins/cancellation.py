"""Core-owned cancellation scope and per-invocation cooperative worker signal."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
import threading

_EVENTS = ContextVar('plugin_invocation_cancellation', default=())


@contextmanager
def cancellation_scope(event):
    parent = _EVENTS.get()
    events = parent if event is None or event in parent else (*parent, event)
    token = _EVENTS.set(events)
    try:
        yield
    finally:
        _EVENTS.reset(token)


def check_cancelled():
    if any(event.is_set() for event in _EVENTS.get()):
        from agent.protocol.cancel import AgentCancelledError
        raise AgentCancelledError('插件调用已取消')


@contextmanager
def worker_cancellation_handle():
    events = _EVENTS.get()
    if not events:
        yield None
        return
    check_cancelled()
    with TemporaryDirectory(prefix='stella-invocation-') as directory:
        path = Path(directory) / 'cancel'
        path.touch(mode=0o600)
        done = threading.Event()
        def monitor():
            while not done.is_set():
                if any(event.is_set() for event in events):
                    path.write_bytes(b'1')
                    return
                done.wait(.02)
        watcher = threading.Thread(target=monitor, name='plugin-cancellation', daemon=True)
        watcher.start()
        try:
            yield str(path)
        finally:
            done.set()
            watcher.join(timeout=1)


def current_cancellation_events():
    """Return active cooperative signals for other Core runtimes."""
    return _EVENTS.get()
