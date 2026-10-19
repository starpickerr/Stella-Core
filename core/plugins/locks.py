"""Cross-process admission leases for managed plugin data and package changes."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import time


@contextmanager
def package_lock(root: Path, plugin_id: str, *, exclusive: bool, timeout: float = 10):
    from core.plugins.caller import remaining_invocation_seconds

    remaining = remaining_invocation_seconds()
    if remaining is not None:
        timeout = min(timeout, remaining)
    # The first supported plugin platform is macOS arm64. Fail closed elsewhere
    # until its process-lock implementation has been validated.
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError('plugin data leases are unsupported on this platform') from exc
    folder = Path(root) / 'management' / 'locks'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (hashlib.sha256(plugin_id.encode()).hexdigest() + '.lock')
    with path.open('a+b') as stream:
        deadline = time.monotonic() + timeout
        while True:
            remaining_invocation_seconds()
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('plugin data lease is busy') from None
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        try:
            remaining_invocation_seconds()
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
