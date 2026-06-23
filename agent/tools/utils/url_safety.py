"""
Shared SSRF guard utilities for tools that fetch model-supplied URLs.

A URL is only considered safe when it uses an http/https scheme, has a
hostname, that hostname resolves, and every resolved address is a public
(internet-routable) address. Loopback, private (RFC1918 / ULA), link-local
(incl. the 169.254.169.254 cloud-metadata endpoint) and otherwise reserved
addresses are rejected, for both IPv4 and IPv6.
"""

import ipaddress
import socket
from urllib.parse import urlparse


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    """Return True if the address is not safe to connect to (non-public)."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_ip(ip_str: str) -> None:
    """Raise ValueError if the given literal IP is a non-public address.

    Used to re-validate the concrete address a redirect resolved to.
    """
    ip = ipaddress.ip_address(ip_str)
    if _is_blocked_ip(ip):
        raise ValueError(
            f"URL resolves to a non-public address ({ip_str}), "
            f"request blocked for security"
        )


def validate_url_safe(url: str) -> None:
    """Reject URLs that target private/loopback/link-local addresses (SSRF guard).

    Resolves the hostname to its IP address(es) and blocks any that fall
    into non-public ranges. Also rejects URLs with no host, non-HTTP(S)
    schemes, or hosts that fail DNS resolution.

    Raises:
        ValueError: if the URL targets a disallowed address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    try:
        # Resolve all addresses for the hostname.
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in addr_infos:
        assert_public_ip(sockaddr[0])
