"""HMAC-SHA256 signed plugin ZIP packages (first-edition trusted catalog)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import zipfile
from pathlib import Path


def sign_bytes(payload: bytes, *, secret: bytes) -> str:
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_signature(payload: bytes, signature_hex: str, *, secret: bytes) -> bool:
    expected = sign_bytes(payload, secret=secret)
    return hmac.compare_digest(expected, signature_hex)


def signing_secret_from_env() -> bytes:
    raw = os.environ.get("STELLA_PLUGIN_SIGNING_SECRET", "").encode("utf-8")
    if not raw:
        raise RuntimeError("STELLA_PLUGIN_SIGNING_SECRET is required for signed packages")
    return raw


def write_signed_zip(source_dir: Path, archive: Path, *, secret: bytes) -> Path:
    """Pack ``source_dir`` into a ZIP with sibling ``.sig`` metadata member."""
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    buf_path = archive.with_suffix(".unsigned.zip")
    with zipfile.ZipFile(buf_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root = Path(source_dir)
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(root).as_posix())
    payload = buf_path.read_bytes()
    signature = sign_bytes(payload, secret=secret)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.zip", payload)
        zf.writestr(
            "signature.json",
            json.dumps({"alg": "hmac-sha256", "signature": signature}, indent=2) + "\n",
        )
    buf_path.unlink(missing_ok=True)
    return archive


def unpack_signed_zip(archive: Path, dest: Path, *, secret: bytes | None = None) -> Path:
    """Verify signature and extract the inner package tree to ``dest``."""
    secret = secret if secret is not None else signing_secret_from_env()
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive, "r") as zf:
        meta = json.loads(zf.read("signature.json"))
        payload = zf.read("package.zip")
    if meta.get("alg") != "hmac-sha256":
        raise ValueError(f"unsupported signature alg: {meta.get('alg')}")
    if not verify_signature(payload, meta["signature"], secret=secret):
        raise PermissionError("plugin package signature invalid")
    inner = dest / "_inner.zip"
    inner.write_bytes(payload)
    out = dest / "content"
    out.mkdir()
    with zipfile.ZipFile(inner, "r") as zf:
        zf.extractall(out)
    inner.unlink(missing_ok=True)
    return out
