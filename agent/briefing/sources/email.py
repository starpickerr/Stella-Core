"""IMAP incremental fetch with local mailbox settings or environment defaults."""

from __future__ import annotations

import imaplib
import hashlib
import sys
import socket
import json
import re
import ssl as ssl_module
from html import unescape
from datetime import date, datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Callable, Dict, List, Optional

from agent.briefing.sources.base import FetchResult, FetchedItem

_DEFAULT_LOOKBACK_DAYS = 2


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _header(msg, name: str) -> str:
    return _decode_header(msg.get(name))


def _occurred_at(raw: str) -> str:
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _message_id(msg) -> str:
    value = (_header(msg, "Message-ID") or _header(msg, "Message-Id")).strip()
    return value


def _thread_id(msg) -> str:
    refs = _header(msg, "References").strip()
    if refs:
        return refs.split()[0]
    reply = _header(msg, "In-Reply-To").strip()
    if reply:
        return reply.split()[0]
    return ""


def _list_id(msg) -> str:
    raw = _header(msg, "List-Id").strip()
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        return raw[raw.rfind("<") + 1 : raw.rfind(">")].strip()
    return raw


def _body(msg) -> str:
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() != "text" or part.get_content_disposition() == "attachment":
            continue
        raw = part.get_payload(decode=True)
        if not isinstance(raw, bytes):
            continue
        try:
            text = raw.decode(part.get_content_charset() or "utf-8", "replace")
        except LookupError:
            text = raw.decode("utf-8", "replace")
        if part.get_content_type() == "text/plain":
            plain.append(text)
        elif part.get_content_type() == "text/html":
            text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text, flags=re.I | re.S)
            html.append(unescape(re.sub(r"<[^>]*>", " ", text)))
    return "\n\n".join(plain or html).strip()


def parse_rfc822(
    raw: bytes, *, uid: str, account_id: str = "default", uidvalidity: str = ""
) -> FetchedItem:
    """Turn RFC822 bytes (headers or a full message) into a FetchedItem."""
    msg = message_from_bytes(raw)
    sender_name, sender_email = parseaddr(_header(msg, "From"))
    message_id = _message_id(msg)
    source_id = message_id or f"imap-uid-{uidvalidity}-{uid}"
    list_unsub = bool(_header(msg, "List-Unsubscribe").strip())
    title = _header(msg, "Subject")
    body = _body(msg)
    return FetchedItem(
        source="email",
        source_id=source_id,
        account_id=account_id,
        thread_id=_thread_id(msg),
        sender=sender_name or sender_email,
        title=title,
        snippet=" ".join(body.split())[:500] or title,
        occurred_at=_occurred_at(_header(msg, "Date")),
        url=f"mid:{message_id.strip('<>')}" if message_id else "",
        payload={"body": body, **({"list_unsubscribe": True} if list_unsub else {})},
        sender_email=sender_email,
        list_id=_list_id(msg),
    )


def _uids_from_search(payload) -> List[str]:
    if not payload or payload[0] is None:
        return []
    blob = payload[0]
    if isinstance(blob, bytes):
        text = blob.decode("ascii", "replace")
    else:
        text = str(blob)
    return [part for part in text.split() if part.isdigit()]


def _header_bytes_from_fetch(payload) -> bytes:
    if not payload:
        return b""
    for part in payload:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
        if isinstance(part, (bytes, bytearray)) and b":" in part:
            return bytes(part)
    return b""


