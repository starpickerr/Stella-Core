"""Exercise the desktop login gate against a mocked local backend."""

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        page.add_init_script("""window.electronAPI = {
            getBackendPort: async () => 9876,
            onBackendStatus: () => () => {},
            getBackendError: async () => null
        };""")
        page.route("http://127.0.0.1:9876/api/health", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok"}', headers={"Access-Control-Allow-Origin": "*"}))
        page.route("http://127.0.0.1:9876/auth/check", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"success","auth_required":true,"authenticated":false}', headers={"Access-Control-Allow-Origin": "http://127.0.0.1:5173", "Access-Control-Allow-Credentials": "true"}))
        page.route("http://127.0.0.1:9876/auth/login", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"error"}', headers={"Access-Control-Allow-Origin": "http://127.0.0.1:5173", "Access-Control-Allow-Credentials": "true"}))
        page.goto("http://127.0.0.1:5173", wait_until="networkidle")
        password = page.locator('input[type="password"]')
        password.wait_for(timeout=15000)
        submit = page.locator('button[type="submit"]')
        assert submit.is_disabled()
        password.fill("incorrect-test-password")
        assert submit.is_enabled()
        submit.click()
        page.locator("p.text-red-500").wait_for(timeout=5000)
        assert password.is_visible()
        print("UI smoke: login validation and rejected-password interaction passed")
    finally:
        browser.close()
