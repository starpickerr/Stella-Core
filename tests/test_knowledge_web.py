import json
from pathlib import Path
from unittest.mock import patch


def test_knowledge_action_handler_delegates_to_dispatch(tmp_path):
    from channel.web.web_channel import KnowledgeActionHandler

    request = {"action": "create_category", "payload": {"path": "research"}}
    dispatched = {"action": "create_category", "code": 200, "message": "success",
                  "payload": {"path": "research", "created": True}}

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", return_value=dispatched) as dispatch:
        response = json.loads(KnowledgeActionHandler().POST())

    dispatch.assert_called_once_with("create_category", {"path": "research"})
    assert response["status"] == "success"
    assert response["payload"]["created"] is True


def test_knowledge_action_handler_preserves_dispatch_error(tmp_path):
    from channel.web.web_channel import KnowledgeActionHandler

    dispatched = {"action": "delete_documents", "code": 403,
                  "message": "protected knowledge file: index.md", "payload": None}
    request = {"action": "delete_documents", "payload": {"paths": ["index.md"]}}

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data", return_value=json.dumps(request).encode()), \
         patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("agent.knowledge.service.KnowledgeService.dispatch", return_value=dispatched):
        response = json.loads(KnowledgeActionHandler().POST())

    assert response["status"] == "error"
    assert response["code"] == 403
    assert response["message"] == "protected knowledge file: index.md"


def test_knowledge_frontend_management_contract():
    root = Path(__file__).parents[1]
    html = (root / "channel/web/chat.html").read_text(encoding="utf-8")
    js = (root / "channel/web/static/js/console.js").read_text(encoding="utf-8")

    assert 'id="knowledge-dialog-overlay"' in html
    assert "function openKnowledgeDialog(" in js
    assert "function _knowledgeCategoryPaths(" in js
    assert "dispatchKnowledgeAction('create_category'" in js
    assert "dispatchKnowledgeAction('rename_category'" in js
    assert "dispatchKnowledgeAction('delete_category'" in js
    assert "dispatchKnowledgeAction('delete_documents'" in js
    assert "dispatchKnowledgeAction('move_documents'" in js

    knowledge_section = js[js.index("// Knowledge View"):js.index("function _hasFilterMatch")]
    assert "prompt(" not in knowledge_section
    assert "alert(" not in knowledge_section
    assert "if (path === 'index.md' || path === 'log.md') return '';" in knowledge_section
