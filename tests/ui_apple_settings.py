"""Verify the unified Apple settings workflow against an isolated HTTP backend."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
calls = []
reject_preview = [False]
connections = {
    'calendar': dict(supported=True, authorization='full_access', connected=False,
                     auto_enabled=True, calendar_ids=[], direction='bidirectional',
                     calendars=[dict(id='cal-a', title='私人', source='iCloud', writable=True)],
                     last_success=None, error='', conflicts=[], pending_deletions=0,
                     pending_local_deletions=0),
    'todos': dict(supported=True, authorization='full_access', connected=False,
                  auto_enabled=True, list_ids=[], direction='bidirectional',
                  lists=[dict(id='list-a', title='个人', source='iCloud', writable=True)],
                  last_success=None, error='', conflicts=[], pending_deletions=0,
                  pending_local_deletions=0),
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
    elif path.startswith('/api/calendar/apple/') or path.startswith('/api/todos/apple/'):
        kind = 'calendar' if '/calendar/' in path else 'todos'
        state = connections[kind]
        if path.endswith('/auto'):
            state['auto_enabled'] = body['enabled']
        elif path.endswith('/scope-preview') or path.endswith('/preview'):
            data.update(preview={'new': 1, 'updated': 0, 'skipped': 0, 'conflicts': 0},
                        preview_token=f'{kind}-preview')
        elif path.endswith('/configure'):
            if reject_preview[0]:
                reject_preview[0] = False
                data = {'status': 'error', 'message': 'Apple sync inventory changed; preview again'}
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                              headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})
                return
            assert body['confirm'] and body['preview_token'] == f'{kind}-preview'
            state.update(connected=True, direction=body['direction'])
            state['calendar_ids' if kind == 'calendar' else 'list_ids'] = body[
                'calendar_ids' if kind == 'calendar' else 'list_ids']
            data['result'] = {'status': 'success', 'imported': 1, 'updated': 0, 'exported': 0}
        elif path.endswith('/items'):
            data['items'] = [dict(event_id='event-1', title='读书会', calendar_id='cal-a')] if kind == 'calendar' else [
                dict(reminder_id='rem-1', title='读书', list_id='list-a')]
        elif path.endswith('/one-time'):
            assert body['confirm'] and body['preview_token'] == f'{kind}-preview'
            data['result'] = {'status': 'success', 'imported': 1, 'updated': 0, 'exported': 0}
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
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/settings?tab=integrations&section=apple-calendar', wait_until='networkidle')
        expect(page.get_by_role('button', name='集成与连接')).to_be_visible()
        calendar = page.get_by_role('region', name='Apple 日历')
        reminders = page.get_by_role('region', name='Apple 提醒事项')
        expect(calendar).to_be_visible()
        expect(reminders).to_be_visible()
        calendar.get_by_role('checkbox', name='私人').check()
        calendar.get_by_role('button', name='预览同步').click()
        expect(calendar.get_by_text('新增 1')).to_be_visible()
        calendar.get_by_role('checkbox', name='私人').uncheck()
        expect(calendar.get_by_role('button', name='确认连接并同步')).to_have_count(0)
        calendar.get_by_role('checkbox', name='私人').check()
        calendar.get_by_role('button', name='预览同步').click()
        reject_preview[0] = True
        calendar.get_by_role('button', name='确认连接并同步').click()
        expect(calendar.get_by_role('alert')).to_contain_text('preview again')
        calendar.get_by_role('button', name='预览同步').click()
        calendar.get_by_role('button', name='确认连接并同步').click()
        assert any(path.endswith('/configure') and body.get('preview_token') == 'calendar-preview'
                   for path, body in calls)
        reminders.get_by_role('checkbox', name='自动同步').uncheck()
        assert connections['todos']['auto_enabled'] is False
        reminders.get_by_role('checkbox', name='个人').check()
        reminders.get_by_role('button', name='一次性导入').click()
        reminders.get_by_label('一次性列表').select_option('list-a')
        reminders.get_by_role('button', name='载入条目').click()
        reminders.get_by_role('checkbox', name='读书').check()
        reminders.get_by_role('button', name='预览导入').click()
        reminders.get_by_role('button', name='确认一次性导入').click()
        assert any(path.endswith('/one-time') and body.get('item_ids') == ['rem-1']
                   for path, body in calls)
        assert connections['todos']['connected'] is False
        calendar.get_by_role('button', name='一次性导入').click()
        calendar.get_by_label('一次性日历').select_option('cal-a')
        calendar.get_by_role('button', name='载入条目').click()
        calendar.get_by_role('checkbox', name='读书会').check()
        calendar.get_by_role('button', name='预览导入').click()
        calendar.get_by_role('button', name='确认一次性导入').click()
        inventory = next(body for path, body in calls if path == '/api/calendar/apple/items')
        assert inventory['calendar_id'] == 'cal-a' and inventory['start'] and inventory['end']
        reminders.get_by_role('button', name='预览同步').click()
        reminders.get_by_role('button', name='确认连接并同步').click()
        assert connections['todos']['connected'] and not connections['todos']['auto_enabled']
        reminders.get_by_role('button', name='断开连接').click()
        expect(reminders.get_by_text('未连接', exact=False)).to_be_visible()
        assert connections['todos']['connected'] is False
        assert errors == [], errors
        print('Apple settings UI: deep link, independent auto, scope and one-time transfer passed')
    finally:
        browser.close()
