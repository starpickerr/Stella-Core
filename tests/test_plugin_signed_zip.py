"""Signed ZIP install path for remote catalog entries (D / R10)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from core.plugins.distribution import fetch_and_install_from_catalog
from core.plugins.package_ops import PackageStore
from core.plugins.signing import sign_bytes, verify_signature, write_signed_zip, unpack_signed_zip


def test_roundtrip_sign_and_verify():
    payload = b"hello-plugin"
    sig = sign_bytes(payload, secret=b"test-secret")
    assert verify_signature(payload, sig, secret=b"test-secret")
    assert not verify_signature(payload, sig, secret=b"wrong")


def test_signed_zip_install_from_catalog_url(tmp_path, monkeypatch):
    sample = Path("samples/plugins/alpha")
    archive = tmp_path / "alpha.zip"
    secret = b"stella-dev-signing-key"
    write_signed_zip(sample, archive, secret=secret)

    # Local HTTP-ish: point url at file:// and monkeypatch urlretrieve
    def _retrieve(url, dest):
        Path(dest).write_bytes(archive.read_bytes())
        return dest, {}

    monkeypatch.setattr("core.plugins.distribution.urllib.request.urlretrieve", _retrieve)

    # Digest in catalog is of the unpacked tree (same filters as production).
    from core.plugins.package_ops import _sha256_tree

    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": "stella.sample.alpha",
                "hostApi": "^1.0.0",
                "path": str(tmp_path / "missing-dir"),
                "url": "https://example.test/alpha.zip",
                "sha256": _sha256_tree(sample),
                "signatureAlg": "hmac-sha256",
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", secret.decode("ascii"))
    store = PackageStore(tmp_path / "pkg")
    result = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
    )
    assert result["status"] == "installed"
    assert store.current_package("stella.sample.alpha") is not None


def test_bad_signature_rejects(tmp_path, monkeypatch):
    sample = Path("samples/plugins/alpha")
    archive = tmp_path / "alpha.zip"
    write_signed_zip(sample, archive, secret=b"correct")
    monkeypatch.setattr(
        "core.plugins.distribution.urllib.request.urlretrieve",
        lambda url, dest: (Path(dest).write_bytes(archive.read_bytes()), {}),
    )
    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": "stella.sample.alpha",
                "hostApi": "^1.0.0",
                "path": str(tmp_path / "missing"),
                "url": "https://example.test/alpha.zip",
                "sha256": "0" * 64,
                "signatureAlg": "hmac-sha256",
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", "wrong-secret")
    store = PackageStore(tmp_path / "pkg")
    result = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
    )
    assert result["status"] in {"signature_invalid", "digest_mismatch", "failed"}
