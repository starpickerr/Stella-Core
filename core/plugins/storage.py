"""Host-selected private storage for plugins without a legacy domain path."""
from pathlib import Path
import re


def private_data_handle(plugin_id: str, user_id: str, *, ensure=False) -> dict:
    if not isinstance(plugin_id, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+', plugin_id):
        raise ValueError('invalid plugin storage namespace')
    from common.state_dir import user_root
    from common.runtime_identity import identity_scope
    with identity_scope(user_id=user_id):
        root = user_root()
    path = Path(root) / 'plugins' / plugin_id
    for candidate in (Path(root), Path(root) / 'plugins', path):
        if candidate.is_symlink():
            raise PermissionError('plugin storage cannot use symlinks')
    if ensure:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    return {'namespace': plugin_id, 'dataDir': str(path.absolute())}
