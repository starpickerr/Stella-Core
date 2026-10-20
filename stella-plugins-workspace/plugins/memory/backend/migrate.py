"""Import legacy markdown once on the coordinator's private recoverable copy."""
from pathlib import Path
import shutil


def apply(migration_id, data_handle):
    target = Path(data_handle['dataDir'])
    target.mkdir(parents=True, exist_ok=True)
    marker = target / '.legacy-imported'
    if not marker.exists():
        legacy = Path(data_handle['legacyMemoryDir'])
        if legacy.is_dir():
            for source in legacy.rglob('*.md'):
                if source.is_symlink() or not source.resolve().is_relative_to(legacy.resolve()):
                    raise PermissionError('legacy memory symlink refused')
                relative = source.relative_to(legacy)
                if any(part.startswith('.') for part in relative.parts):
                    continue
                destination = target / 'memory' / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copy2(source, destination)
        main = Path(data_handle['legacyMainFile'])
        if main.is_symlink():
            raise PermissionError('legacy main memory symlink refused')
        if main.is_file() and not (target / 'MEMORY.md').exists():
            shutil.copy2(main, target / 'MEMORY.md')
        marker.write_text(migration_id, encoding='utf-8')
    return {'migrationId': migration_id, 'applied': True, 'schemaVersion': 1}


def verify(migration_id, data_handle):
    root = Path(data_handle['dataDir'])
    return {'migrationId': migration_id, 'verified': root.is_dir() and (root / '.legacy-imported').is_file(), 'schemaVersion': 1}
