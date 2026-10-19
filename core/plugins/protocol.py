"""Length-prefixed JSON-RPC frames for Core ↔ plugin runner IPC."""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO, Mapping, MutableMapping

MAX_FRAME_BYTES = 1 * 1024 * 1024  # 1 MiB JSON body


class FrameError(ValueError):
    """Invalid frame length, encoding, or JSON shape."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise FrameError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def encode_frame(payload: Mapping[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if len(body) == 0 or len(body) > MAX_FRAME_BYTES:
        raise FrameError(f"frame body length out of range: {len(body)}")
    return struct.pack(">I", len(body)) + body


def decode_frame(frame: bytes) -> dict[str, Any]:
    if len(frame) < 4:
        raise FrameError("truncated frame header")
    (length,) = struct.unpack(">I", frame[:4])
    if length == 0 or length > MAX_FRAME_BYTES:
        raise FrameError(f"invalid frame length: {length}")
    body = frame[4:]
    if len(body) != length:
        raise FrameError(f"frame body length mismatch: expected {length}, got {len(body)}")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameError("invalid UTF-8 in frame body") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise FrameError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FrameError("JSON-RPC frame must be an object")
    return value


def write_frame(stream: BinaryIO, payload: Mapping[str, Any]) -> None:
    stream.write(encode_frame(payload))
    stream.flush()


def read_frame(stream: BinaryIO) -> dict[str, Any]:
    header = stream.read(4)
    if len(header) != 4:
        raise FrameError("unexpected EOF reading frame header")
    (length,) = struct.unpack(">I", header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise FrameError(f"invalid frame length: {length}")
    body = stream.read(length)
    if len(body) != length:
        raise FrameError("unexpected EOF reading frame body")
    return decode_frame(header + body)


def make_request(method: str, params: Mapping[str, Any], request_id: str) -> dict[str, Any]:
    if not request_id:
        raise FrameError("request id must be a non-empty string")
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}


def make_result(request_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def make_error(request_id: str | None, code: int, message: str) -> dict[str, Any]:
    payload: MutableMapping[str, Any] = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
    }
    if request_id is not None:
        payload["id"] = request_id
    return dict(payload)
