"""Exercise scheduler cards with a mocked, isolated desktop backend."""

import json
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://localhost:5173')
tasks = [
    dict(id='plain-1', name='Standalone digest', enabled=True, created_at='', updated_at='',
         schedule={'type': 'cron', 'expression': '0 8 * * *'},
         action={'type': 'send_message', 'content': 'Digest', 'channel_type': 'web'},
         next_run_at='2026-10-10T08:00:00Z'),
    dict(id='linked-1', linked_todo_id='todo-1', name='Linked reminder', enabled=True,
         created_at='', updated_at='', schedule={'type': 'once', 'run_at': '2026-10-10T14:00:00Z'},
         action={'type': 'send_message', 'content': 'Reminder', 'channel_type': 'feishu'},
         next_run_at='2026-10-10T14:00:00Z'),
]


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}], capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/scheduler':
        data['tasks'] = tasks
    elif path == '/api/scheduler/destinations':
        data['destinations'] = [dict(channel_type='desktop', configured=True, ready=True, status='ready', recipients=[]),
                                dict(channel_type='weixin', configured=True, ready=False, status='no_recipient', recipients=[])]
    elif path == '/api/sessions':
        data.update(sessions=[
            dict(session_id='chat-a', title='对话 A', created_at=0, last_active=1, msg_count=1),
            dict(session_id='chat-b', title='对话 B', created_at=0, last_active=2, msg_count=2),
        ], total=2, page=1, page_size=50, has_more=False)
    elif path == '/api/projects':
        data.update(projects=[], current=None)
    elif path == '/api/todos':
        data['todos'] = [dict(
            id='todo-1', title='Linked todo', notes='', status='todo', parent_id=None, sort_order=0,
            remind_at=None, scheduler_task_id='linked-1', reminder_sync_pending=False, reminder_sync_error='',
            subtask_count=0, progress_completed=0, progress_total=0, progress_percent=0,
            dependency_ids=[], blocked_by=[], due_on=None, due_time=None, timezone='Asia/Shanghai',
            priority=0, completed_at=None, repeat_frequency='none', repeat_days='[]', repeat_until=None,
            planned_on=None, list_name='', tags='[]', flagged=0, checklist='[]', source_type=None,
            source_key=None, source_url='', user_modified=0, briefing_id=None, created_at='', updated_at='',
        )]
    elif path == '/api/todos/reminders/uncertain':
        data['reminders'] = []
    elif route.request.method == 'POST' and path == '/api/scheduler/update':
        body = json.loads(route.request.post_data or '{}')
        for task in tasks:
            if task['id'] == body.get('task_id') and 'run_permission_mode' in body:
                if body['run_permission_mode'] == 'inherit':
                    task.pop('run_permission_mode', None)
                else:
                    task['run_permission_mode'] = body['run_permission_mode']
    elif route.request.method == 'POST' and path == '/api/scheduler/run':
        data['message'] = 'queued'
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {platform: 'darwin',
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/tasks', wait_until='networkidle')
        page.get_by_text('Linked reminder').click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog).to_have_attribute('aria-label', '编辑任务')
        expect(dialog.locator('input').first).to_have_value('Linked reminder')
        expect(dialog).to_contain_text('此提醒由关联事务管理，请在事务中修改。')
        assert page.url.endswith('/#/tasks'), page.url
        page.get_by_role('dialog').get_by_role('button', name='取消').click()
        page.get_by_role('button', name='Linked reminder').get_by_text('下次执行').click()
        expect(page.get_by_role('dialog')).to_have_attribute('aria-label', '编辑任务')
        page.get_by_role('dialog').get_by_role('button', name='取消').click()
        tasks[1]['linked_todo_id'] = 'missing-todo'
        page.reload(wait_until='networkidle')
        page.get_by_text('Linked reminder').click()
        expect(page.get_by_role('dialog')).to_contain_text('关联事务不存在或暂时无法读取')
        page.get_by_role('dialog').get_by_role('button', name='取消').click()
        page.get_by_role('button', name='关联事务').click()
        expect(page.get_by_role('dialog')).to_contain_text('关联事务不存在或暂时无法读取')
        assert page.url.endswith('/#/tasks'), page.url
        page.get_by_role('dialog').get_by_role('button', name='取消').click()
        page.get_by_text('Standalone digest').click()
        editor = page.get_by_role('dialog')
        expect(editor).to_contain_text('需要重新选择渠道')
        editor.get_by_role('button', name='需要重新选择渠道').click()
        expect(page.get_by_text('客户端', exact=True)).to_be_visible()
        expect(page.get_by_text('微信', exact=True)).to_have_count(0)
        editor.get_by_role('button', name='取消').click()
        expect(page.get_by_text('沿用绑定对话').first).to_be_visible()
        page.get_by_text('Standalone digest').click()
        editor = page.get_by_role('dialog')
        editor.get_by_role('button', name='沿用绑定对话').click()
        page.get_by_text('完全访问', exact=True).click()
        editor.get_by_role('button', name='保存').click()
        expect(editor).to_be_hidden()
        expect(page.get_by_text('完全访问')).to_be_visible()
        page.get_by_text('Standalone digest').click()
        expect(page.get_by_role('dialog').get_by_role('button', name='完全访问')).to_be_visible()
        page.once('dialog', lambda popup: popup.accept())
        page.get_by_role('dialog').get_by_role('button', name='立即执行').click()
        page.get_by_role('dialog').get_by_role('button', name='取消').click()
        tasks[0]['last_run_status'] = 'failed'
        tasks[0]['last_error'] = '需要审批，任务未执行'
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('需要审批，任务未执行')).to_be_visible()
        expect(page.get_by_text('完全访问')).to_be_visible()
        tasks[1]['linked_todo_id'] = 'todo-1'
        page.reload(wait_until='networkidle')
        page.get_by_role('button', name='关联事务').click()
        expect(page).to_have_url(re.compile(r'/todos$'))
        page.wait_for_load_state('networkidle')
        assert errors == [], errors
        print('Task cards: linked detail and explicit todo navigation passed')
    finally:
        browser.close()
