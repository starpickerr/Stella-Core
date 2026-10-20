"""Bounded memory document writes under the approved plugin namespace."""
import hashlib
import os
from pathlib import Path
import tempfile


def check_active():
    # Standalone domain tests have no host SDK. A managed worker always does.
    try:
        from stella_host import cancellation_token
    except ImportError:
        return
    if cancellation_token().is_set():
        raise PermissionError('memory invocation cancelled or expired')


def target_path(root, path):
    if not isinstance(path, str) or path.startswith(('/', '\\')) or '..' in path.replace('\\', '/').split('/'):
        raise ValueError('invalid memory path')
    if path != 'MEMORY.md' and not path.startswith('memory/'):
        raise ValueError('only memory documents may be written')
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or target.suffix != '.md':
        raise PermissionError('memory path escapes namespace')
    return target


def write(root, path, content, append=False, expected_hash=None, snapshotId=None):
    check_active()
    target = target_path(root, path)
    if not isinstance(content, str) or len(content.encode()) > 1_000_000:
        raise ValueError('invalid memory content')
    old = target.read_text(encoding='utf-8') if target.is_file() else ''
    if expected_hash is not None and expected_hash != hashlib.sha256(old.encode()).hexdigest():
        raise ValueError('memory revision conflict')
    result = old + content if append else content
    if snapshotId:
        from memory_domain.snapshots import record
        record(root, snapshotId, path, old if target.is_file() else None, result)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix='.memory-write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        check_active()
        os.replace(staged, target)
    finally:
        Path(staged).unlink(missing_ok=True)
    return {'path': path, 'hash': hashlib.sha256(result.encode()).hexdigest(), 'written': True}
