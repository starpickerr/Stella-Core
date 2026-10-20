"""Built-in Provider adapters — agentId + accessMode (D24).

providerLocalId remains the adapter registry key and compatibility alias.
"""

from __future__ import annotations

from domain.providers.base import ProviderAdapter, UnsupportedCapability
from domain.providers.claude_code import ClaudeCodeProvider
from domain.providers.codex_app_server import CodexAppServerProvider
from domain.providers.codex_cli import CodexCliProvider
from domain.providers.cursor_acp import CursorAcpProvider
from domain.providers.cursor_cli import CursorCliProvider

ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "codex-app-server": CodexAppServerProvider,
    "codex-cli": CodexCliProvider,
    "cursor-acp": CursorAcpProvider,
    "cursor-cli": CursorCliProvider,
    "claude-code": ClaudeCodeProvider,
}

# Historical / display aliases → (agentId, accessMode, providerLocalId)
LEGACY_IDENTITY: dict[str, tuple[str, str, str]] = {
    "codex-app-server": ("codex", "app-server", "codex-app-server"),
    "codex-cli": ("codex", "cli", "codex-cli"),
    "cursor-acp": ("cursor", "acp", "cursor-acp"),
    "cursor-cli": ("cursor", "cli", "cursor-cli"),
    "claude-code": ("claude-code", "cli", "claude-code"),
}

DEFAULT_CATALOG = [
    {
        "providerLocalId": "codex-app-server",
        "agentId": "codex",
        "accessMode": "app-server",
        "displayName": "Codex · App Server",
        "binaryHints": ["codex"],
    },
    {
        "providerLocalId": "codex-cli",
        "agentId": "codex",
        "accessMode": "cli",
        "displayName": "Codex · CLI exec",
        "binaryHints": ["codex"],
    },
    {
        "providerLocalId": "cursor-acp",
        "agentId": "cursor",
        "accessMode": "acp",
        "displayName": "Cursor · ACP",
        "binaryHints": ["agent", "cursor-agent", "cursor"],
    },
    {
        "providerLocalId": "cursor-cli",
        "agentId": "cursor",
        "accessMode": "cli",
        "displayName": "Cursor · CLI print",
        "binaryHints": ["agent", "cursor-agent", "cursor"],
    },
    {
        "providerLocalId": "claude-code",
        "agentId": "claude-code",
        "accessMode": "cli",
        "displayName": "Claude Code · CLI",
        "binaryHints": ["claude"],
    },
]


def resolve_identity(provider_local_id: str) -> tuple[str, str, str]:
    if provider_local_id in LEGACY_IDENTITY:
        return LEGACY_IDENTITY[provider_local_id]
    cls = ADAPTERS.get(provider_local_id)
    if cls is None:
        raise KeyError(f"unknown provider: {provider_local_id}")
    return (cls.agent_id, cls.access_mode, provider_local_id)


def get_adapter(
    provider_local_id: str,
    *,
    binary_path: str | None = None,
    settings: dict | None = None,
) -> ProviderAdapter:
    cls = ADAPTERS.get(provider_local_id)
    if cls is None:
        raise KeyError(f"unknown provider: {provider_local_id}")
    return cls(binary_path=binary_path, settings=settings or {})


def get_adapter_for_agent(
    agent_id: str,
    access_mode: str,
    *,
    binary_path: str | None = None,
    settings: dict | None = None,
) -> ProviderAdapter:
    for local_id, (aid, mode, _) in LEGACY_IDENTITY.items():
        if aid == agent_id and mode == access_mode:
            return get_adapter(local_id, binary_path=binary_path, settings=settings)
    raise KeyError(f"unknown agent/mode: {agent_id}/{access_mode}")


__all__ = [
    "ADAPTERS",
    "DEFAULT_CATALOG",
    "LEGACY_IDENTITY",
    "ProviderAdapter",
    "UnsupportedCapability",
    "get_adapter",
    "get_adapter_for_agent",
    "resolve_identity",
]
