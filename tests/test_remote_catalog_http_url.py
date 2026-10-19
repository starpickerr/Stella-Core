"""Catalog ``url`` may be an absolute http(s) location (remote publish shape).

Uses a temporary local HTTP server so the production fetch path is exercised
without requiring a published CDN or push authorization.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.plugins.bootstrap import bootstrap_default_plugins
from core.plugins.distribution import _package_files, fetch_and_install_from_catalog
from core.plugins.package_ops import PackageStore
from core.plugins.signing import write_signed_zip

SECRET = b"stella-first-edition-plugin-catalog"


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in _package_files(root):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _plugins_root() -> Path:
    workspace = Path("stella-plugins-workspace/plugins")
    if workspace.is_dir():
        return workspace
    return Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins"


def test_absolute_http_url_installs_signed_package(tmp_path, monkeypatch):
    plugins = _plugins_root()
    src = plugins / "bills"
    assert src.is_dir()
    packages = tmp_path / "cdn" / "plugin-packages"
    packages.mkdir(parents=True)
    archive = packages / "bills.zip"
    write_signed_zip(src, archive, secret=SECRET)
    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": "stella.bills",
                "hostApi": "^1.0.0",
                "version": json.loads((src / "plugin.json").read_text(encoding="utf-8"))["version"],
                "url": "REPLACE",
                "sha256": _tree_digest(src),
                "signatureAlg": "hmac-sha256",
            }
        ],
    }
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", SECRET.decode("ascii"))

    root = tmp_path / "cdn"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, *_args, **_kwargs):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        catalog["plugins"][0]["url"] = f"http://{host}:{port}/plugin-packages/bills.zip"
        catalog_path = tmp_path / "remote-catalog.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        store = PackageStore(tmp_path / "pkg")
        result = fetch_and_install_from_catalog(
            catalog_path=catalog_path,
            plugin_id="stella.bills",
            package_store=store,
        )
        assert result["status"] == "installed"
        assert store.current_package("stella.bills") is not None
        boot = bootstrap_default_plugins(
            catalog_path=catalog_path,
            package_store=store,
            plugin_ids=["stella.bills"],
        )
        assert boot["status"] == "ok"
    finally:
        server.shutdown()
