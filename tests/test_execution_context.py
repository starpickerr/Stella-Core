"""Core execution scopes preserve workspace ownership across nested work."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from common.runtime_identity import identity_scope, submit


@pytest.fixture
def work(tmp_path, monkeypatch):
    from agent.workspace import project_store
    root = tmp_path / 'work'
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: root)
    monkeypatch.setattr(project_store, '_store_file', lambda: str(tmp_path / 'projects.json'))
    return root


def test_workspace_service_uses_ambient_agent_and_stable_task_space(work):
    from core.workspace.service import WorkspaceService
    with identity_scope(agent_id='alpha', session_id='source', task_id='daily'):
        context = WorkspaceService.context()
        assert context.root == work / 'automations/alpha/daily'
        assert WorkspaceService.context(session_id='output').root == context.root
    assert not work.exists()


def test_execution_scope_is_immutable_thread_safe_and_restored(work):
    from core.execution.context import capture_execution_context, current_execution_context, execution_scope
    with identity_scope(agent_id='alpha', user_id='alice', session_id='chat'):
        context = capture_execution_context(origin='tool')
        with pytest.raises(FrozenInstanceError):
            context.origin = 'ui'
        with execution_scope(context):
            with ThreadPoolExecutor(1) as pool:
                assert submit(pool, current_execution_context).result() == context
            with execution_scope(consumer_plugin_id='stella.briefing') as child:
                assert child.identity == context.identity
                assert child.workspace == context.workspace
                assert child.consumer_plugin_id == 'stella.briefing'
            assert current_execution_context() == context
    assert current_execution_context() is None


def test_nested_context_cannot_replace_user_workspace_or_background_purpose(work):
    from core.execution.context import capture_execution_context, execution_scope
    with identity_scope(agent_id='alpha', user_id='alice', task_id='daily', session_id='source'):
        parent = capture_execution_context(origin='job', consumer_plugin_id='stella.briefing')
        with execution_scope(parent):
            for forged in [replace(parent, identity=parent.identity.derive(user_id='bob')),
                           replace(parent, workspace=replace(parent.workspace, root=work / 'elsewhere')),
                           replace(parent, purpose='interactive'), replace(parent, origin='ui'),
                           replace(parent, consumer_plugin_id='stella.tasks')]:
                with pytest.raises(PermissionError):
                    with execution_scope(forged):
                        pytest.fail('broader context admitted')
            with identity_scope(user_id='bob'):
                with pytest.raises(PermissionError):
                    parent.check_active()


def test_nested_deadlines_can_only_shrink_and_expiry_is_checked(work):
    from core.execution.context import capture_execution_context, execution_scope
    with identity_scope(agent_id='alpha', session_id='chat'):
        deadline = datetime.now(timezone.utc) + timedelta(seconds=20)
        parent = capture_execution_context(origin='tool', deadline=deadline)
        with execution_scope(parent):
            with execution_scope(deadline=deadline + timedelta(seconds=10)) as child:
                assert child.deadline == deadline
            with pytest.raises(PermissionError, match='expired'):
                with execution_scope(deadline=datetime.now(timezone.utc) - timedelta(seconds=1)):
                    pytest.fail('expired context admitted')


def test_workspace_service_keeps_explicit_project_and_automation_private_root(work, tmp_path):
    from core.workspace.service import WorkspaceService
    from agent.workspace import project_store
    project = tmp_path / 'project'
    project.mkdir()
    project_store.set_project_dir('output', str(project), 'alpha')
    with identity_scope(agent_id='alpha', session_id='transcript', execution_session_id='output', task_id='daily'):
        context = WorkspaceService.context()
        assert context.root == project
        assert context.private_root == work / 'automations/alpha/daily'
        assert not work.exists()


def test_child_agent_run_changes_only_run_identity_and_keeps_parent_constraints(work):
    from core.execution.context import execution_scope, child_execution_scope, current_execution_context
    from common.runtime_identity import current_identity
    with identity_scope(agent_id='alpha', user_id='alice', session_id='chat', run_id='parent'):
        with execution_scope(consumer_plugin_id='stella.briefing') as parent:
            with child_execution_scope('child') as child:
                assert current_identity().run_id == 'child'
                assert child.identity.derive(run_id='parent') == parent.identity
                assert child.workspace == parent.workspace
                assert child.origin == parent.origin and child.purpose == parent.purpose
                assert child.consumer_plugin_id == parent.consumer_plugin_id
                assert current_execution_context() == child
            assert current_identity().run_id == 'parent'
            assert current_execution_context() == parent
