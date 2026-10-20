"""Shared Provider adapter contract (design §3)."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator


class UnsupportedCapability(RuntimeError):
    def __init__(self, capability: str):
        super().__init__(f"UNSUPPORTED_CAPABILITY:{capability}")
        self.capability = capability


class ProviderAdapter(ABC):
    """One concrete accessMode implementation for an agentId (D24)."""

    provider_local_id: str
    agent_id: str = ""
    access_mode: str = ""
    adapter_version: str = "1.0.0"
    binary_hints: tuple[str, ...] = ()

    def __init__(self, *, binary_path: str | None = None, settings: dict | None = None):
        self.binary_path = binary_path
        self.settings = dict(settings or {})

    def resolve_binary(self) -> str | None:
        if self.binary_path:
            path = Path(self.binary_path)
            return str(path) if path.is_file() else None
        for name in self.binary_hints:
            found = shutil.which(name)
            if found:
                return found
        return None

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def probe(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def start(self, task: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        ...

    @abstractmethod
    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        ...

    def reattach(self, external_session_ref: str) -> dict[str, Any]:
        raise UnsupportedCapability("reattach")
