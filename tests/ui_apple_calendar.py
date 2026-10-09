"""Exercise Apple Calendar settings without opening the real macOS calendar."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
connection = dict(supported=False, authorization='unsupported', connected=False, calendar_ids=[],
                  direction='bidirectional', calendars=[], last_success=None, error='', conflicts=[], pending_deletions=0)
calls = []


def backend(route):
    path = urlparse(route.request.url).path
    body = route.request.post_data_json if route.request.method == 'POST' else {}
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id':'test','configured':True}], capabilities={'chat':{'current_provider':'test','current_model':'test'}})
    elif path == '/api/calendar/events':
        data['events'] = [dict(id='apple-1', title='Apple 课程', description='', location='',
                               start_at='2026-10-12T01:00:00Z', end_at='2026-10-12T02:00:00Z', all_day=0,
                               category_id=None, repeat_frequency='none', repeat_days='[]', repeat_until=None,
                               repeat_timezone='Asia/Shanghai', source_type='apple_calendar', source_key='eventkit:key',
                               source_url='', user_modified=0, created_at='2026-10-10T00:00:00Z',
                               updated_at='2026-10-10T00:00:00Z'),
                          dict(id='apple-day', title='Apple 全天活动', description='', location='',
                               start_at='2026-10-14T16:00:00Z', end_at='2026-10-15T16:00:00Z', all_day=1,
                               category_id=None, repeat_frequency='none', repeat_days='[]', repeat_until=None,
                               repeat_timezone='Asia/Shanghai', source_type='apple_calendar', source_key='eventkit:day',
                               source_url='', user_modified=0, created_at='2026-10-10T00:00:00Z',
                               updated_at='2026-10-10T00:00:00Z')] if connection['connected'] else []
    elif path == '/api/calendar/categories':
        data['categories'] = []
    elif path.startswith('/api/calendar/apple/'):
        calls.append((path, body))
        if path.endswith('/access'):
            connection.update(supported=True, authorization='full_access',
                              calendars=[{'id':'a','title':'私人','source':'iCloud','writable':True},
                                         {'id':'b','title':'课程','source':'本机','writable':False}])
        elif path.endswith('/configure'):
            connection.update(connected=True, calendar_ids=body['calendar_ids'], direction=body['direction'],
                              last_success='2026-10-10T08:00:00Z')
            data['result'] = dict(status='success', imported=2, updated=0, exported=0,
                                  deleted_local=0, deleted_remote=0, conflicts=0, pending_deletions=0, failed_calendar_ids=[])
        elif path.endswith('/sync'):
            if body.get('confirm_deletions'):
                connection['pending_deletions'] = 0
            data['result'] = dict(status='success', imported=0, updated=0, exported=0,
                                  deleted_local=0, deleted_remote=int(bool(body.get('confirm_deletions'))),
                                  conflicts=0, pending_deletions=connection['pending_deletions'], failed_calendar_ids=[])
        elif path.endswith('/resolve'):
            connection['conflicts'] = []
        elif path.endswith('/disconnect'):
            connection['connected'] = False
        data['connection'] = connection
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin':test_url,'Access-Control-Allow-Credentials':'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width':1280,'height':900}, timezone_id='America/Los_Angeles')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/calendar', wait_until='networkidle')
        page.get_by_role('button', name='Apple 日历').click()
        panel = page.get_by_role('dialog', name='Apple 日历')
        expect(panel.get_by_text('此平台不支持 Apple 日历')).to_be_visible()
        connection.update(supported=True, authorization='denied')
        panel.get_by_role('button', name='重新检查').click()
        expect(panel.get_by_text('系统日历权限已拒绝')).to_be_visible()
        panel.get_by_role('button', name='请求日历权限').click()
        panel.get_by_role('checkbox', name='私人').check()
        panel.get_by_role('checkbox', name='课程').check()
        panel.get_by_label('同步方向').select_option('bidirectional')
        panel.get_by_role('button', name='连接并同步').click()
        expect(panel.get_by_text('已连接')).to_be_visible()
        assert next(body for path, body in calls if path.endswith('/configure'))['calendar_ids'] == ['a', 'b']
        panel.get_by_role('button', name='立即同步').click()
        connection['pending_deletions'] = 1
        connection['conflicts'] = [{'stella_id':'event-1','reason':'Both Stella and Apple changed this event'}]
        panel.get_by_role('button', name='重新检查').click()
        panel.get_by_role('button', name='确认删除 Apple 事件').click()
        assert any(body.get('confirm_deletions') for path, body in calls if path.endswith('/sync'))
        panel.get_by_role('button', name='保留 Stella 版本').click()
        assert any(path.endswith('/resolve') for path, _ in calls)
        panel.get_by_role('button', name='关闭').click()
        page.get_by_role('button', name='列表', exact=True).click()
        page.get_by_role('button', name='Apple 课程', exact=False).click()
        expect(page.get_by_text('来自 Apple 日历')).to_be_visible()
        day_section = page.locator('section').filter(has=page.get_by_role('button', name='Apple 全天活动'))
        expect(day_section.get_by_role('heading')).to_contain_text('10月15日')
        day_section.get_by_role('button', name='Apple 全天活动').click()
        day_section.get_by_role('button', name='编辑').click()
        editor = page.get_by_role('dialog')
        editor.locator('input[type="date"]').nth(1).fill('')
        editor.get_by_role('button', name='保存').click()
        expect(editor.get_by_role('alert')).to_be_visible()
        editor.get_by_role('button', name='Close').click()
        page.get_by_role('button', name='Apple 日历').click()
        panel.get_by_role('button', name='断开连接').click()
        expect(panel.get_by_text('未连接')).to_be_visible()
        assert errors == [], errors
        print('Apple Calendar UI: unsupported, permission, connect, sync, conflict and disconnect passed')
    finally:
        browser.close()
