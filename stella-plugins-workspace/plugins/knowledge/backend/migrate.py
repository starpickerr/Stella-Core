"""Knowledge migration preserves documents in the host's recoverable directory copy."""
from pathlib import Path


def apply(migration_id, data_handle):
    Path(data_handle['dataDir']).mkdir(parents=True, exist_ok=True)
    return {'migrationId': migration_id, 'applied': True, 'schemaVersion': 1}


def verify(migration_id, data_handle):
    root = Path(data_handle['dataDir'])
    valid = root.is_dir() and all(not file.is_symlink() and file.resolve().is_relative_to(root.resolve())
                                  for file in root.rglob('*'))
    return {'migrationId': migration_id, 'verified': valid, 'schemaVersion': 1}
