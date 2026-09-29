"""Canvas API、网络请求与浏览器登录。"""
import http.cookiejar
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import LoginRequired, SyncError
from .utils import next_link
from agent.briefing.elearning_settings import session_path, save_session

LOGGER = logging.getLogger("elearning")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise SyncError("服务器返回了非 HTTPS 跳转，已停止请求。")
        redirect = super().redirect_request(req, fp, code, msg, headers, newurl)
        # Never forward authentication headers to another host.
        if urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            for header in ("Authorization", "Cookie"):
                redirect.remove_header(header)
        return redirect


def cookie_matches_host(domain, host):
    domain, host = domain.lower(), host.lower()
    return domain.lstrip(".") == host or (domain.startswith(".") and host.endswith(domain))


class Canvas:
    def __init__(self, config, cookies=None, auto_login=True):
        self.config = config
        self.base = config["base_url"].rstrip("/")
        self.origin = urllib.parse.urlparse(self.base).netloc
        self.interval = max(float(config.get("request_interval", 0.4)), 0)
        # Verification during browser login must never trigger another browser login.
        self.auto_login = auto_login and cookies is None
        # Explicit browser cookies must be verified independently of any configured Token.
        self.token = "" if cookies is not None else config.get("token", "")
        try:
            self._load_cookies(cookies)
        except LoginRequired:
            if not self.auto_login or self.token:
                raise
            self._renew_login()

    def _load_cookies(self, cookies=None):
        jar = http.cookiejar.CookieJar()
        auth = session_path(self.config)
        if cookies is None and not self.token:
            if not auth.is_file():
                raise LoginRequired("尚未连接 eLearning，请在简报设置中测试连接。")
            try:
                cookies = json.loads(auth.read_text(encoding="utf-8"))["cookies"]
            except (ValueError, KeyError, TypeError):
                raise LoginRequired("保存的登录状态无效，请重新登录。") from None
        if cookies is not None and not self.token:
            if not isinstance(cookies, list) or any(not isinstance(item, dict) for item in cookies):
                raise LoginRequired("保存的登录状态无效，请重新登录。")
            try:
                for item in cookies:
                    domain = item["domain"]
                    if not cookie_matches_host(domain, urllib.parse.urlparse(self.base).hostname):
                        continue
                    expiry = float(item.get("expires", -1))
                    jar.set_cookie(http.cookiejar.Cookie(
                        version=0, name=item["name"], value=item["value"], port=None,
                        port_specified=False, domain=domain, domain_specified=domain.startswith("."),
                        domain_initial_dot=domain.startswith("."), path=item.get("path", "/"),
                        path_specified=True, secure=item.get("secure", True),
                        expires=int(expiry) if expiry >= 0 else None, discard=expiry < 0,
                        comment=None, comment_url=None, rest={}, rfc2109=False))
            except (KeyError, ValueError, TypeError, AttributeError):
                raise LoginRequired("保存的登录状态无效，请重新登录。") from None
        jar.clear_expired_cookies()
        if not self.token and not list(jar):
            raise LoginRequired("登录状态中没有可用的 elearning Cookie，请重新登录。")
        self.cookie_jar = jar
        self.opener = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPCookieProcessor(jar))

    def _renew_login(self):
        print("尚未登录或 Cookie 已失效，正在连接 eLearning……", flush=True)
        LOGGER.info("开始自动登录")
        try:
            login(self.config)
            self._load_cookies()
        except (SyncError, OSError) as error:
            LOGGER.warning("自动登录失败（%s）", type(error).__name__)
            raise LoginRequired("自动登录未成功：{}".format(error)) from None
        LOGGER.info("自动登录完成")

    def session_data(self):
        # Include cookies refreshed by the verification response, not just the browser snapshot.
        host = urllib.parse.urlparse(self.base).hostname
        return {"cookies": [{"name": item.name, "value": item.value, "domain": item.domain,
                             "path": item.path, "secure": item.secure,
                             "expires": item.expires if item.expires is not None else -1}
                            for item in self.cookie_jar if cookie_matches_host(item.domain, host)]}

    def open(self, url, api=True):
        try:
            return self._open(url, api)
        except LoginRequired:
            if not self.auto_login or self.token:
                raise
            self._renew_login()
            # Retry this request once, preserving the current selection and download progress.
            # A second authentication failure propagates instead of reopening browsers in a loop.
            return self._open(url, api)

    def _open(self, url, api=True):
        url = urllib.parse.urljoin(self.base + "/", url)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise SyncError("只允许 HTTPS 请求。")
        if api and parsed.netloc != self.origin:
            raise SyncError("接口分页地址不属于 elearning，已停止请求。")
        headers = {"User-Agent": "FudanCourseSync/1.0", "Accept": "application/json" if api else "*/*"}
        if self.token and parsed.netloc == self.origin:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(4):
            time.sleep(self.interval)
            try:
                response = self.opener.open(urllib.request.Request(url, headers=headers), timeout=60)
                if api and (urllib.parse.urlparse(response.geturl()).netloc != self.origin or
                            "json" not in response.headers.get("Content-Type", "").lower()):
                    response.close()
                    raise LoginRequired("登录已失效，或站点未返回接口数据，请重新登录。")
                if not api and any(kind in response.headers.get("Content-Type", "").lower()
                                   for kind in ("text/html", "application/json")) and not response.headers.get(
                                       "Content-Disposition", "").lower().startswith("attachment"):
                    response.close()
                    raise LoginRequired("下载返回了登录或错误页面，未保存为课件。")
                return response
            except urllib.error.HTTPError as error:
                code, retry = error.code, error.headers.get("Retry-After", "")
                error.close()
                if code == 401:
                    raise LoginRequired("登录已失效，请在简报设置中重新测试连接。") from None
                if code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(min(int(retry), 30) if retry.isdigit() else 2 ** attempt)
                    continue
                raise SyncError("网站返回 HTTP {}。".format(code)) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise SyncError("连接失败，请检查网络或校园网连接。") from None

    def get(self, path, params=None):
        if params:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(params, doseq=True)
        with self.open(path) as response:
            try:
                data = json.load(response)
            except (ValueError, UnicodeDecodeError):
                raise SyncError("接口数据格式不正确。") from None
            return data, next_link(response.headers.get("Link"))

    def list(self, path, params=None):
        params = dict(params or {}, per_page=100)
        output, seen = [], set()
        while path:
            if path in seen:
                raise SyncError("接口分页循环，已停止以防重复请求。")
            seen.add(path)
            data, path = self.get(path, params)
            params = None
            if not isinstance(data, list):
                raise SyncError("接口未返回列表。")
            output.extend(data)
        return output


