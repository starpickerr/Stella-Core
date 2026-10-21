"""Account and destination settings have no separate business write grant."""

import json
import os
import re
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("STELLA_TEST_URL", "http://127.0.0.1:5184")
settings = {
    "enabled": False,
    "configured": True,
    "base_url": "https://elearning.fudan.edu.cn",
    "username": "browser-student",
    "courses": ["42"],
    "course_options": [{"id": "42", "name": "课程"}],
    "account_id": "test-account",
    "password_set": True,
    "password_masked": "********",
    "file_sync_root": "/initial",
}
saves = []
syncs = []
fail_save = [False]
source_enabled = [True]


def backend(route):
    path = urlparse(route.request.url).path
    data = {"status": "success"}
    if path == "/api/health":
        data = {"status": "ok"}
    elif path == "/auth/check":
        data.update(auth_required=False, authenticated=True)
    elif path == "/api/data":
        data.update(sources=[{"provider": "elearning", "enabled": source_enabled[0], "available": True}], errors=[])
    elif path == "/api/elearning/file-sync":
        if route.request.method == "POST":
            body = route.request.post_data_json
            saves.append(body)
            assert set(body) == {"file_sync_root"}
            if fail_save[0]:
                data = {
                    "status": "error",
                    "message": "目录不可访问，请检查系统目录权限",
                }
            else:
                settings.update(body)
        data["settings"] = settings
    elif path == '/api/data/elearning/sync-files':
        syncs.append(route.request.post_data_json)
        data['sync'] = {'status': 'completed', 'processed': 2, 'next_offset': None, 'errors': []}
    elif path == "/api/briefings/elearning/test":
        data.update(connected=True, courses=settings["course_options"])
    elif path == "/api/briefings/elearning":
        if route.request.method == "POST":
            body = route.request.post_data_json
            assert "file_sync_enabled" not in body
            settings.update(
                {key: value for key, value in body.items() if key != "password"}
            )
        data["settings"] = settings
    elif path == "/api/plugins/runtime":
        data["plugins"] = []
    elif path == "/api/models":
        data.update(
            providers=[{"id": "test", "configured": True, "label": "Test"}],
            capabilities={
                "chat": {"current_provider": "test", "current_model": "test"}
            },
        )
    else:
        data.update(
            tools=[],
            servers=[],
            skills=[],
            result=[],
            updates=[],
            blocked=[],
            sources=[],
        )
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(data),
        headers={
            "Access-Control-Allow-Origin": URL,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            platform:'darwin', getBackendPort:async()=>9876, onBackendStatus:()=>()=>{},
            getBackendError:async()=>null, getAppVersion:async()=>'9.9.9',
            selectDirectory:async()=>'/Users/starpickerr/Desktop/课程资料'};""")
        page.route("http://127.0.0.1:9876/**", backend)
        page.goto(URL + "/#/elearning", wait_until="networkidle")
        expect(page).to_have_url(URL + '/#/data/sources/elearning')
        expect(page.get_by_role('link', name='返回数据', exact=True)).to_be_visible()
        expect(page.locator('aside').get_by_role('button', name='数据', exact=True)).to_have_class(re.compile('bg-accent-soft'))
        root = page.get_by_role("textbox", name="课件保存目录", exact=True)
        expect(root).to_have_value("/initial")
        expect(
            page.get_by_role("switch", name="允许 Agent 保存所选课程文件")
        ).to_have_count(0)
        page.get_by_role("button", name="测试连接并读取课程", exact=True).click()
        expect(
            page.get_by_text("eLearning 连接成功，已读取课程", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="选择目录", exact=True).click()
        expect(root).to_have_value("/Users/starpickerr/Desktop/课程资料")
        page.get_by_role("button", name="保存", exact=True).last.click()
        expect(page.get_by_text("保存目录已更新", exact=True)).to_be_visible()
        assert saves[-1] == {"file_sync_root": "/Users/starpickerr/Desktop/课程资料"}
        page.reload(wait_until="networkidle")
        expect(root).to_have_value("/Users/starpickerr/Desktop/课程资料")
        page.get_by_role('button', name='同步课程文件', exact=True).click()
        expect(page.get_by_text('已处理 2 个文件', exact=True)).to_be_visible()
        assert syncs == [{'offset': 0, 'limit': 50}]
        source_enabled[0] = False
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("button", name="同步课程文件", exact=True)).to_be_disabled()
        expect(page.get_by_text("信息源已停用，请在数据中启用后同步", exact=True)).to_be_visible()
        source_enabled[0] = True
        page.reload(wait_until="networkidle")
        fail_save[0] = True
        root.fill("/unavailable")
        expect(page.get_by_role('button', name='同步课程文件', exact=True)).to_be_disabled()
        page.get_by_role("button", name="保存", exact=True).last.click()
        expect(page.get_by_role("alert")).to_contain_text("目录不可访问")
        assert settings["file_sync_root"] == "/Users/starpickerr/Desktop/课程资料"
        page.screenshot(
            path="/tmp/stella-elearning-settings-desktop.png", full_page=True
        )
        page.set_viewport_size({"width": 620, "height": 900})
        expect(root).to_be_visible()
        root.scroll_into_view_if_needed()
        box = root.bounding_box()
        assert box and box["x"] >= 208 and box["x"] + box["width"] <= 620
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path="/tmp/stella-elearning-settings-narrow.png", full_page=True
        )
        assert not errors, errors
        print(
            "PASS: eLearning account connection, destination-only save, persistence, failure and narrow layout"
        )
    finally:
        browser.close()
