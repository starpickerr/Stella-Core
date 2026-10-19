# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Stella desktop backend (onedir).

Produces a self-contained `stella-backend` folder that the Electron app
spawns directly, so end users don't need Python installed.

onedir is chosen over onefile because the backend reads data files via paths
relative to the source tree (e.g. config-template.json, skills/);
onedir preserves that layout, while onefile's temp-extraction would break it.

Build from the repo root:
    pyinstaller desktop/build/stella-backend.spec --noconfirm

Sibling packaging (G5): the plugin worker is NOT launched from this bundle.
`desktop/build/stella-plugin-runner.spec` freezes `core/plugins/runner/cli.py`
into a separate `stella-plugin-runner/` onedir that must ship NEXT TO
`stella-backend/` (or be pointed at via STELLA_PLUGIN_RUNNER); the host resolves
it in core.plugins.host.resolve_runner_command. Re-launching this backend as a
worker would re-enter app init, the legacy PluginManager watcher and scheduler
recovery (R01). Business packages (bills/tasks/calendar/email/elearning/
briefing/automation) are NOT embedded here: bytes come from Stella-Plugins via
resources/default-plugins.json. DMG integration of the runner is still open.
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Resolve the repo root from the spec's own location (desktop/build/ -> root),
# independent of the current working directory. PyInstaller exposes SPECPATH.
ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))


def rp(*parts):
    """Absolute path under the repo root."""
    return os.path.join(ROOT, *parts)

# --- Hidden imports -------------------------------------------------------
# Channels are imported dynamically by channel_factory via string names, so
# PyInstaller's static analysis can't see them. List every channel we ship.
# Feishu (channel.feishu.feishu_channel) is bundled so the channel code is
# present; its heavy lark_oapi SDK is deliberately NOT bundled — see the
# `excludes` note below and channel/feishu/lark_install.py, which downloads a
# trimmed bundle the first time the user enables Feishu (fixes
# starpickerr/Stella#2987: "客户端没有飞书通道").
hiddenimports = [
    # channels (dynamic import in channel/channel_factory.py)
    'channel.desktop.desktop_channel',
    'channel.terminal.terminal_channel',
    'channel.weixin.weixin_channel',
    'channel.wechatmp.wechatmp_channel',
    'channel.wechatcom.wechatcomapp_channel',
    'channel.wechat_kf.wechat_kf_channel',
    'channel.feishu.feishu_channel',
    'channel.dingtalk.dingtalk_channel',
    'channel.wecom_bot.wecom_bot_channel',
    'channel.qq.qq_channel',
    'channel.telegram.telegram_channel',
    'channel.slack.slack_channel',
    'channel.discord.discord_channel',
]

# Agent tools and model providers are imported lazily in places; collect their
# submodules so nothing is missed at runtime.
hiddenimports += collect_submodules('agent.tools')
# agent.calendar / agent.briefing are no longer blanket-collected (G5): neither
# package uses dynamic imports, so the in-process legacy fallback modules are
# pulled in by static analysis only where Core still imports them. The Apple
# EventKit bridge must stay in Core (it needs host OS access), so list it
# explicitly in case it is only reached lazily.
hiddenimports += [
    'agent.calendar.apple_bridge',
    'agent.calendar.apple_preview',
    'agent.calendar.apple_runtime',
    'agent.calendar.apple_sync',
    'common.timezones',
]
hiddenimports += collect_submodules('models')
hiddenimports += collect_submodules('voice')
hiddenimports += collect_submodules('bridge')

# Legacy chat-command plugin framework (top-level `plugins/`). DesktopChannel ->
# ChatChannel imports `from plugins import *`, and desktop mode loads plugins (in a
# background thread) so command plugins like stella_cli/godcmd (/status, #help)
# work. This is NOT the Plugin Runtime: business plugins, package install, the
# registry and worker lifecycle live in `core.plugins` (see core/plugins/__init__.py)
# and run in the separate stella-plugin-runner. The legacy PluginManager only
# imports command plugins from ./plugins and skips plugin.json packages
# (see plugins/plugin_manager.py). Plugin modules are imported dynamically by
# name in scan_plugins(), so list them explicitly. The `cli` package is a
# stella_cli dependency (`from cli import ...`).
hiddenimports += [
    'plugins',
    'plugins.event',
    'plugins.plugin',
    'plugins.plugin_manager',
]
hiddenimports += collect_submodules('plugins')

# `cli` powers stella_cli's slash commands (`stella skill install`, `stella status`, …).
# Its command modules are imported lazily inside functions, so static analysis
# misses them. collect_submodules('cli') alone proved unreliable (a build can
# end up with `cli` but not `cli.commands`), so list the command modules
# explicitly AND ship the package as data (see datas) as a belt-and-suspenders.
hiddenimports += collect_submodules('cli')
hiddenimports += [
    'cli',
    'cli.cli',
    'cli.utils',
    'cli.commands',
    'cli.commands.skill',
    'cli.commands.process',
    'cli.commands.context',
    'cli.commands.install',
    'cli.commands.knowledge',
]

# certifi carries the CA bundle the bundled OpenSSL lacks (see common/ssl_certs).
# requests pulls it in, but naming it keeps stdlib TLS working even if that ever
# stops being true — without it every HTTPS call through urllib/websockets fails.
hiddenimports += ['certifi']

