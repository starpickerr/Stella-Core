"""Check notification route editors against an isolated desktop API."""

import json
import os
from datetime import date, timedelta
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://localhost:5173')
requests = []
weixin_ready = [False]
todo = dict(id='todo-1', title='交作业', status='todo', series_id=None, parent_id=None,
            sort_order=0, notes='', due_on=(date.today() + timedelta(days=1)).isoformat(),
            due_time=None, timezone='Asia/Shanghai', priority=0, repeat_frequency='none',
            repeat_days='[]', repeat_until=None, planned_on=None, list_name='', tags='[]',
            flagged=0, checklist='[]', remind_at=(date.today() + timedelta(days=1)).isoformat() + 'T06:00:00Z',
            scheduler_task_id=None, reminder_sync_pending=False, reminder_delivery={
                'primary': None, 'backup_enabled': False, 'backup': None},
            reminder_delivery_status={'status': 'waiting', 'error': 'session expired'}, blocked_by=[], dependency_ids=[], subtask_count=0,
            progress_completed=0, progress_total=0, progress_percent=0, created_at='2026-10-01T00:00:00Z')
task = dict(id='task-1', name='邮件简报', enabled=True, created_at='', updated_at='',
            schedule={'type': 'cron', 'expression': '0 8 * * *'},
            action={'type': 'send_message', 'content': '简报', 'channel_type': 'web', 'receiver': 'session-1'},
            next_run_at='2026-10-10T08:00:00Z')


def backend(route):
    path = urlparse(route.request.url).path
    body = route.request.post_data_json if route.request.method == 'POST' else {}
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}], capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/scheduler':
        data['tasks'] = [task]
    elif path == '/api/scheduler/destinations':
        data['destinations'] = [
            dict(channel_type='web', configured=True, ready=True, status='ready', recipients=[{'receiver': 'session-1', 'name': 'Current chat'}]),
            dict(channel_type='feishu', configured=True, ready=True, status='ready', recipients=[]),
            dict(channel_type='weixin', configured=True, ready=weixin_ready[0],
                 status='ready' if weixin_ready[0] else 'no_recipient',
                 recipients=[{'receiver': 'wx-user', 'name': 'wx-user'}] if weixin_ready[0] else []),
        ]
    elif path == '/api/scheduler/test-delivery':
        requests.append((path, body))
        data['delivery_status'] = 'accepted'
    elif path == '/api/scheduler/update':
        requests.append((path, body))
        task.update({key: value for key, value in body.items() if key != 'task_id'})
        data['task'] = task
    elif path == '/api/todos':
        data['todos'] = [todo]
    elif path == '/api/todos/reminders/uncertain':
        data['reminders'] = []
    elif path == '/api/todos/update':
        requests.append((path, body))
        todo.update({key: value for key, value in body.items() if key != 'id'})
        data['todo'] = todo
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)

        page.goto(test_url + '/#/tasks', wait_until='networkidle')
        page.get_by_text('邮件简报').click()
        modal = page.get_by_role('dialog')
        expect(modal.get_by_text('备用渠道（可选）')).to_be_visible()
        modal.get_by_role('button', name='客户端').click()
        page.get_by_text('飞书', exact=True).click()
        modal.locator('input[list="task-recipients"]').fill('ou_primary')
        modal.get_by_role('button', name='测试发送至首选渠道').click()
        expect(modal.get_by_text('平台已接受', exact=False)).to_be_visible()
        assert requests[-1][1]['notification_route']['backup_enabled'] is False
        modal.get_by_role('button', name='保存').click()
        assert requests[-1][1]['notification_route']['primary']['receiver'] == 'ou_primary'
        assert requests[-1][1]['notification_route']['backup_enabled'] is False
        page.get_by_text('邮件简报').click()
        modal = page.get_by_role('dialog')
        modal.get_by_role('switch').nth(1).click()
        modal.get_by_text('备用渠道', exact=True).locator('..').get_by_role('button').click()
        page.get_by_text('微信', exact=True).click()
        modal.locator('input[list="task-backup-recipients"]').fill('wx-user')
        modal.get_by_role('button', name='保存').click()
        assert requests[-1][1]['notification_route']['backup_enabled'] is True
        assert requests[-1][1]['notification_route']['backup']['receiver'] == 'wx-user'
        page.get_by_text('邮件简报').click()
        modal = page.get_by_role('dialog')
        modal.get_by_role('switch').nth(1).click()
        modal.get_by_role('button', name='保存').click()
        assert requests[-1][1]['notification_route']['backup_enabled'] is False
        assert requests[-1][1]['notification_route']['backup'] is None

        page.goto(test_url + '/#/todos', wait_until='networkidle')
        page.get_by_text('交作业', exact=True).click()
        page.get_by_role('button', name='编辑详情').click()
        editor = page.get_by_role('region', name='事务详情')
        expect(editor.get_by_label('提醒渠道')).to_be_visible()
        expect(editor.get_by_text('最近投递: waiting · session expired')).to_be_visible()
        editor.get_by_label('提醒渠道').select_option('weixin')
        expect(editor.get_by_role('option', name='weixin · no_recipient')).to_have_count(1)
        expect(editor.get_by_text('微信发送需要有效会话', exact=False)).to_be_visible()
        editor.get_by_label('接收人', exact=True).fill('wx-user')
        assert not editor.get_by_label('备用渠道（可选）').is_checked()
        weixin_ready[0] = True
        editor.get_by_role('button', name='刷新渠道').click()
        expect(editor.get_by_role('option', name='weixin · ready')).to_have_count(1)
        editor.get_by_role('button', name='测试发送至首选渠道').click()
        expect(editor.get_by_text('测试消息已被平台接受')).to_be_visible()
        editor.get_by_role('button', name='保存修改').click()
        assert requests[-1][1]['reminder_delivery']['primary']['channel_type'] == 'weixin'
        assert requests[-1][1]['reminder_delivery']['backup_enabled'] is False
        assert errors == [], errors
        print('Notification UI: task and todo routes, optional backup, refresh, test send passed')
    finally:
        browser.close()
