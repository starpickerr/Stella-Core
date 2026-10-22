"""Data pages explain sources, functional usage and real storage locations."""
import json
import os
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright

url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5184')
sources = [
    dict(id='school', name='eLearning', provider='elearning', kind='elearning', enabled=True, available=True,
         representation='reference', operations=['resources', 'read'], resource_kinds=['course', 'announcement', 'assignment', 'file'],
         settings_url='/elearning', connection='mcp:elearning', storage='reference', retention_days=30, running=False, last_run=None, error=''),
    dict(id='mail', name='收件箱', provider='email', kind='email', enabled=True, available=True,
         representation='collection', operations=['resources', 'read', 'sync', 'export', 'delete'], resource_kinds=['email'],
         settings_url='/email', connection='mcp:email', storage='persistent', retention_days=30, running=False, last_run=None, error=''),
    dict(id='notes', name='Knowledge', provider='knowledge', kind='knowledge', enabled=True, available=False,
         representation='reference', operations=['resources', 'read'], resource_kinds=['knowledge'],
         settings_url='/knowledge', connection='plugin:stella.knowledge', storage='reference', retention_days=30, running=False, last_run=None, error=''),
]
usages = [dict(consumer_id='stella.briefing', source_id=source, enabled=True, selected=True) for source in ['school', 'mail']]
commands, queries = [], []
fail_save = [False]
fail_read = [False]
hold_save = [False]
deferred = []


