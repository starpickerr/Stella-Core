from __future__ import annotations

from core.services.sources_public import SourceDescriptor, SourceDirectory


def test_source_directory_lists_metadata_only():
    directory = SourceDirectory()
    directory.upsert(
        SourceDescriptor(
            source_id="email:school",
            plugin_id="stella.email",
            kind="email",
            label="学校邮箱",
        )
    )
    rows = directory.list_for_user()
    assert rows == [
        {
            "sourceId": "email:school",
            "pluginId": "stella.email",
            "kind": "email",
            "label": "学校邮箱",
            "status": "available",
        }
    ]


def test_source_metadata_is_scoped_to_original_user():
    from common.runtime_identity import identity_scope
    directory = SourceDirectory()
    with identity_scope(user_id='alice'):
        directory.upsert(SourceDescriptor('email:private', 'stella.email', 'email', 'Alice private'))
        assert len(directory.list_for_user()) == 1
    with identity_scope(user_id='bob'):
        assert directory.list_for_user() == []
        directory.remove('email:private')
    with identity_scope(user_id='alice'):
        assert len(directory.list_for_user()) == 1
