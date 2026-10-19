"""IMAP host normalization (shared by settings validation and the IMAP client)."""

from __future__ import annotations

import ipaddress
import re


def normalize_imap_host(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请填写 IMAP 服务器地址")
    host = value.strip()
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        encoded = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        encoded = ""
    if not encoded or len(encoded) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in encoded.split(".")
    ):
        raise ValueError("IMAP 服务器只填写主机名，例如 imap.gmail.com；不要填写邮箱地址、网址或端口")
    return encoded
