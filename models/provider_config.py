"""Resolve an upstream endpoint, model and wire protocol independently.

The old bot_type remains readable, but an explicit provider or protocol always
wins over model-name heuristics. Credentials stay on the provider, never on a
model binding or run record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from common import const
from config import conf


PROTOCOLS = frozenset({"openai_chat", "anthropic_messages", "gemini_native", "openai_responses"})
_NATIVE = {
    "openai": "openai_chat", "custom": "openai_chat",
    "claudeAPI": "anthropic_messages", "gemini": "gemini_native",
}
_CREDENTIALS = {
    "openai": ("open_ai_api_key", "open_ai_api_base"),
    "claudeAPI": ("claude_api_key", "claude_api_base"),
    "gemini": ("gemini_api_key", "gemini_api_base"),
    "custom": ("custom_api_key", "custom_api_base"),
}
_DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "claudeAPI": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}


def validate_endpoint(api_base, api_key):
    """Validate an explicitly configured endpoint before saving a binding."""
    parsed = urlparse(api_base or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("API base must be an absolute HTTP(S) URL")
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if not local and parsed.scheme != "https":
        raise ValueError("remote API base must use HTTPS")
    if not local and not api_key:
        raise ValueError("API key is required for a remote provider")


def validate_provider_ready(provider):
    validate_endpoint(provider.api_base or _DEFAULT_BASES.get(provider.provider_id),
                      provider.api_key)


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    name: str
    api_base: Optional[str]
    api_key: str
    credential_ref: str
    auth_method: str
    protocol_id: str
    bot_type: str


@dataclass(frozen=True)
class ModelBinding:
    provider_id: str
    model_id: str
    protocol_id: str
    capabilities: tuple = ("text", "tools", "stream")


def _provider_id(bot_type: str) -> str:
    return "openai" if bot_type in (const.CHATGPT, const.OPENAI, "openai") else bot_type


def resolve_provider(provider_id: str, config=None) -> ProviderConfig:
    cfg = config if config is not None else conf()
    provider_id = _provider_id(provider_id or cfg.get("bot_type") or const.CHATGPT)
    if provider_id.startswith("custom:"):
        custom_id = provider_id.partition(":")[2]
        item = next((p for p in cfg.get("custom_providers", [])
                     if isinstance(p, dict) and p.get("id") == custom_id), None)
        if item is None:
            raise ValueError(f"unknown custom provider id: {custom_id}")
        base = (item.get("api_base") or "").strip() or None
        protocol = item.get("protocol_id") or "openai_chat"
        if protocol not in PROTOCOLS:
            raise ValueError(f"unsupported upstream protocol: {protocol}")
        return ProviderConfig(provider_id, item.get("name") or custom_id, base,
                              item.get("api_key") or "", f"custom_providers:{custom_id}",
                              "x-api-key" if protocol == "anthropic_messages" else
                              "x-goog-api-key" if protocol == "gemini_native" else "bearer",
                              protocol, provider_id)
    keys = _CREDENTIALS.get(provider_id)
    if keys is None:
        # Other established Bot classes continue to own their transport until
        # their wire protocols have explicit adapters.
        return ProviderConfig(provider_id, provider_id, None, "", "legacy",
                              "legacy", "legacy", provider_id)
    protocol = (cfg.get("provider_protocols") or {}).get(provider_id) or _NATIVE[provider_id]
    if protocol not in PROTOCOLS:
        raise ValueError(f"unsupported upstream protocol: {protocol}")
    key_field, base_field = keys
    return ProviderConfig(provider_id, provider_id, cfg.get(base_field) or None,
                          cfg.get(key_field) or "", key_field,
                          "x-api-key" if protocol == "anthropic_messages" else
                          "x-goog-api-key" if protocol == "gemini_native" else "bearer",
                          protocol, const.CHATGPT if provider_id == "openai" else provider_id)


def resolve_binding(provider_id=None, model_id=None, protocol_id=None, config=None):
    cfg = config if config is not None else conf()
    provider = resolve_provider(provider_id or cfg.get("bot_type"), cfg)
    model = model_id or cfg.get("model") or const.DEFAULT_MODEL
    protocol = protocol_id or provider.protocol_id
    if protocol not in PROTOCOLS and protocol != "legacy":
        raise ValueError(f"unsupported upstream protocol: {protocol}")
    native = _NATIVE.get(provider.provider_id)
    if native and protocol != native and not provider.api_base:
        # Without an explicit endpoint, selecting a different wire format
        # could send one vendor's credential to another vendor's default host.
        raise ValueError("a protocol override requires an explicit API base")
    if provider.provider_id.startswith("custom:") and not provider.api_base:
        raise ValueError("custom provider requires an API base")
    return provider, ModelBinding(provider.provider_id, model, protocol)