def backend(route):
    parsed = urlparse(route.request.url)
    path, query = parsed.path, parse_qs(parsed.query)
    data = {'status': 'success'}
    if path == '/api/health':
        data['status'] = 'ok'
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}], capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/data':
        data.update(sources=sources, usages=usages,
            usage_consumers=[{'id': 'stella.briefing', 'name': {'zh': '简报', 'en': 'Briefing'}, 'available': True}],
            providers=[], record_count=1, subscriptions=[], consumers=[], deliveries=[], errors=[],
            storage={'available': True, 'categories': [
                {'id': 'data_service', 'name': {'zh': '来源数据与同步状态', 'en': 'Source data'}, 'path': '/isolated/data/data.db', 'bytes': 4096,
                 'retention': {'zh': '由信息源策略管理', 'en': 'Managed by source policy'}, 'actions': []},
                {'id': 'temporary', 'name': {'zh': '临时文件', 'en': 'Temporary files'}, 'path': '/isolated/tmp', 'bytes': 0,
                 'retention': {'zh': '可以清理', 'en': 'Can be cleared'}, 'actions': ['clear_temporary']} ]})
        if query.get('storage') == ['0']:
            data['storage']['categories'] = []
    elif path == '/api/data/command':
        body = route.request.post_data_json
        commands.append(body)
        if fail_save[0]:
            data.update(status='error', message='保存失败，请重试')
        elif body['action'] == 'usage':
            row = next(row for row in usages if row['source_id'] == body['source_id'])
            row.update(enabled=body['enabled'], selected=body.get('selected', True))
            data['usage'] = row
        elif body['action'] == 'sync':
            data['sync'] = {'processed': 1, 'errors': []}
        elif body['action'] == 'export':
            data['export'] = {'format': 'stella-data-v1', 'source_id': 'mail', 'records': []}
        elif body['action'] in ('delete_record', 'cleanup', 'cleanup_storage'):
            data['removed'] = 1
        elif body['action'] == 'source':
            next(row for row in sources if row['id'] == body['source_id']).update({key: value for key, value in body.items() if key not in ('action', 'source_id')})
    elif path == '/api/data/resources':
        queries.append(query)
        resource = {'id': 'ref', 'source_id': query['source_id'][0], 'provider': 'elearning', 'reference': 'upstream', 'kind': 'file', 'name': '课程文件', 'operations': ['read']}
        if fail_read[0]:
            data.update(status='error', message='访问已撤销')
        elif 'resource_id' in query:
            data.update(resource=resource, content='按需读取的资源正文')
        else:
            data.update(resources=[resource], total=1, offset=0, limit=50)
    if path == '/api/data/command' and hold_save[0]:
        deferred.append((route, data))
        return
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 960})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');window.electronAPI={platform:'darwin',getBackendPort:async()=>9876,onBackendStatus:()=>()=>{},getBackendError:async()=>null};""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/data', wait_until='networkidle')
        tabs = page.get_by_role('navigation', name='数据分类')
        expect(tabs.get_by_role('button')).to_have_text(['总览', '信息源', '数据使用', '数据存储'])
        expect(page.get_by_role('heading', name='总览', exact=True)).to_be_visible()
        expect(page.get_by_label('Agent 范围', exact=True)).to_have_count(0)
        expect(page.get_by_label('工作区范围', exact=True)).to_have_count(0)
        page.screenshot(path='/tmp/stella-data-overview.png', full_page=True)
        tabs.get_by_role('button', name='信息源', exact=True).click()
        expect(page.get_by_test_id('data-source-school')).to_contain_text('可用')
        expect(page.get_by_test_id('data-source-notes')).to_contain_text('暂不可用')
        expect(page.locator('[data-testid^="data-source-"]')).to_have_count(3)
        page.screenshot(path='/tmp/stella-data-sources.png', full_page=True)
        tabs.get_by_role('button', name='数据使用', exact=True).click()
        briefing = page.get_by_test_id('data-consumer-stella.briefing')
        expect(briefing.get_by_role('heading', name='简报', exact=True)).to_be_visible()
        use_school = briefing.get_by_role('switch', name='简报使用eLearning', exact=True)
        expect(use_school).to_be_checked()
        expect(page.get_by_role('button', name='添加订阅', exact=True)).to_have_count(0)
        fail_save[0] = True
        use_school.click()
        expect(page.get_by_role('alert')).to_contain_text('保存失败')
        expect(use_school).to_be_checked()
        fail_save[0] = False
        use_school.click()
        expect(use_school).not_to_be_checked()
        assert sources[0]['enabled'] is True
        page.reload(wait_until='networkidle')
        expect(use_school).not_to_be_checked()
        briefing.get_by_role('button', name='移除简报使用的收件箱', exact=True).click()
        expect(briefing.get_by_role('switch', name='简报使用收件箱', exact=True)).to_have_count(0)
        briefing.get_by_role('button', name='添加信息源', exact=True).click()
        briefing.get_by_label('为简报选择信息源', exact=True).select_option('mail')
        briefing.get_by_role('button', name='添加', exact=True).click()
        expect(briefing.get_by_role('switch', name='简报使用收件箱', exact=True)).to_be_checked()
        use_school.click()
        expect(use_school).to_be_checked()
        page.screenshot(path='/tmp/stella-data-usage.png', full_page=True)
        page.set_viewport_size({'width': 620, 'height': 960})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path='/tmp/stella-data-usage-narrow.png', full_page=True)
        hold_save[0] = True
        use_school.click()
        tabs.get_by_role('button', name='数据存储', exact=True).click()
        expect(page.get_by_text('/isolated/data/data.db', exact=True)).to_be_visible()
        page.screenshot(path='/tmp/stella-data-storage.png', full_page=True)
        hold_save[0] = False
        pending, payload = deferred.pop()
        pending.fulfill(status=200, content_type='application/json', body=json.dumps(payload), headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})
        expect(page.get_by_role('button', name='刷新', exact=True)).to_be_enabled()
        expect(page.get_by_text('/isolated/data/data.db', exact=True)).to_be_visible()
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='清理临时文件', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='已清理')).to_be_visible()
        tabs.get_by_role('button', name='信息源', exact=True).click()
        page.get_by_test_id('data-source-school').get_by_role('link', name='浏览资源', exact=True).click()
        expect(page.get_by_role('heading', name='eLearning', exact=True)).to_be_visible()
        page.get_by_label('资源类型', exact=True).select_option('file')
        expect(page.get_by_text('课程文件', exact=True)).to_be_visible()
        assert queries[-1]['kind'] == ['file']
        page.get_by_role('button', name='查看内容', exact=True).click()
        expect(page.get_by_text('按需读取的资源正文', exact=True)).to_be_visible()
        fail_read[0] = True
        page.get_by_role('button', name='刷新资源', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('访问已撤销')
        expect(page.get_by_text('按需读取的资源正文', exact=True)).to_have_count(0)
        fail_read[0] = False
        page.goto(url + '/#/data?section=sync', wait_until='networkidle')
        expect(tabs.get_by_role('button', name='数据使用', exact=True)).to_have_attribute('aria-current', 'page')
        page.goto(url + '/#/data?section=storage', wait_until='networkidle')
        expect(tabs.get_by_role('button', name='数据存储', exact=True)).to_have_attribute('aria-current', 'page')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='收起侧栏', exact=True).click()
        tabs.get_by_role('button', name='数据使用', exact=True).click()
        use_school.focus()
        expect(use_school).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path='/tmp/stella-data-usage-mobile.png', full_page=True)
        assert errors == [], errors
        print('PASS: Data overview, registered sources, feature usage persistence/add/remove/failure, storage, resource detail and desktop/narrow layouts')
    finally:
        browser.close()
