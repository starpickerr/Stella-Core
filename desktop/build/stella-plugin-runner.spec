# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the dedicated ``stella-plugin-runner`` (onedir).

The runner is the plugin worker process: it speaks the framed JSON-RPC
protocol on stdin/stdout and loads one plugin entry from STELLA_PLUGIN_ROOT.
It is frozen separately from ``app.py`` so that starting a plugin never
re-enters app business init, the legacy plugin watcher, the scheduler, or
shared run-record recovery (R01).

Entry:   core/plugins/runner/cli.py
Bundled: only core.plugins.{protocol,contract,manifest,registry,runner}
Excluded: app/application/agent/channel/models/... (see `excludes`).

Build from the repo root:
    pyinstaller desktop/build/stella-plugin-runner.spec --noconfirm \
        --distpath desktop/build/dist --workpath desktop/build/build-work

Output: desktop/build/dist/stella-plugin-runner/stella-plugin-runner
Ship it next to the frozen backend (`stella-backend/`) or point
STELLA_PLUGIN_RUNNER at the binary; see core.plugins.host.resolve_runner_command.
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))


def rp(*parts):
    return os.path.join(ROOT, *parts)


# cli.py imports the real runner lazily, so static analysis can't see it.
hiddenimports = [
    'core',
    'core.plugins',
    'core.plugins.protocol',
    'core.plugins.contract',
    'core.plugins.manifest',
    'core.plugins.registry',
    'core.plugins.runner',
    'core.plugins.runner.__main__',
    # Plugin entries are loaded from disk via importlib and commonly use these.
    'json',
    'datetime',
    'hashlib',
    'uuid',
    'zoneinfo',
    # Domain plugins (bills/tasks/…) open SQLite; freeze must ship the stdlib module.
    'sqlite3',
    '_sqlite3',
]

# Business stack that must never be reachable from the runner binary.
excludes = [
    'app',
    'application',
    'agent',
    'channel',
    'bridge',
    'models',
    'voice',
    'plugins',            # legacy PluginManager package (top-level, not core.plugins)
    'cli',
    'common',
    'config',
    'core.services',
    'core.plugins.host',  # host side only; runner never spawns workers
    'core.plugins.bridge',
    'core.plugins.runtime_hub',
    'core.plugins.package_ops',
    'core.plugins.distribution',
    'core.plugins.mcp',
    'core.plugins.authz',
    'tests',
    'pip',
    'pytest',
    'tkinter',
    'playwright',
    'lark_oapi',
]

block_cipher = None

a = Analysis(
    [rp('core', 'plugins', 'runner', 'cli.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='stella-plugin-runner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='stella-plugin-runner',
)
