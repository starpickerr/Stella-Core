"""Subtask rows in the focus view show a deadline only when one is set."""
import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')


def todo(**overrides):
    row = dict(
        id='parent', title='作业', notes='', status='todo', parent_id=None, sort_order=0,
        remind_at=None, scheduler_task_id=None, reminder_sync_pending=False, reminder_sync_error='',
        subtask_count=0, progress_completed=0, progress_total=0, progress_percent=0,
        dependency_ids=[], blocked_by=[], due_on=None, due_time=None, timezone='Asia/Shanghai',
        priority=0, completed_at=None, repeat_frequency='none', repeat_days='[]', repeat_until=None,
        planned_on=None, list_name='', tags='[]', flagged=0, checklist='[]', source_type=None,
        source_key=None, source_url='', user_modified=0, briefing_id=None, created_at='', updated_at='',
    )
    row.update(overrides)
    return row


todos = [
    todo(id='parent', title='作业', subtask_count=2, progress_total=2),
    todo(id='timed', title='有截止的步骤', parent_id='parent', sort_order=0,
         due_on='2026-10-29', due_time='18:00'),
    todo(id='open', title='没有截止的步骤', parent_id='parent', sort_order=1),
    todo(id='leaf', title='更深层步骤', parent_id='timed', sort_order=0,
         due_on='2026-11-02', due_time='09:30'),
]
todos[1]['subtask_count'] = 1
todos[1]['progress_total'] = 1


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/todos':
        data['todos'] = todos
    elif path == '/api/todos/reminders/uncertain':
        data['reminders'] = []
    else:
        data.update(sessions=[], projects=[], messages=[], skills=[], tasks=[], agents=[], admissions=[])
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
        page.goto(test_url + '/#/todos', wait_until='networkidle')
        expect(page.get_by_text('作业', exact=True)).to_be_visible()
        page.get_by_text('作业', exact=True).click()
        expect(page.get_by_role('button', name='有截止的步骤', exact=True)).to_be_visible()
        timed = page.get_by_role('button', name='有截止的步骤', exact=True).locator('xpath=..')
        expect(timed).to_contain_text('2026-10-29 18:00')
        open_row = page.get_by_role('button', name='没有截止的步骤', exact=True).locator('xpath=..')
        expect(open_row).not_to_contain_text('2026-')
        page.get_by_role('button', name='有截止的步骤', exact=True).click()
        nested = page.get_by_role('button', name='更深层步骤', exact=True).locator('xpath=..')
        expect(nested).to_contain_text('2026-11-02 09:30')
        assert errors == [], errors
        print('Todo focus: subtask deadlines passed')
    finally:
        browser.close()
