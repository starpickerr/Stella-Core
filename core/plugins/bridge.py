"""Host-side Bridge identity binding for restricted plugin UI frames."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class BridgeChannel:
    plugin_id: str
    user_id: str
    instance_id: str
    generation: int
    page_id: str
    channel_nonce: str


class BridgeRegistry:
    """Binds page channels; messages cannot override identity fields."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._channels: dict[str, BridgeChannel] = {}

    def open(
        self,
        *,
        plugin_id: str,
        user_id: str,
        instance_id: str,
        generation: int,
        page_id: str,
    ) -> BridgeChannel:
        nonce = secrets.token_urlsafe(16)
        channel = BridgeChannel(
            plugin_id=plugin_id,
            user_id=user_id,
            instance_id=instance_id,
            generation=generation,
            page_id=page_id,
            channel_nonce=nonce,
        )
        with self._lock:
            self._channels[nonce] = channel
        return channel

    def resolve(self, channel_nonce: str) -> BridgeChannel:
        with self._lock:
            channel = self._channels.get(channel_nonce)
        if channel is None:
            raise PermissionError("unknown or revoked bridge channel")
        return channel

    def authorize_invoke(
        self,
        channel_nonce: str,
        *,
        plugin_id: str,
        generation: int,
        page_id: str,
    ) -> BridgeChannel:
        channel = self.resolve(channel_nonce)
        if (
            channel.plugin_id != plugin_id
            or channel.generation != generation
            or channel.page_id != page_id
        ):
            raise PermissionError("bridge identity mismatch")
        return channel

    def close(self, channel_nonce: str) -> None:
        with self._lock:
            self._channels.pop(channel_nonce, None)

    def revoke_generation(self, plugin_id: str, generation: int) -> None:
        with self._lock:
            drop = [
                nonce
                for nonce, ch in self._channels.items()
                if ch.plugin_id == plugin_id and ch.generation == generation
            ]
            for nonce in drop:
                del self._channels[nonce]
