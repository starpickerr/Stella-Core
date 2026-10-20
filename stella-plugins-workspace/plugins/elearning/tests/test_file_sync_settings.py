"""Directory configuration is business state, never a second permission switch."""
import io
import json
from unittest.mock import Mock

import pytest

from stella_elearning_test_support import ElearningService, settings, sync_files
from stella_elearning_test_support.fakes import BASE, FakeCanvas, config


@pytest.mark.parametrize('legacy_flag', [None, False])
def test_configured_directory_syncs_without_legacy_write_switch(config_path, tmp_path, legacy_flag):
    root = tmp_path / '课程资料'
    root.mkdir()
    saved = config(file_sync_root=str(root.resolve()))
    if legacy_flag is not None:
        saved['file_sync_enabled'] = legacy_flag
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(saved))
    before = config_path.read_bytes()
    canvas = FakeCanvas()
    canvas.rows['files'] = [{'id': 4, 'filename': '../讲义.pdf', 'url': BASE + '/files/4/download'}]
    canvas.open = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(b'courseware'))
    service = ElearningService(config_path.parent, client_factory=lambda _: canvas)
    for _ in range(2):
        result = service.sync_files(layout='courseware')
        assert result['status'] == 'completed' and result['errors'] == []
    assert canvas.open.call_count == 1
    assert len(list(root.rglob('*.pdf'))) == 1
    assert not (tmp_path / '讲义.pdf').exists()
    assert config_path.read_bytes() == before  # Reading/using old settings never rewrites accounts.
    assert 'file_sync_enabled' not in service.get_settings()


def test_directory_configuration_and_course_edit_preserve_account_and_records(config_path, tmp_path):
    root = tmp_path / '课程资料'
    root.mkdir()
    settings.save_settings(config())
    cfg = settings.load_settings()
    settings.save_session(cfg, {'cookies': [{'name': 'test', 'value': 'private'}]})
    manifest = settings.file_sync_manifest_path(cfg)
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"existing":"sync-record"}')
    cursor = {'elearning_state': 'unchanged'}
    settings.set_cursors(cursor)
    credentials = settings.load_settings()['password']
    result = settings.save_file_sync_settings(str(root))
    assert result['file_sync_root'] == str(root.resolve())
    settings.save_settings({'courses': ['43']})
    assert settings.load_settings()['file_sync_root'] == str(root.resolve())
    assert settings.load_settings()['password'] == credentials
    assert settings.get_cursors() == cursor and manifest.read_text() == '{"existing":"sync-record"}'
    assert settings.session_path(cfg).is_file()


def _download_rows():
    return [({'id': 42, 'name': '课程'}, {'id': 4, 'filename': '讲义.pdf', 'url': BASE + '/files/4/download'})]


def test_sync_refuses_ancestor_symlink_swap_after_directory_validation(config_path, tmp_path, monkeypatch):
    parent, outside = tmp_path / 'allowed', tmp_path / 'outside'
    root = parent / 'selected'
    root.mkdir(parents=True)
    (outside / 'selected').mkdir(parents=True)
    settings.save_settings(config(file_sync_root=str(root.resolve()), file_sync_enabled=True))
    cfg, store = settings.load_settings(), settings.store()
    load = store.load_settings
    swapped = False

    def swap():
        nonlocal swapped
        if not swapped:
            swapped = True
            parent.rename(tmp_path / 'original')
            parent.symlink_to(outside, target_is_directory=True)
        return load()

    monkeypatch.setattr(store, 'load_settings', swap)
    client = Mock()
    client.open.side_effect = lambda *args, **kwargs: io.BytesIO(b'courseware')
    from stella_elearning_test_support import file_sync
    errors = file_sync.sync_files(client, cfg, _download_rows(), store)
    assert errors and '目录' in errors[0]
    assert not list(outside.rglob('*.pdf'))
    client.open.assert_not_called()


def test_sync_refuses_root_move_during_download(config_path, tmp_path):
    root = tmp_path / 'selected'
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root.resolve()), file_sync_enabled=True))
    cfg = settings.load_settings()
    moved = tmp_path / 'moved'

    def download(*args, **kwargs):
        root.rename(moved)
        root.mkdir()
        return io.BytesIO(b'courseware')

    client = Mock()
    client.open.side_effect = download
    errors = sync_files(client, cfg, _download_rows())
    assert errors and '目录' in errors[0]
    assert not list(moved.rglob('*.pdf')) and not list(root.rglob('*.pdf'))
    assert not list(moved.rglob('.elearning-*'))


def test_sync_keeps_os_permission_errors_and_does_not_record_success(config_path, tmp_path, monkeypatch):
    from stella_elearning_test_support import file_sync
    import errno

    root = tmp_path / 'selected'
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root.resolve())))
    cfg = settings.load_settings()
    original = file_sync.os.open

    def denied(path, flags, *args, **kwargs):
        if str(path) == 'selected' and 'dir_fd' in kwargs:
            raise PermissionError(errno.EACCES, 'Permission denied')
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(file_sync.os, 'open', denied)
    client = Mock()
    errors = sync_files(client, cfg, _download_rows())
    assert errors and '权限不足' in errors[0]
    client.open.assert_not_called()
    assert not settings.file_sync_manifest_path(cfg).exists()
    assert list(root.iterdir()) == []


def test_exhausted_download_preserves_existing_file_and_has_no_success_record(config_path, tmp_path, monkeypatch):
    from stella_elearning_test_support import file_sync
    import http.client

    root = tmp_path / 'selected'
    folder = root / '课程--42'
    folder.mkdir(parents=True)
    existing = folder / '讲义--4.pdf'
    existing.write_bytes(b'local notes')
    settings.save_settings(config(file_sync_root=str(root.resolve())))
    cfg = settings.load_settings()

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b'partial', 10)

    client = Mock()
    client.open.side_effect = lambda *args, **kwargs: Interrupted()
    monkeypatch.setattr(file_sync.time, 'sleep', lambda _: None)
    errors = sync_files(client, cfg, _download_rows())
    assert errors and '已重试 3 次' in errors[0]
    assert client.open.call_count == 3
    assert existing.read_bytes() == b'local notes'
    assert not list(folder.glob('.elearning-*'))
    assert not settings.file_sync_manifest_path(cfg).exists()


def test_remote_update_preserves_concurrent_local_edit_at_publication(config_path, tmp_path, monkeypatch):
    from stella_elearning_test_support import file_sync

    root = tmp_path / 'selected'
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root.resolve())))
    cfg, store = settings.load_settings(), settings.store()
    rows = _download_rows()
    rows[0][1]['updated_at'] = 'v1'
    client = Mock()
    client.open.side_effect = lambda *args, **kwargs: io.BytesIO(b'first')
    assert file_sync.sync_files(client, cfg, rows, store) == []
    target = next(root.rglob('*.pdf'))
    rows[0][1]['updated_at'] = 'v2'
    client.open.side_effect = lambda *args, **kwargs: io.BytesIO(b'new remote version')
    audit = store.record_audit

    def edit_before_publication(**event):
        target.write_bytes(b'concurrent local notes')
        return audit(**event)

    monkeypatch.setattr(store, 'record_audit', edit_before_publication)
    assert file_sync.sync_files(client, cfg, rows, store) == []
    assert target.read_bytes() == b'concurrent local notes'
    assert any(p.read_bytes() == b'new remote version' for p in root.rglob('*.pdf'))
    downloads = client.open.call_count
    assert file_sync.sync_files(client, cfg, rows, store) == []
    assert client.open.call_count == downloads
