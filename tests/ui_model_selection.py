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
    {'id': 'openai', 'label': 'OpenAI', 'configured': True, 'models': ['chat-only'], 'api_key_field': 'open_ai_api_key'},
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
reject_provider_save = [False]


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/security/center':
        data = {'status': 'error', 'message': 'Security contents are tested in ui_security_modes.py'}
    elif path == '/api/models':
        if route.request.method == 'POST':
            body = route.request.post_data_json
            saved.append(body)
            if body['action'] == 'set_provider' and (reject_provider_save[0] or body['provider_id'].startswith('custom:')):
                data.update(status='error', message='Provider configuration rejected')
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
        card('模型厂商').get_by_role('button', name='Alpha').click()
        expect(page.get_by_role('dialog').get_by_role('link', name='在安全中管理凭据')).to_have_attribute('href', '#/security?tab=secrets&secret=CUSTOM%3Aalpha')
        expect(page.locator('input[placeholder="sk-..."]')).to_have_count(0)
        dialog = page.get_by_role('dialog')
        dialog.get_by_role('button', name='添加模型', exact=True).click()
        dialog.get_by_role('textbox').last.fill('alpha-new-image')
        dialog.get_by_role('button', name='保存', exact=True).click()
        expect(dialog).to_have_count(0)
        assert saved[-1]['action'] == 'set_custom_provider' and 'api_key' not in saved[-1]
        image.get_by_role('button').nth(0).click()
        page.get_by_text('Alpha', exact=True).last.click()
        image.get_by_role('button').nth(1).click()
        expect(page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-new-image', exact=True)).to_be_visible()
        page.locator('body > div[style*="position: fixed"]').get_by_text('alpha-new-image', exact=True).click()
        image.get_by_role('button', name='保存', exact=True).click()
        expect(image.get_by_text('已保存', exact=True)).to_be_visible()
        assert saved[-1]['model'] == 'alpha-new-image', saved
        # Built-in and search credentials point to the same Security owner.
        card('模型厂商').get_by_role('button', name='OpenAI').click()
        dialog = page.get_by_role('dialog')
        expect(dialog.get_by_role('link', name='在安全中管理凭据')).to_have_attribute('href', '#/security?tab=secrets&secret=OPENAI_API_KEY')
        expect(dialog.locator('input[type="password"]')).to_have_count(0)
        dialog.get_by_role('button', name='取消', exact=True).click()
        expect(card('联网搜索').get_by_role('link', name='在安全中管理凭据')).to_have_attribute('href', '#/security?tab=secrets&secret=BOCHA_API_KEY')
        # First-run setup saves model routing, then sends missing credentials to Security.
        providers[2]['configured'] = False
        page.evaluate("""async () => {
          const {useOnboardingStore} = await import('/src/store/onboardingStore.ts')
          useOnboardingStore.getState().openWizard()
        }""")
        page.get_by_role('button', name='下一步', exact=True).click()
        page.get_by_role('button', name='选择厂商', exact=True).click()
        page.get_by_text('OpenAI', exact=True).last.click()
        expect(page.locator('input[type="password"]')).to_have_count(0)
        reject_provider_save[0] = True
        page.get_by_role('button', name='继续配置凭据', exact=True).click()
        expect(page.get_by_text('保存失败，请检查后重试', exact=True)).to_be_visible()
        reject_provider_save[0] = False
        page.get_by_role('button', name='继续配置凭据', exact=True).click()
        expect(page).to_have_url(test_url + '/#/security?tab=secrets&secret=OPENAI_API_KEY')
        assert saved[-2]['action'] == 'set_provider' and 'api_key' not in saved[-2]
        assert saved[-1]['action'] == 'set_capability' and saved[-1]['provider_id'] == 'openai'
        page.evaluate("""async () => {
          const {useOnboardingStore} = await import('/src/store/onboardingStore.ts')
          useOnboardingStore.getState().openWizard()
        }""")
        page.get_by_role('button', name='下一步', exact=True).click()
        page.get_by_role('button', name='选择厂商', exact=True).click()
        page.get_by_text('Alpha', exact=True).last.click()
        previous = len(saved)
        page.get_by_role('button', name='开始对话', exact=True).click()
        expect(page.get_by_role('button', name='开始对话', exact=True)).to_have_count(0)
        assert len(saved) == previous + 1 and saved[-1]['action'] == 'set_capability'
        assert errors == [], errors
        print('Model selection: configured catalogs, six capabilities, vendor switching, manual models, reload, and vendor editing passed')
    finally:
        browser.close()
