"""Real React interactions with transport fixtures; backend policy is tested separately."""
import json
import re
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[1]


def test_settings_retains_drafts_reports_conflict_and_approves_independently(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    process = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'],
        cwd=REPO / 'desktop', stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(origin, timeout=.2).close()
                break
            except OSError:
                time.sleep(.05)
        else:
            raise AssertionError('Vite did not start')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1080, 'height': 900})
            page.set_default_timeout(5000)
            errors, calls, grants = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('cow_auth_token', 'test-token'); localStorage.setItem('stella_lang', 'zh')")
            fields = [{'key': 'name', 'title': '名称', 'category': 'general', 'type': 'string'},
                      {'key': 'other', 'title': '其他', 'category': 'other', 'type': 'string'}]
            descriptor = {'id': 'preferences', 'categories': [{'id': 'general', 'title': '常规'}, {'id': 'other', 'title': '其他类别'}], 'fields': fields}
            conflict = [True]

            def handle(route):
                request = route.request
                body = request.post_data_json if request.method == 'POST' else {}
                assert request.headers.get('authorization') == 'Bearer test-token'
                calls.append((request.url, body))
                result = None
                status = 'ok'
                if request.url.endswith('/runtime'):
                    route.fulfill(json={'status': 'ok', 'plugins': [{'pluginId': 'stella.bills', 'userId': 'alice', 'name': '账单', 'version': '1.0.1', 'intent': 'enabled', 'state': 'stopped'}]})
                    return
                if '/settings' in request.url:
                    if body['action'] == 'describe':
                        result = [descriptor]
                    elif body['action'] == 'read':
                        result = {'revision': 2 if not conflict[0] else 1, 'values': {}, 'secretFields': []}
                    elif body['action'] == 'save':
                        if conflict[0]:
                            conflict[0] = False
                            status = 'conflict'
                        else:
                            result = {'revision': 3, 'values': body['changes'], 'secretFields': []}
                elif '/authorization' in request.url:
                    action = body['action']
                    if action == 'describe':
                        result = [{'methods': [{'name': 'list_ledger', 'permissions': ['bills.read']}]}]
                    elif action == 'list':
                        result = grants
                    elif action == 'request':
                        result = {'requestId': 'r1', **body['spec']}
                    elif action == 'approve':
                        grants.append({'grantId': 'g1', 'consumerPluginId': 'stella.bills', 'capability': 'bills.read', 'purpose': 'interactive', 'resources': [{'kind': 'user', 'id': 'alice'}], 'methods': ['list_ledger'], 'revoked': False})
                        result = grants[-1]
                    elif action == 'revoke':
                        grants[0]['revoked'] = True
                route.fulfill(json={'status': status, 'result': result, 'message': '设置已变化' if status == 'conflict' else ''})

            page.route('**/api/plugins/**', handle)
            compiled = urllib.request.urlopen(origin + '/src/main.tsx').read().decode()
            react_url = re.search(r'from "([^"]*/deps/react\.js(?:\?[^"]*)?)"', compiled).group(1)
            dom_url = re.search(r'from "([^"]*/deps/react-dom_client\.js(?:\?[^"]*)?)"', compiled).group(1)
            router_source = urllib.request.urlopen(origin + '/src/App.tsx').read().decode()
            router_url = re.search(r'from "([^"]*/deps/react-router-dom\.js(?:\?[^"]*)?)"', router_source).group(1)
            html = '''<!doctype html><html><body><div id="root" style="max-width:800px;margin:24px auto"></div>
<script type="module">
import '/@vite/client';
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>(type)=>type; window.__vite_plugin_react_preamble_installed__=true;
const React = (await import('REACT_URL')).default;
const ReactDOM = (await import('DOM_URL')).default;
const Settings = (await import('/src/pages/settings/PluginSettings.tsx')).default;
const {MemoryRouter} = await import('ROUTER_URL');
await import('/src/index.css');
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(MemoryRouter, null, React.createElement(Settings, {baseUrl: window.location.origin})));
</script></body></html>'''.replace('REACT_URL', react_url).replace('DOM_URL', dom_url).replace('ROUTER_URL', router_url)
            page.route('**/plugin-test', lambda route: route.fulfill(body=html, content_type='text/html'))
            page.goto(origin + '/plugin-test')
            page.wait_for_load_state('networkidle')
            assert not errors, errors
            page.get_by_role('radio', name='授权', exact=True).click()
            expect(page.get_by_role('button', name='审阅授权范围')).to_be_visible()
            page.get_by_role('radio', name='常规').click()
            page.get_by_label('名称').fill('保留草稿')
            page.get_by_role('radio', name='其他类别').click()
            page.get_by_label('其他', exact=True).fill('另一类别')
            page.get_by_role('radio', name='常规').click()
            expect(page.get_by_label('名称')).to_have_value('保留草稿')
            page.get_by_role('button', name='保存本类别').click()
            expect(page.get_by_role('alert')).to_contain_text('草稿已保留')
            page.get_by_role('button', name='读取最新版本并保留修改').click()
            expect(page.get_by_label('名称')).to_have_value('保留草稿')
            page.get_by_role('button', name='保存本类别').click()
            expect(page.get_by_role('status')).to_have_text('本类别已保存')
            page.get_by_role('radio', name='授权', exact=True).click()
            page.get_by_role('button', name='审阅授权范围').click()
            expect(page.get_by_role('dialog')).to_be_visible()
            expect(page.get_by_role('dialog')).to_contain_text('user: alice')
            page.get_by_role('button', name='批准并立即生效').click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            expect(page.get_by_role('status')).to_contain_text('来源选用保持原来的设置')
            page.get_by_role('button', name='撤销', exact=True).click()
            expect(page.get_by_role('button', name='已撤销')).to_be_disabled()
            page.screenshot(path=str(tmp_path / 'settings-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(tmp_path / 'settings-narrow.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            saves = [body for _, body in calls if body.get('action') == 'save']
            assert [body['expectedRevision'] for body in saves] == [1, 2]
            assert all(body['changes'] == {'name': '保留草稿'} for body in saves)
            assert not any('select_sources' in json.dumps(body) for _, body in calls)
            assert not errors, errors
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