class EmailSource:
    name = "email"

    def __init__(
        self,
        *,
        account_id: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        folder: Optional[str] = None,
        ssl: bool = True,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        opener: Optional[Callable[[], object]] = None,
    ):
        self._account_id = account_id
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._folder = folder
        self._ssl = ssl
        self.lookback_days = lookback_days
        self._opener = opener
        self._resolved_settings = None

    @property
    def display_name(self) -> str:
        return f"email ({self._user})" if self._user else "email"

    @property
    def account_id(self) -> str:
        if self._account_id is not None:
            return self._account_id
        if self._opener is not None:
            return "default"
        cfg = self._settings()
        # UIDs are scoped to the mailbox; changing account/folder must not
        # inherit the previous mailbox's cursor or fallback message ids.
        key = json.dumps([cfg["host"].casefold(), cfg["port"], cfg["user"], cfg["folder"]])
        return "imap-" + hashlib.sha256(key.encode()).hexdigest()[:16]

    def _settings(self) -> dict:
        if self._resolved_settings is not None:
            return self._resolved_settings
        from agent.briefing.settings import load_mailbox
        explicit = {"host": self._host, "port": self._port, "user": self._user,
                    "password": self._password, "folder": self._folder}
        cfg = dict(explicit) if all(value is not None for value in explicit.values()) else load_mailbox()
        for key, value in (("host", self._host), ("port", self._port),
                           ("user", self._user), ("password", self._password),
                           ("folder", self._folder)):
            if value is not None:
                cfg[key] = value
        from agent.briefing.settings import normalize_imap_host
        if cfg["host"]:
            cfg["host"] = normalize_imap_host(cfg["host"])
        cfg["port"] = int(cfg["port"])
        if not 1 <= cfg["port"] <= 65535:
            raise ValueError("IMAP_PORT must be between 1 and 65535")
        cfg["ssl"] = self._ssl
        self._resolved_settings = cfg
        return cfg

    def _connect(self):
        if self._opener is not None:
            return self._opener()
        cfg = self._settings()
        if not cfg["host"] or not cfg["user"] or not cfg["password"]:
            raise ValueError(
                "IMAP is not configured; set IMAP_HOST, IMAP_USER, and IMAP_PASSWORD"
            )
        timeout = {"timeout": 30} if sys.version_info >= (3, 9) else {}
        client = None
        try:
            if cfg["ssl"]:
                client = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], ssl_context=ssl_module.create_default_context(), **timeout)
            else:
                client = imaplib.IMAP4(cfg["host"], cfg["port"], **timeout)
            client.socket().settimeout(30)
            client.login(cfg["user"], cfg["password"])
            return client
        except Exception as exc:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass
            if isinstance(exc, socket.gaierror):
                raise ValueError(f"无法解析 IMAP 服务器 {cfg['host']}，尚未验证授权码。请检查服务器地址、网络、DNS 或代理的 DNS 设置。") from None
            if isinstance(exc, ssl_module.SSLError):
                raise ValueError("IMAP SSL 连接失败，请检查 SSL 端口和网络连接。") from None
            if isinstance(exc, (TimeoutError, socket.timeout)):
                raise ValueError("IMAP 连接超时，请确认当前网络可以访问邮箱服务器及 SSL 端口。") from None
            if isinstance(exc, ConnectionRefusedError):
                raise ValueError("IMAP 服务器拒绝连接，请检查服务器地址、SSL 端口及网络连接。") from None
            if isinstance(exc, imaplib.IMAP4.error):
                raise ValueError("IMAP 登录失败，请确认邮箱账号和授权码，并检查邮箱服务是否允许 IMAP 访问。") from None
            if isinstance(exc, OSError):
                raise ValueError("IMAP 网络连接失败，请检查网络、DNS、代理设置及 SSL 端口。") from None
            raise

    def check_connection(self) -> None:
        cfg = self._settings()
        client = self._connect()
        try:
            status, _ = client.select(cfg["folder"], readonly=True)
            if status != "OK":
                raise ValueError("已登录，但无法打开邮件文件夹，请检查文件夹名称。")
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        cfg = self._settings()
        client = self._connect()
        try:
            status, _ = client.select(cfg["folder"], readonly=True)
            if status != "OK":
                raise RuntimeError(f"IMAP SELECT {cfg['folder']} failed: {status}")
            uidvalidity = _uidvalidity(client)
            last_uid = int(cursors.get("imap_uid") or 0)
            last_validity = cursors.get("imap_uidvalidity") or ""
            if last_validity and last_validity != uidvalidity:
                last_uid = 0

            refresh = cursors.get("refresh_existing_content") == "1"
            uids = self._search_uids(client, 0 if refresh else last_uid, cursors.get("since"))
            items: List[FetchedItem] = []
            max_uid = last_uid
            for uid in sorted(set(uids), key=int):
                number = int(uid)
                if number <= last_uid and not refresh:
                    continue
                raw = self._fetch_message(client, uid)
                if not raw:
                    raise RuntimeError(f"IMAP FETCH UID {uid} returned no message")
                items.append(parse_rfc822(raw, uid=uid, account_id=self.account_id, uidvalidity=uidvalidity))
                if number > max_uid:
                    max_uid = number
            return FetchResult(
                items=items,
                cursors={
                    "imap_uid": str(max_uid),
                    "imap_uidvalidity": uidvalidity,
                },
            )
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _search_uids(self, client, last_uid: int, window_start: Optional[str] = None) -> List[str]:
        if last_uid > 0:
            status, payload = client.uid("SEARCH", None, "UID", f"{last_uid + 1}:*")
        else:
            if window_start:
                # IMAP SINCE uses the server's internal date, with day precision.
                since_day = datetime.fromisoformat(window_start.replace("Z", "+00:00")).date() - timedelta(days=1)
            else:
                since_day = date.today() - timedelta(days=self.lookback_days)
            since = since_day.strftime("%d-%b-%Y")
            status, payload = client.uid("SEARCH", None, "SINCE", since)
        if status != "OK":
            raise RuntimeError(f"IMAP SEARCH failed: {status}")
        return _uids_from_search(payload)

    def _fetch_message(self, client, uid: str) -> bytes:
        status, payload = client.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK":
            raise RuntimeError(f"IMAP FETCH UID {uid} failed: {status}")
        return _header_bytes_from_fetch(payload)


def _uidvalidity(client) -> str:
    raw = getattr(client, "untagged_responses", {}).get("UIDVALIDITY") or []
    if not raw:
        return ""
    value = raw[0]
    if isinstance(value, bytes):
        return value.decode("ascii", "replace")
    return str(value)
