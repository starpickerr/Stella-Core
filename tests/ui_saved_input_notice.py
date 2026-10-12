"""Check dismissal persistence and date-based briefing updates in one browser."""
import json
import os
from datetime import date
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
pending = [dict(run_id='uncertain-1', status='outcome_unknown', clear_history=False,
                user_content=[dict(type='text', text='更新简报')])]
mutations = []
briefing = dict(id='brf-' + date.today().isoformat(), title='今日简报', status='completed',
                body='', fetched_count=0, kept_count=0, filtered_count=0, error_message='',
                generated_at='2026-10-12T08:00:00Z', source_windows={}, updated_sources=[],
                rule_text='', mail_snapshot_available=True, window_start=None, window_end=None)
detail = dict(briefing=briefing, items=[], mail=[], revisions=[], actions={}, preferences={})


def backend(route):
    path = urlparse(route.request.url).path
    body = route.request.post_data_json if route.request.method == 'POST' else None
    if body is not None and path != '/poll':
        mutations.append((path, body))
    data = dict(status='success', sessions=[], projects=[], messages=[], skills=[], tasks=[],
                agents=[], admissions=[], page=1, has_more=False, total=0)
    if path == '/api/health':
        data['status'] = 'ok'
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[dict(id='test', configured=True)],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/history':
        data['pending_admissions'] = pending
    elif path == '/api/briefings':
        assert 'kind' not in route.request.url
        data['briefings'] = [briefing]
    elif path in ('/api/briefings/' + briefing['id'], '/api/briefings/run'):
        data.update(detail)
    elif path == '/api/briefings/overview':
        data.update(items=[], actions={}, preferences={})
    elif path == '/api/briefings/sources':
        data['sources'] = [dict(id='email:test', source='email', account_id='test', name='测试邮箱')]
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 980, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');
            localStorage.setItem('cow_session_id','notice-test');
            window.electronAPI = {getBackendPort: async () => 9876,
                onBackendStatus: () => () => {}, getBackendError: async () => null};""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/', wait_until='networkidle')
        close = page.get_by_role('button', name='关闭已保存输入提示')
        expect(close).to_be_visible()
        expect(page.get_by_text('更新简报', exact=True)).to_be_visible()
        close.focus()
        page.keyboard.press('Enter')
        expect(close).to_have_count(0)
        page.reload(wait_until='networkidle')
        expect(close).to_have_count(0)
        assert pending[0]['status'] == 'outcome_unknown'
        assert not mutations, mutations
        pending.append(dict(run_id='uncertain-2', status='queued', clear_history=False,
                            user_content=[dict(type='text', text='新的保存输入')]))
        page.reload(wait_until='networkidle')
        expect(close).to_be_visible()
        expect(page.get_by_text('新的保存输入', exact=True)).to_be_visible()
        expect(page.get_by_text('更新简报', exact=True)).to_have_count(0)
        page.goto(url + '/#/briefing', wait_until='networkidle')
        update = page.get_by_role('button', name='更新今日简报', exact=True)
        expect(update).to_be_enabled()
        update.click()
        expect(update).to_be_enabled()
        runs = [body for path, body in mutations if path == '/api/briefings/run']
        assert len(runs) == 1 and runs[0]['operation'] == 'update' and 'kind' not in runs[0], runs
        assert not errors, errors
        print('PASS: notice closes by keyboard, stays hidden after reload, new inputs remain visible; neutral briefing updates once')
    finally:
        browser.close()
