"""Native Data management actions, denial, storage ownership and narrow layout."""

import json
import os
import re
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import expect, sync_playwright

url = os.environ.get("STELLA_TEST_URL", "http://127.0.0.1:5184")
source = {
    "id": "mcp:email:a",
    "name": "收件箱",
    "provider": "email",
    "kind": "email",
    "account_id": "a",
    "enabled": True,
    "available": True,
    "connection": "mcp:email",
    "settings_url": "/email",
    "storage": "persistent",
    "retention_days": 30,
    "running": False,
    "last_run": None,
    "error": "",
}
reference_source = {**source, 'id': 'documents:library', 'name': '文档引用', 'kind': 'document',
                    'provider': 'documents', 'representation': 'reference',
                    'operations': ['metadata', 'configure', 'resources', 'read'],
                    'connection': None, 'settings_url': None}

records = [
    {
        "id": "record-1",
        "source_id": source["id"],
        "version": "v1",
        "item": {
            "source": "email",
            "account_id": "a",
            "source_id": "message",
            "title": "项目会议",
            "snippet": "安排本周会议",
            "occurred_at": "2026-10-21T00:00:00Z",
            "url": "https://example.test/mail",
            "payload": {"body": "仅在获准读取时显示的邮件正文"},
        },
    }
]
subscriptions = []
deliveries = []
commands = []
queries = []
grants = [
    {
        "id": "old-mail-grant",
        "server": "email",
        "consumer": "stella.briefing",
        "capabilities": ["email.fetch"],
        "methods": ["fetch_messages"],
        "purposes": ["interactive"],
        "resources": [{"kind": "account", "id": "a"}],
        "valid_until": None,
        "revoked": True,
        "revision": 2,
        "scoped": True,
    }
]
fail = [False]
fail_read = [False]
storage = {
    "available": True,
    "categories": [
        {
            "id": "temporary",
            "name": {"zh": "临时文件", "en": "Temporary files"},
            "path": "/isolated/tmp",
            "bytes": 3,
            "exists": True,
            "retention": {"zh": "可安全清理", "en": "Safe to clear"},
            "actions": ["clear_temporary"],
        }
    ],
}


