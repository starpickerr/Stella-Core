import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def test_knowledge_action_handler_delegates_to_dispatch(tmp_path):
    from channel.desktop.desktop_channel import KnowledgeActionHandler

    request = {"action": "create_category", "payload": {"path": "research"}}
    dispatched = {"action": "create_category", "code": 200, "message": "success",
                  "payload": {"path": "research", "created": True}}

    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.desktop.desktop_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("core.services.knowledge_facade.KnowledgePort.dispatch", return_value=dispatched) as dispatch:
        response = json.loads(KnowledgeActionHandler().POST())

    dispatch.assert_called_once_with("create_category", {"path": "research"})
    assert response["status"] == "success"
    assert response["payload"]["created"] is True


def test_knowledge_action_handler_preserves_dispatch_error(tmp_path):
    from channel.desktop.desktop_channel import KnowledgeActionHandler

    dispatched = {"action": "delete_documents", "code": 403,
                  "message": "protected knowledge file: index.md", "payload": None}
    request = {"action": "delete_documents", "payload": {"paths": ["index.md"]}}

    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.desktop.desktop_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("core.services.knowledge_facade.KnowledgePort.dispatch", return_value=dispatched):
        response = json.loads(KnowledgeActionHandler().POST())

    assert response["status"] == "error"
    assert response["code"] == 403
    assert response["message"] == "protected knowledge file: index.md"


def test_desktop_knowledge_management_contract():
    root = Path(__file__).parents[1]
    page = (root / "desktop/src/renderer/src/pages/KnowledgePage.tsx").read_text(encoding="utf-8")
    client = (root / "desktop/src/renderer/src/api/client.ts").read_text(encoding="utf-8")
    assert "action: 'create_category'" in page
    assert "action: 'create_document'" in page
    assert "apiClient.importKnowledge" in page
    assert "KNOWLEDGE_IMPORT_MAX_FILE_SIZE" in page
    assert "async importKnowledge(" in client


class UploadedFile:
    def __init__(self, filename, content):
        self.filename = filename
        self.value = content


def test_knowledge_import_handler_delegates_to_dispatch(tmp_path):
    from channel.desktop.desktop_channel import KnowledgeImportHandler

    dispatched = {"action": "import_documents", "code": 200, "message": "success",
                  "payload": {"imported": 2, "skipped": 0, "failed": 0}}
    params = {
        "target_category": "notes",
        "conflict_strategy": "rename",
        "files": [UploadedFile("a.md", b"# A"), UploadedFile("b.txt", b"B")],
    }

    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.ctx", SimpleNamespace(env={}), create=True), \
         patch("channel.desktop.desktop_channel._raw_web_input", return_value=params), \
         patch("channel.desktop.desktop_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("core.services.knowledge_facade.KnowledgePort.dispatch", return_value=dispatched) as dispatch:
        response = json.loads(KnowledgeImportHandler().POST())

    dispatch.assert_called_once()
    action, payload = dispatch.call_args.args
    assert action == "import_documents"
    assert payload["target_category"] == "notes"
    assert payload["conflict_strategy"] == "rename"
    assert [f["filename"] for f in payload["files"]] == ["a.md", "b.txt"]
    assert response["status"] == "success"
    assert response["payload"]["imported"] == 2


def test_knowledge_import_handler_rejects_large_content_length(tmp_path):
    from channel.desktop.desktop_channel import KnowledgeImportHandler
    from core.services import knowledge_facade as KnowledgeService
    assert KnowledgeService.MAX_IMPORT_TOTAL_SIZE == 200 * 1024 * 1024

    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.ctx", create=True) as ctx:
        ctx.env = {"CONTENT_LENGTH": str(KnowledgeService.MAX_IMPORT_TOTAL_SIZE + 1)}
        response = json.loads(KnowledgeImportHandler().POST())

    assert response["status"] == "error"
    assert response["code"] == 413
    assert response["message"] == "import batch too large"
