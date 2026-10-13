"""Workspace dispatch logs client-visible 403/404 failures."""
from agent.workspace.service import WorkspaceService
from common.log import logger


def test_workspace_dispatch_logs_missing_file(tmp_path, caplog):
    service = WorkspaceService(str(tmp_path))
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger=logger.name):
            result = service.dispatch("read", {"path": "missing.txt"})
    finally:
        logger.removeHandler(caplog.handler)

    assert result["code"] == 404
    assert "[Workspace] dispatch read → 404" in caplog.text


def test_workspace_dispatch_logs_path_escape(tmp_path, caplog):
    service = WorkspaceService(str(tmp_path))
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger=logger.name):
            result = service.dispatch("read", {"path": "../escape.txt"})
    finally:
        logger.removeHandler(caplog.handler)

    assert result["code"] == 403
    assert "[Workspace] dispatch read → 403" in caplog.text
