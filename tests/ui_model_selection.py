"""Configured vendor models remain selectable across model capabilities."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
providers = [
    {'id': 'custom:alpha', 'label': 'Alpha', 'configured': True, 'is_custom': True,
     'custom_id': 'alpha', 'custom_name': 'Alpha', 'model': 'alpha-default',
     'models': ['alpha-default', 'alpha-vision', 'alpha-image'], 'api_base': 'https://example.invalid/v1'},
    {'id': 'custom:beta', 'label': 'Beta', 'configured': True, 'is_custom': True,
     'custom_id': 'beta', 'custom_name': 'Beta', 'model': 'beta-default', 'models': ['beta-default']},
    {'id': 'openai', 'label': 'OpenAI', 'configured': True, 'models': ['chat-only']},
]
capabilities = {
    key: {'current_provider': '', 'current_model': '',
          'providers': [p['id'] for p in providers],
          'provider_models': {'custom': [], 'openai': [key + '-preset']}}
    for key in ('chat', 'vision', 'image', 'asr', 'tts', 'embedding')
}
capabilities['chat'].update(current_provider='custom:alpha', current_model='alpha-default')
capabilities['tts'].update(reply_mode='always', current_voice='', provider_voices={})
capabilities['search'] = {'strategy': 'auto', 'providers': [], 'current_provider': ''}
saved = []


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        if route.request.method == 'POST':
            body = route.request.post_data_json
            saved.append(body)
            if body['action'] == 'set_capability':
                capabilities[body['capability']].update(
                    current_provider=body['provider_id'], current_model=body['model'])
            elif body['action'] == 'set_custom_provider':
                providers[0].update(model=body['model'], models=body['models'])
        data.update(providers=providers, capabilities=capabilities)
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
        page.goto(test_url + '/#/settings?tab=models', wait_until='networkidle')

        def card(title):
            return page.locator('div.rounded-card').filter(
                has=page.get_by_role('heading', name=title, exact=True))

        # Menus use portals, so options are located on the page, not in the card.
        for key, title in (('vision', '图像理解'), ('image', '图像生成'), ('chat', '主模型'),
                           ('asr', '语音识别'), ('embedding', '向量'), ('tts', '语音合成')):
            section = card(title)
            provider_index = 1 if key == 'tts' else 0
            model_index = provider_index + 1
            section.get_by_role('button').nth(provider_index).click()
            page.get_by_text('Alpha', exact=True).last.click()
            section.get_by_role('button').nth(model_index).click()
            expect(page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-image', exact=True)).to_be_visible()
            page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-image', exact=True).click()
            section.get_by_role('button', name='保存', exact=True).click()
            expect(section.get_by_text('已保存', exact=True)).to_be_visible()
            assert saved[-1]['provider_id'] == 'custom:alpha' and saved[-1]['model'] == 'alpha-image', saved

        # Switching vendors must clear the previous vendor's selected model.
        image = card('图像生成')
        image.get_by_role('button').nth(0).click()
        page.get_by_text('Beta', exact=True).last.click()
        expect(image.get_by_role('button').nth(1)).to_have_text('beta-default')
        image.get_by_role('button').nth(1).click()
        expect(page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-image', exact=True)).to_have_count(0)
        expect(page.locator('body > div[style*="position: fixed"]').get_by_text('自定义', exact=True)).to_have_count(1)
        page.locator('body > div[style*="position: fixed"]').get_by_text('自定义', exact=True).click()
        image.get_by_role('textbox').fill('manual-image-model')
        image.get_by_role('button', name='保存', exact=True).click()
        expect(image.get_by_text('已保存', exact=True)).to_be_visible()
        assert saved[-1]['model'] == 'manual-image-model', saved
        page.reload(wait_until='networkidle')
        expect(card('图像生成').get_by_role('button').nth(1)).to_have_text('manual-image-model')

        # Built-in providers keep the catalog specific to the capability.
        image = card('图像生成')
        image.get_by_role('button').nth(0).click()
        page.get_by_text('OpenAI', exact=True).last.click()
        expect(image.get_by_role('button').nth(1)).to_have_text('image-preset')

        # Editing vendor models refreshes downstream menus without reloading.
        card('厂商凭据').get_by_role('button', name='Alpha').click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_role('button', name='添加模型', exact=True).click()
        dialog.get_by_role('textbox').last.fill('alpha-new-image')
        dialog.get_by_role('button', name='保存', exact=True).click()
        expect(dialog).to_have_count(0)
        image.get_by_role('button').nth(0).click()
        page.get_by_text('Alpha', exact=True).last.click()
        image.get_by_role('button').nth(1).click()
        expect(page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-new-image', exact=True)).to_be_visible()
        page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-new-image', exact=True).click()
        image.get_by_role('button', name='保存', exact=True).click()
        expect(image.get_by_text('已保存', exact=True)).to_be_visible()
        assert saved[-1]['model'] == 'alpha-new-image', saved
        assert errors == [], errors
        print('Model selection: configured catalogs, six capabilities, vendor switching, manual models, reload, and vendor editing passed')
    finally:
        browser.close()