# zoneinfo falls back to the tzdata package when the OS has no IANA database
# (frozen Windows builds, minimal Linux images). Without these files even UTC
# fails and Apple calendar import surfaces as "invalid repeat_timezone".
hiddenimports += ['tzdata']

# agent.tools.search_files does `import regex as re` at module import time.
hiddenimports += ['regex']

# Third-party SDKs that use lazy/conditional imports internally.
hiddenimports += collect_submodules('dashscope')
hiddenimports += [
    'tiktoken_ext',
    'tiktoken_ext.openai_public',
]

# Document parsing libs. The read / web_fetch tools import these lazily inside
# functions (e.g. `from pypdf import PdfReader`), so PyInstaller's static
# analysis misses them and they'd be dropped from the bundle — leaving the
# desktop client unable to read PDF/Word/Excel/PPT. List them explicitly.
hiddenimports += [
    'pypdf',
    'docx',           # python-docx
    'pptx',           # python-pptx
    'openpyxl',
]
hiddenimports += collect_submodules('pypdf')
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('pptx')
hiddenimports += collect_submodules('openpyxl')

# Playwright powers the browser tool. Only the pure-Python package + its bundled
# Node driver are shipped (~10-15MB); the ~150MB Chromium binary is NOT bundled
# and is either satisfied by the user's system Chrome/Edge (preferred, zero
# download) or downloaded on demand into ~/.stella/ms-playwright at first use.
# Playwright imports its transport/driver lazily, so list submodules explicitly.
hiddenimports += ['playwright', 'playwright.sync_api', 'playwright._impl']
hiddenimports += collect_submodules('playwright')

# --- Data files -----------------------------------------------------------
# Runtime-read files/dirs that must travel with the executable. Paths are
# (source, dest_dir_in_bundle).
datas = [
    (rp('config-template.json'), '.'),
    # First-boot plugin bootstrap list (bytes still come from Stella-Plugins catalog).
    (rp('resources', 'default-plugins.json'), 'resources'),
    (rp('skills'), 'skills'),
    # Legacy PluginManager.scan_plugins() walks the on-disk ./plugins dir at
    # runtime for chat-command plugins (it doesn't rely solely on imports), so
    # ship that directory. Runtime ability to load external plugins is unchanged:
    # that path is core.plugins (PluginRegistry/PluginSession) + the runner, which
    # reads packages from the user data dir, not from this bundle.
    (rp('plugins'), 'plugins'),
    # Ship the `cli` package as loose files too: onedir adds _internal to
    # sys.path, so `import cli.commands.*` resolves even if PyInstaller's
    # submodule collection misses the lazily-imported command modules.
    (rp('cli'), 'cli'),
    # Briefing legacy fallback still reads these SQL files until agent.briefing is
    # deleted (plugin copies live in the stella.briefing package). Remove once the
    # in-process fallback is gone.
    (rp('agent', 'briefing', 'schema.sql'), 'agent/briefing'),
    (rp('agent', 'briefing', 'actions.sql'), 'agent/briefing'),
    # Scaffold templates for first-run subagent assets (README + example).
    (rp('agent', 'subagent', 'assets'), 'agent/subagent/assets'),
]

# Some libraries (tiktoken encodings, etc.) ship data files.
datas += collect_data_files('tiktoken_ext', include_py_files=False)

# tzdata's zoneinfo trees are package data, not importable modules.
datas += collect_data_files('tzdata')

# Explicit CA bundle path for frozen OpenSSL (belt-and-suspenders with hook-certifi).
datas += collect_data_files('certifi')

# python-docx / python-pptx bundle template files (default.docx / default.pptx,
# content-type XML) inside their packages; they're loaded at import/parse time,
# so ship them or document parsing fails in the frozen build.
datas += collect_data_files('docx')
datas += collect_data_files('pptx')

# Playwright ships its Node.js driver + package.json under playwright/driver/.
# These are NOT Python modules, so hiddenimports won't pull them in — collect
# them as data or `playwright install` / launching fails in the frozen build.
# include_py_files=True is required: the driver dir contains .py entrypoints.
datas += collect_data_files('playwright', include_py_files=True)

# --- Excludes -------------------------------------------------------------
# Keep the bundle lean: drop tests/docs and dev-only packages.
#
# Feishu's lark_oapi (~122MB unpacked) is intentionally EXCLUDED here. The first
# time a user enables the Feishu channel, channel/feishu/lark_install.py
# downloads a trimmed, pure-Python bundle (~1MB, built by
# desktop/build/build-feishu-vendor.py) into ~/.stella/feishu_vendor and adds it to
# sys.path. This keeps the base download small while Feishu still works out of
# the box after a one-time fetch (fixes starpickerr/Stella#2987).
excludes = [
    'lark_oapi',          # Feishu SDK — fetched on demand, NOT bundled (see above)
    'tests',
    'pip',
    'pytest',
    # NOTE: playwright is now BUNDLED (pure-Python package + Node driver, ~10-15MB)
    # so the browser tool works out of the box on desktop. The heavy Chromium
    # binary is still NOT bundled: it comes from the user's system Chrome/Edge or
    # is downloaded on demand into ~/.stella/ms-playwright. See browser_env.py.
]

block_cipher = None

a = Analysis(
    [rp('app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
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
    name='stella-backend',
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
    name='stella-backend',
)
