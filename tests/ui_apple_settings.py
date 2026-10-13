"""Verify Apple category mapping settings against an isolated HTTP backend."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
calls = []
reject_preview = [False]
connections = {
    'calendar': dict(supported=True, authorization='full_access', connected=False,
                     auto_enabled=True, calendar_ids=[], direction='bidirectional', links=[],
                     calendars=[dict(id='cal-a', title='私人', source='iCloud', writable=True)],
                     last_success=None, error='', conflicts=[], pending_deletions=0,
                     pending_local_deletions=0),
    'todos': dict(supported=True, authorization='full_access', connected=False,
                  auto_enabled=True, list_ids=[], direction='bidirectional', links=[],
                  lists=[dict(id='list-a', title='个人', source='iCloud', writable=True)],
                  last_success=None, error='', conflicts=[], pending_deletions=0,
                  pending_local_deletions=0),
}
categories = {
    'calendar': [dict(id='personal', name='个人', color='#55B89A', created_at='2026-01-01T00:00:00Z')],
    'todos': [dict(id='life', name='生活', color='#6B8AF7', created_at='2026-01-01T00:00:00Z')],
}


def backend(route):
    path = urlparse(route.request.url).path
    body = route.request.post_data_json if route.request.method == 'POST' else {}
    calls.append((path, body))
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/calendar/categories':
        data = {'status': 'success', 'categories': categories['calendar']}
    elif path == '/api/todos/categories':
        data = {'status': 'success', 'categories': categories['todos']}
    elif path.startswith('/api/calendar/apple/') or path.startswith('/api/todos/apple/'):
        kind = 'calendar' if '/calendar/' in path else 'todos'
        state = connections[kind]
        if path.endswith('/auto'):
            state['auto_enabled'] = body['enabled']
        elif path.endswith('/links-preview'):
            data = {'preview_token': f'{kind}-links', 'status': 'success'}
        elif path.endswith('/links'):
            if reject_preview[0]:
                reject_preview[0] = False
                data = {'status': 'error', 'message': 'Apple sync inventory changed; preview again'}
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                              headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})
                return
            assert body['confirm'] and body['preview_token'] == f'{kind}-links'
            assert 'item_ids' not in body
            state.update(connected=True, links=body['links'])
            data['result'] = {'status': 'success', 'imported': 1, 'updated': 0, 'exported': 0}
        elif path.endswith('/batch-preview'):
            assert body['selections'] and 'item_ids' not in body
            data.update(preview={'new': 3, 'skipped': 0, 'failed': 0}, preview_token=f'{kind}-batch')
        elif path.endswith('/batch'):
            assert body['confirm'] and body['preview_token'] == f'{kind}-batch'
            assert 'item_ids' not in body
            data['result'] = {'status': 'success', 'imported': 3, 'updated': 0, 'exported': 0}
        elif path.endswith('/disconnect'):
            state['connected'] = False
        elif path.endswith('/sync'):
            data['result'] = {'status': 'success', 'imported': 0, 'updated': 0, 'exported': 0}
        data['connection'] = state
    elif path == '/api/calendar/events':
        data['events'] = []
    elif path == '/api/todos':
        data['todos'] = []
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, timezone_id='Asia/Shanghai')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {platform: 'darwin',
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/settings?tab=integrations&section=apple-calendar', wait_until='networkidle')
        expect(page.get_by_role('navigation', name='设置分类').get_by_role('button', name='连接', exact=True)).to_be_visible()
        calendar = page.get_by_role('region', name='Apple 日历')
        reminders = page.get_by_role('region', name='Apple 提醒事项')
        expect(calendar).to_be_visible()
        expect(reminders).to_be_visible()
        expect(calendar.get_by_role('checkbox', name='读书会')).to_have_count(0)
        calendar.get_by_role('button', name='添加映射').click()
        calendar.get_by_label('Apple 日历 1').select_option('cal-a')
        calendar.get_by_label('Stella 分类 1').select_option('personal')
        calendar.get_by_label('内容方向 1').select_option('import')
        calendar.get_by_role('button', name='预览同步').click()
        reject_preview[0] = True
        calendar.get_by_role('button', name='确认连接并同步').click()
        expect(calendar.get_by_role('alert')).to_contain_text('preview again')
        calendar.get_by_role('button', name='预览同步').click()
        calendar.get_by_role('button', name='确认连接并同步').click()
        saved = next(body for path, body in calls if path == '/api/calendar/apple/links')
        assert saved['links'][0]['apple_id'] == 'cal-a'
        assert saved['links'][0]['stella_id'] == 'personal'
        assert saved['links'][0]['direction'] == 'import'
        assert 'item_ids' not in saved
        reminders.get_by_role('checkbox', name='自动同步').uncheck()
        assert connections['todos']['auto_enabled'] is False
        reminders.get_by_role('button', name='一次性导入').click()
        reminders.get_by_label('来源分类').select_option('list-a')
        reminders.get_by_label('目标分类').select_option('life')
        expect(reminders.get_by_label('包含无日期事务')).to_be_visible()
        reminders.get_by_role('button', name='预计导入').click()
        expect(reminders.get_by_text('预计导入 3 条')).to_be_visible()
        reminders.get_by_role('button', name='开始导入').click()
        batch = next(body for path, body in calls if path == '/api/todos/apple/batch')
        assert batch['selections'] == [{'apple_id': 'list-a', 'stella_id': 'life'}]
        assert 'item_ids' not in batch
        assert connections['todos']['connected'] is False
        calendar.get_by_role('button', name='一次性导入').click()
        year = page.evaluate('new Date().getFullYear()')
        assert calendar.get_by_label('开始日期').input_value() == f'{year}-01-01'
        assert calendar.get_by_label('结束日期').input_value() == f'{year + 1}-01-01'
        reminders.get_by_role('button', name='添加映射').click()
        reminders.get_by_label('Apple 列表 1').select_option('list-a')
        reminders.get_by_label('Stella 分类 1').select_option('life')
        reminders.get_by_role('button', name='预览同步').click()
        reminders.get_by_role('button', name='确认连接并同步').click()
        assert connections['todos']['connected'] and not connections['todos']['auto_enabled']
        reminders.get_by_role('button', name='断开连接').click()
        expect(reminders.get_by_text('未连接', exact=False)).to_be_visible()
        assert connections['todos']['connected'] is False
        assert errors == [], errors
        print('Apple settings UI: category mapping and batch transfer passed')
    finally:
        browser.close()
