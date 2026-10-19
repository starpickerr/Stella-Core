"""Plugin Runtime frame codec and JSON-RPC envelope (P1)."""

from __future__ import annotations

import json
import struct

import pytest

from core.plugins.protocol import (
    MAX_FRAME_BYTES,
    FrameError,
    decode_frame,
    encode_frame,
    read_frame,
    write_frame,
)


def test_encode_decode_roundtrip():
    payload = {"jsonrpc": "2.0", "id": "1", "method": "runtime.initialize", "params": {}}
    raw = encode_frame(payload)
    assert raw[:4] == struct.pack(">I", len(raw) - 4)
    assert decode_frame(raw) == payload


def test_rejects_oversized_frame():
    huge = {"jsonrpc": "2.0", "id": "x", "method": "noop", "params": {"blob": "a" * (MAX_FRAME_BYTES)}}
    with pytest.raises(FrameError):
        encode_frame(huge)


def test_rejects_invalid_utf8_payload():
    body = b"\xff\xfe"
    frame = struct.pack(">I", len(body)) + body
    with pytest.raises(FrameError):
        decode_frame(frame)


def test_rejects_duplicate_json_keys():
    # object_pairs_hook must reject duplicates
    body = b'{"jsonrpc":"2.0","id":"1","id":"2","method":"x","params":{}}'
    frame = struct.pack(">I", len(body)) + body
    with pytest.raises(FrameError):
        decode_frame(frame)


def test_write_read_stream_roundtrip(tmp_path):
    path = tmp_path / "pipe.bin"
    msg = {"jsonrpc": "2.0", "id": "a", "result": {"ok": True}}
    with path.open("wb") as out:
        write_frame(out, msg)
    with path.open("rb") as inp:
        assert read_frame(inp) == msg


def test_zero_length_frame_rejected():
    with pytest.raises(FrameError):
        decode_frame(struct.pack(">I", 0))
