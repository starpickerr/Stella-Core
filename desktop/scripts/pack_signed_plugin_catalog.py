#!/usr/bin/env python3
"""Pack Stella-Plugins into signed ZIPs + Core-only plugin-catalog.json.

Replaces unpacked plugin-seed trees. Catalog entries use relative ``url`` values
pointing at ``plugin-packages/{domain}.zip`` next to the catalog file.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
RESOURCES = DESKTOP / "resources"
PACKAGES = RESOURCES / "plugin-packages"
CATALOG_OUT = RESOURCES / "plugin-catalog.json"
SECRET_FILE = RESOURCES / "plugin-signing.secret"
PLUGINS_ROOT = ROOT.parent / "Stella-Plugins" / "plugins"
OFFICIAL = ROOT.parent / "Stella-Plugins" / "catalog" / "official.json"

DOMAINS = ("bills", "calendar", "tasks", "email", "elearning", "briefing", "automation")
DEFAULT_SECRET = b"stella-first-edition-plugin-catalog"


def tree_digest(root: Path) -> str:
    sys.path.insert(0, str(ROOT))
    from core.plugins.distribution import _package_files

    h = hashlib.sha256()
    for path in _package_files(root):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()

def main() -> int:
    if not PLUGINS_ROOT.is_dir():
        print(f"missing Stella-Plugins at {PLUGINS_ROOT}", file=sys.stderr)
        return 1
    sys.path.insert(0, str(ROOT))
    from core.plugins.signing import write_signed_zip

    secret = os.environ.get("STELLA_PLUGIN_SIGNING_SECRET", "").encode("utf-8") or DEFAULT_SECRET
    RESOURCES.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_bytes(secret + (b"" if secret.endswith(b"\n") else b"\n"))

    seed = RESOURCES / "plugin-seed"
    if seed.exists():
        import shutil

        shutil.rmtree(seed)

    if PACKAGES.exists():
        import shutil

        shutil.rmtree(PACKAGES)
    PACKAGES.mkdir(parents=True)

    official = json.loads(OFFICIAL.read_text(encoding="utf-8")) if OFFICIAL.is_file() else {"coreApi": "1.0.0"}
    entries = []
    for domain in DOMAINS:
        src = PLUGINS_ROOT / domain
        if not src.is_dir():
            print(f"missing plugin {src}", file=sys.stderr)
            return 1
        manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
        archive = PACKAGES / f"{domain}.zip"
        write_signed_zip(src, archive, secret=secret)
        entry = {
            "pluginId": f"stella.{domain}",
            "hostApi": manifest.get("hostApi", "^1.0.0"),
            "version": manifest["version"],
            "url": f"plugin-packages/{domain}.zip",
            "sha256": tree_digest(src),
            "signatureAlg": "hmac-sha256",
        }
        entries.append(entry)
        print(f"packed {domain} -> {archive.name} sha256={entry['sha256'][:12]}…")

    catalog = {"coreApi": official.get("coreApi", "1.0.0"), "plugins": entries}
    CATALOG_OUT.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {CATALOG_OUT} ({len(entries)} signed packages, no plugin-seed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
