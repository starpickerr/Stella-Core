"""Run against a renderer with STELLA_PRODUCT_DIR=tests/fixtures/managed_product."""
import json
import os
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5185')
saved = []


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data['status'] = 'ok'
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/config':
        if route.request.method == 'POST':
            saved.append(route.request.post_data_json['updates'])
        data.update(model='managed-model', bot_type='linkai', use_linkai=True,
                    api_keys={'linkai_api_key': '********'},
                    providers={'linkai': {'label': 'LinkAI', 'models': ['managed-model'], 'api_key_field': 'linkai_api_key'}})
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');window.electronAPI={platform:'darwin',
          getBackendPort:async()=>9876,onBackendStatus:()=>()=>{},getBackendError:async()=>null};""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/models', wait_until='networkidle')
        expect(page.get_by_role('heading', name='主模型', exact=True)).to_be_visible()
        expect(page.get_by_text('已配置凭据', exact=True)).to_be_visible()
        link = page.get_by_role('link', name='在安全中管理凭据', exact=True)
        expect(link).to_have_attribute('href', '#/security?tab=secrets&secret=LINKAI_API_KEY')
        expect(page.locator('input[type="password"]')).to_have_count(0)
        page.get_by_role('button', name='保存', exact=True).click()
        expect(page.get_by_text('已保存', exact=True)).to_be_visible()
        assert saved == [{'model': 'managed-model', 'use_linkai': True, 'bot_type': ''}], saved
        page.set_viewport_size({'width': 620, 'height': 900})
        expect(link).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        link.focus()
        expect(link).to_be_focused()
        assert not errors, errors
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/managed-models-narrow.png', full_page=True)
        print('PASS: managed model choice, sole Security credential owner, payload, keyboard and narrow layout')
    finally:
        browser.close()
