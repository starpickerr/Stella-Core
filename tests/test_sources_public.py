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