def backend(route):
    path = urlparse(route.request.url).path
    data = {"status": "success"}
    if route.request.method == "OPTIONS":
        route.fulfill(
            status=204,
            headers={
                "Access-Control-Allow-Origin": url,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            },
        )
        return
    if path == "/api/health":
        data = {"status": "ok"}
    elif path == "/auth/check":
        data.update(auth_required=False, authenticated=True)
    elif path == "/api/data":
        data.update(
            sources=[source, reference_source],
            record_count=len(records),
            subscriptions=subscriptions,
            deliveries=deliveries,
            storage=storage,
            consumers=[{"id": "briefing", "name": "简报"}],
            errors=[],
            scope={'agent': parse_qs(urlparse(route.request.url).query).get('agent', ['alpha'])[0],
                   'session': 'chat', 'root': '/isolated/work', 'kind': 'session'},
            agents=[{'id': 'alpha', 'name': 'Alpha'}, {'id': 'beta', 'name': 'Beta'}],
            workspaces=[{'session': 'chat', 'name': '当前会话'}],
        )
    elif path == "/api/data/resources":
        params = parse_qs(urlparse(route.request.url).query)
        queries.append(params)
        resource = {'id': 'doc-1', 'source_id': reference_source['id'], 'provider': 'documents',
                    'reference': 'doc:42', 'kind': 'document', 'name': '引用笔记', 'operations': ['read']}
        content = '从所有者实时读取的内容'
        if params.get('source_id') == [source['id']]:
            resource = {**resource, 'id': 'mail-1', 'source_id': source['id'], 'provider': 'email',
                        'reference': 'record-1', 'kind': 'email', 'name': '项目会议'}
            content = '仅在获准读取时显示的邮件正文'
        if fail_read[0]:
            data = {'status': 'error', 'message': 'Document access revoked'}
        elif parse_qs(urlparse(route.request.url).query).get('resource_id'):
            data.update(resource=resource, content=content)
        else:
            data.update(resources=[resource], total=1, offset=0, limit=50)
    elif path == "/api/data/records":
        if fail_read[0]:
            data = {"status": "error", "message": "Connection mcp:email was revoked."}
        else:
            data.update(records=records, total=len(records), offset=0, limit=50)
    elif path == "/api/data/command":
        body = route.request.post_data_json
        commands.append(body)
        if fail[0]:
            data = {"status": "error", "message": "保存失败，请重试"}
        elif body["action"] == "source":
            source.update(
                {
                    k: v
                    for k, v in body.items()
                    if k in ["enabled", "storage", "retention_days"]
                }
            )
        elif body["action"] == "sync":
            source["last_run"] = 1792530000
            data["sync"] = {"processed": 1, "errors": []}
        elif body["action"] == "subscribe":
            subscriptions[:] = [
                {
                    "id": "sub",
                    "source_id": source["id"],
                    "consumer": "briefing",
                    "filter": {},
                    "enabled": True,
                }
            ]
            deliveries[:] = [
                {
                    "subscription_id": "sub",
                    "event_id": "event",
                    "state": "failed",
                    "attempts": 1,
                    "error": "Consumer unavailable",
                    "type": "created",
                    "record_id": "record-1",
                    "seq": 1,
                }
            ]
            data["subscription"] = subscriptions[0]
        elif body["action"] == "dispatch":
            deliveries[0].update(state="delivered", error="", attempts=2)
            data["delivery"] = {"delivered": 1, "failed": 0}
        elif body["action"] == "subscription":
            subscriptions[0]["enabled"] = body["enabled"]
        elif body["action"] == "export":
            data["export"] = {
                "format": "stella-data-v1",
                "source_id": source["id"],
                "records": records,
            }
        elif body["action"] == "delete_record" or body["action"] == "cleanup":
            records.clear()
            data["removed"] = 1
        elif body["action"] == "cleanup_storage":
            storage["categories"][0]["bytes"] = 0
            data["removed"] = 1
    elif path == "/api/security/mcp-access":
        body = route.request.post_data_json
        assert body["id"] == "old-mail-grant" and body["revision"] == 2
        grants[0].update(body)
        grants[0]["revision"] += 1
        data["grants"] = grants
    elif path == "/api/security/center":
        policy = {"preset": "workspace-write", "rules": {}, "connections": {}}
        data.update(
            global_policy=policy,
            effective_policy=policy,
            effective_mode="workspace-write",
            effective_rules={},
            policy_source="global",
            mode_definitions=[],
            authorized_roots=[],
            project=None,
            project_policy={},
            projects=[],
            conversation_policy={},
            connections=[],
            secrets=[],
            background_tasks=[],
            process_isolation={"status": "enabled", "reason": ""},
            privacy={"available": True, "categories": [], "external_transfers": []},
            data_access={
                "available": True,
                "resources": [
                    {
                        "id": source["id"],
                        "name": "收件箱",
                        "provider": "email",
                        "account_id": "a",
                        "connection": "mcp:email",
                    }
                ],
                "external_transfers": [],
                "inherited_grants": grants,
            },
            summary={
                "status": "normal",
                "app_password_set": False,
                "connection_count": 0,
                "secret_count": 0,
                "recent_high_risk": [],
                "recent_denials": [],
                "activity_counts": {},
                "background_tasks": {
                    "total": 0,
                    "enabled": 0,
                    "paused": 0,
                    "modes": {},
                    "unknown": 0,
                    "available": True,
                },
            },
        )
    elif path == "/api/security/activity":
        data.update(records=[])
    elif path == "/api/email/accounts":
        data["settings"] = {"mailboxes": []}
    elif path == "/api/models":
        blank = {"current_provider": "", "current_model": "", "providers": []}
        data.update(
            providers=[{"id": "test", "configured": True, "label": "Test"}],
            capabilities={
                **{
                    key: blank
                    for key in ["vision", "image", "embedding", "asr", "tts", "search"]
                },
                "chat": {
                    "current_provider": "test",
                    "current_model": "test",
                    "providers": ["test"],
                },
            },
        )
    elif path == "/api/plugins/runtime":
        data["plugins"] = []
    else:
        data.update(
            sessions=[], tools=[], skills=[], servers=[], entries=[], briefings=[]
        )
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(data),
        headers={
            "Access-Control-Allow-Origin": url,
            "Access-Control-Allow-Credentials": "true",
        },
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page(
            viewport={"width": 1280, "height": 960}, accept_downloads=True
        )
        page.add_init_script(
            "localStorage.setItem('stella_lang','zh');window.electronAPI={platform:'darwin',getBackendPort:async()=>9876,onBackendStatus:()=>()=>{},getBackendError:async()=>null};"
        )
        page.route("http://127.0.0.1:9876/**", backend)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(url + "/#/settings", wait_until="networkidle")
        nav = page.get_by_role("navigation", name="设置分类")
        expect(nav.get_by_role("button", name="数据", exact=True)).to_have_count(0)
        expect(nav.get_by_role("button", name="安全中心", exact=True)).to_have_count(0)
        sidebar = page.locator("aside").first
        expect(sidebar.get_by_role("button", name="安全", exact=True)).to_have_count(1)
        sidebar.get_by_role("button", name="数据", exact=True).click()
        expect(page).to_have_url(url + "/#/data")
        expect(page.get_by_role("heading", name="数据", exact=True)).to_be_visible()
        expect(page.get_by_role("navigation", name="设置分类")).to_have_count(0)
        tabs = page.get_by_role("navigation", name="数据分类")
        expect(tabs.get_by_role('button', name='资源浏览', exact=True)).to_have_attribute('aria-current', 'page')
        expect(page.get_by_role('combobox', name='Agent 范围')).to_be_visible()
        expect(page.get_by_role('combobox', name='工作区范围')).to_be_visible()
        expect(page.get_by_role('combobox', name='资源类型')).to_be_visible()
        for label in ["资源浏览", "信息源", "同步与分发", "存储管理"]:
            expect(tabs.get_by_role("button", name=label, exact=True)).to_be_visible()
        tabs.get_by_role("button", name="信息源", exact=True).click()
        card = page.get_by_test_id("data-source-" + source["id"])
        expect(card.get_by_role("link", name="配置账号")).to_have_attribute(
            "href", re.compile(r'^#/data/sources/email\?agent=.*&session=')
        )
        toggle = card.get_by_role("switch", name="收件箱", exact=True)
        toggle.click()
        expect(toggle).to_have_attribute("aria-checked", "false")
        expect(card.get_by_role("button", name="同步", exact=True)).to_be_disabled()
        fail[0] = True
        toggle.click()
        expect(page.get_by_role("alert")).to_contain_text("保存失败")
        expect(toggle).to_have_attribute("aria-checked", "false")
        fail[0] = False
        toggle.click()
        expect(toggle).to_have_attribute("aria-checked", "true")
        card.get_by_role("button", name="同步", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("同步完成")
        tabs.get_by_role("button", name="资源浏览", exact=True).click()
        expect(page.get_by_text("项目会议", exact=True)).to_be_visible()
        page.get_by_role("button", name="查看内容", exact=True).click()
        expect(
            page.get_by_text("仅在获准读取时显示的邮件正文", exact=True)
        ).to_be_visible()
        with page.expect_download() as info:
            page.get_by_role("button", name="导出", exact=True).click()
        assert info.value.suggested_filename.endswith(".json")
        fail_read[0] = True
        page.get_by_role("button", name="刷新", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("revoked")
        expect(
            page.get_by_text("仅在获准读取时显示的邮件正文", exact=True)
        ).to_have_count(0)
        fail_read[0] = False
        page.get_by_role("button", name="刷新", exact=True).click()
        expect(page.get_by_text("项目会议", exact=True)).to_be_visible()
        tabs.get_by_role("button", name="同步与分发", exact=True).click()
        page.get_by_role("button", name="添加订阅", exact=True).click()
        expect(page.get_by_text("Consumer unavailable", exact=False)).to_be_visible()
        page.get_by_role("button", name="重试投递", exact=True).click()
        expect(page.get_by_text("已投递 · 2", exact=True)).to_be_visible()
        tabs.get_by_role("button", name="存储管理", exact=True).click()
        page.get_by_role("combobox", name="存储策略 收件箱").select_option("reference")
        page.get_by_role("button", name="保存策略 收件箱").click()
        expect(page.get_by_role("status")).to_contain_text("已保存")
        page.get_by_role("button", name="清理临时文件", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("已清理")
        page.screenshot(path="/tmp/stella-data-management-desktop.png", full_page=True)
        page.set_viewport_size({"width": 640, "height": 920})
        for label in ["资源浏览", "信息源", "同步与分发", "存储管理"]:
            tabs.get_by_role("button", name=label, exact=True).click()
            expect(page.get_by_role("button", name="刷新", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path="/tmp/stella-data-management-narrow.png", full_page=True)
        tabs.get_by_role('button', name='信息源', exact=True).click()
        reference_card = page.get_by_test_id('data-source-documents:library')
        expect(reference_card.get_by_role('button', name='同步', exact=True)).to_have_count(0)
        tabs.get_by_role('button', name='资源浏览', exact=True).click()
        page.get_by_role('combobox', name='选择信息源').select_option('documents:library')
        expect(page.get_by_text('引用笔记', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='导出', exact=True)).to_have_count(0)
        page.get_by_role('button', name='查看内容', exact=True).click()
        expect(page.get_by_text('从所有者实时读取的内容', exact=True)).to_be_visible()
        page.get_by_role('combobox', name='资源类型').select_option('document')
        expect(page.get_by_text('引用笔记', exact=True)).to_be_visible()
        assert queries[-1]['kind'] == ['document']
        page.get_by_role('combobox', name='Agent 范围').select_option('beta')
        expect(page.get_by_role('combobox', name='Agent 范围')).to_have_value('beta')
        expect(page.get_by_text('从所有者实时读取的内容', exact=True)).to_have_count(0)
        page.get_by_role('combobox', name='选择信息源').select_option('documents:library')
        expect(page.get_by_text('引用笔记', exact=True)).to_be_visible()
        assert queries[-1]['agent'] == ['beta']
        fail_read[0] = True
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('revoked')
        expect(page.get_by_text('从所有者实时读取的内容', exact=True)).to_have_count(0)
        fail_read[0] = False
        tabs.get_by_role('button', name='同步与分发', exact=True).click()
        expect(page.get_by_role('button', name='添加订阅', exact=True)).to_be_disabled()
        tabs.get_by_role('button', name='存储管理', exact=True).click()
        expect(page.get_by_role('combobox', name='存储策略 文档引用')).to_have_count(0)
        page.screenshot(path='/tmp/stella-data-resources-narrow.png', full_page=True)
        sidebar.get_by_role("button", name="安全", exact=True).click()
        page.get_by_role("navigation", name="安全中心").get_by_role(
            "button", name="数据访问", exact=True
        ).click()
        expect(page.get_by_role("heading", name="数据访问", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="管理数据", exact=True)).to_have_attribute(
            "href", "#/data"
        )
        expect(
            page.get_by_role("button", name="清理临时文件", exact=True)
        ).to_have_count(0)
        grant = page.get_by_test_id("mcp-grant-old-mail-grant")
        expect(grant.get_by_text("已撤销", exact=True)).to_be_visible()
        grant.get_by_role("checkbox", name="允许使用此授权").check()
        grant.get_by_role("button", name="保存授权", exact=True).click()
        expect(grant.get_by_text("有效", exact=True)).to_be_visible()
        assert grants[0]["revoked"] is False
        # Old bookmarks redirect to the sole page and preserve their section.
        page.goto(
            url + "/#/settings?tab=data&section=storage", wait_until="networkidle"
        )
        expect(page).to_have_url(url + "/#/data?section=storage")
        expect(
            page.get_by_role("navigation", name="数据分类").get_by_role(
                "button", name="存储管理", exact=True
            )
        ).to_have_attribute("aria-current", "page")
        expect(page.get_by_role("navigation", name="设置分类")).to_have_count(0)
        page.reload(wait_until="networkidle")
        expect(
            page.get_by_role("navigation", name="数据分类").get_by_role(
                "button", name="存储管理", exact=True
            )
        ).to_have_attribute("aria-current", "page")
        sidebar.get_by_role("button", name="通用", exact=True).click()
        settings_nav = page.get_by_role("navigation", name="设置分类")
        expect(
            settings_nav.get_by_role("button", name="数据", exact=True)
        ).to_have_count(0)
        expect(
            settings_nav.get_by_role("button", name="安全中心", exact=True)
        ).to_have_count(0)
        print(
            "PASS: data source intent, sync, records, denial, export, subscriptions/retry, storage, security boundary, desktop/narrow UI"
        )
    finally:
        browser.close()