def read_login_credentials(config):
    values = config
    username = (values.get("username") or "").strip()
    password = values.get("password") or ""
    if not username or not password:
        raise SyncError("请在简报设置中填写 eLearning 学工号和密码。")
    return username, password


def ensure_login(config):
    canvas = Canvas(config)
    profile, _ = canvas.get("/api/v1/users/self/profile")
    if not isinstance(profile, dict) or not profile.get("id"):
        raise LoginRequired("未能验证登录状态，请检查登录配置。")
    return canvas


def login(config, manual=False):
    username, password = (None, None) if manual else read_login_credentials(config)
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        raise SyncError("缺少 Playwright 登录组件，请安装桌面运行依赖。") from None
    base = config["base_url"].rstrip("/")
    host = urllib.parse.urlparse(base).hostname
    print("即将打开浏览器，请在窗口中登录。" if manual else
          "正在使用本地 eLearning 设置登录。", flush=True)
    from agent.tools.browser.browser_env import apply_browsers_path_env
    apply_browsers_path_env()
    with sync_playwright() as p:
        stage = "打开登录页面"
        try:
            browser = p.chromium.launch(channel="chrome", headless=not manual)
        except Exception:
            try:
                browser = p.chromium.launch(headless=not manual)
            except Exception:
                raise SyncError("无法打开浏览器，请安装 Chrome，或运行 python -m playwright install chromium。") from None
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(base + "/login", timeout=60000)
            if not manual:
                # Form selectors verified on Fudan's public SSO page.
                try:
                    stage = "提交登录表单"
                    page.locator('#login-username').wait_for(state="visible", timeout=20000)
                    if urllib.parse.urlparse(page.url).hostname != "id.fudan.edu.cn":
                        raise SyncError("登录页面不属于复旦统一身份认证。")
                    page.locator('#login-username').fill(username, timeout=20000)
                    page.locator('#login-password').fill(password, timeout=20000)
                    page.get_by_role('button', name='登录', exact=True).click(timeout=20000)
                except Exception:
                    if not manual:
                        raise SyncError("自动登录未成功，请检查学工号、密码和学校认证要求。") from None
                finally:
                    username = password = None
            deadline = time.monotonic() + (600 if manual else 90)
            stage = "等待登录跳转"
            while time.monotonic() < deadline:
                if page.is_closed():
                    raise SyncError("登录窗口已关闭，未保存登录状态。")
                if urllib.parse.urlparse(page.url).hostname == host:
                    # Use the same network/proxy handling as all subsequent API operations.
                    cookies = [c for c in context.cookies() if cookie_matches_host(c["domain"], host)]
                    stage = "验证登录状态"
                    try:
                        canvas = Canvas(config, cookies=cookies)
                        profile, _ = canvas.get("/api/v1/users/self/profile")
                        if isinstance(profile, dict) and profile.get("id"):
                            save_session(config, canvas.session_data())
                            print("登录成功，已验证并保存 elearning 登录状态。浏览器将关闭。", flush=True)
                            return
                    except LoginRequired:
                        # The success redirect may arrive before Canvas has finished establishing its session.
                        pass
                    except SyncError as error:
                        raise SyncError("验证登录状态失败：{} 登录状态尚未保存。".format(error)) from None
                    stage = "等待登录跳转"
                page.wait_for_timeout(1500)
            raise SyncError("等待登录状态验证超时，未保存 Cookie。请检查账号密码和网络后重试。")
        except SyncError:
            raise
        except PlaywrightError as error:
            # Report useful categories without exposing SSO tickets or credentials in raw browser errors.
            codes = re.findall(r"net::ERR_[A-Z_]+|ENOTFOUND|ECONNREFUSED|ETIMEDOUT", str(error))
            detail = "（{}）".format(codes[0]) if codes else ""
            raise SyncError("{}失败{}，登录状态尚未保存，请检查网络后重试。".format(stage, detail)) from None
        except Exception:
            raise SyncError("{}失败，登录状态尚未保存，请重试。".format(stage)) from None
        finally:
            browser.close()
