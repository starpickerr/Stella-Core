"""Host-selected private storage for plugins without a legacy domain path."""
from pathlib import Path
import re


def private_data_handle(plugin_id: str, user_id: str, *, ensure=False) -> dict:
    if not isinstance(plugin_id, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+', plugin_id):
        raise ValueError('invalid plugin storage namespace')
    from common.state_dir import user_root, shared_root
    from common.runtime_identity import identity_scope
    with identity_scope(user_id=user_id):
        root = user_root()
    path = Path(root) / 'plugins' / plugin_id
    anchor = Path(shared_root())
    try:
        path.relative_to(anchor)
    except ValueError:
        # Explicit standalone/test roots retain a local anchor. OS ancestors
        # such as macOS /var are outside the configured storage boundary.
        anchor = Path(root).parent
    candidates = [path]
    while candidates[-1] != anchor and candidates[-1] != candidates[-1].parent:
        candidates.append(candidates[-1].parent)
    for candidate in candidates:
        if candidate.is_symlink():
            raise PermissionError('plugin storage cannot use symlinks')
    if ensure:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    return {'namespace': plugin_id, 'dataDir': str(path.absolute())}
