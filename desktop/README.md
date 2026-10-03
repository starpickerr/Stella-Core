# Stella Desktop

Cross-platform desktop client for Stella, built with Electron + React + TypeScript.

Stella uses the Electron client and its private loopback Python API. The old Web frontend is removed.

The **Briefing** page supports IMAP mailbox setup, daily email briefings, history, item status updates, and filter rules. See [the briefing guide](../agent/briefing/README.md) for setup, scheduling, and development checks.

## Development

### Prerequisites

- Node.js 18+
- npm or yarn
- Python 3.7+ (for the backend)

### Setup

```bash
cd desktop
npm install
```

### Run in Development

Build the current renderer and main process, then start Electron:

```bash
npm run dev
```

For hot renderer reload, run:

```bash
# Terminal 1: Start Vite dev server
npm run dev:renderer

# Terminal 2: Start Electron (after renderer is ready)
npm run dev:main
```

The app starts the Python backend from the parent directory. `npm run dev` always loads the freshly built renderer; only `dev:main` opts into Vite on port 5173. Development and installed builds use the same `~/.stella` settings and workspace data. Starting either build replaces the running desktop instance before opening that data store. Existing `~/.stella-dev` files remain on disk but are no longer read.

### Adding a second Agent to an existing installation

The original local user's business data stays in the default Agent workspace
until it is copied to the canonical `users/local-default` directory. Before
enabling a second Agent, quit Stella and stop its Python backend, then run from
the repository root:

```bash
python -m scripts.migrate_user_data --confirm-offline
```

The migration copies user data, uses SQLite backups for databases, and retains
the original files. It activates the new path only after the copy completes.
If the copy has not been activated, a second Agent cannot open the legacy
local user's business data.

### Checks

```bash
npm run typecheck
```

`npm run build` checks both renderer and main-process types before compiling.

### Build

```bash
# Build for current platform
npm run dist

# Build for macOS only
npm run dist:mac

# Build for Windows only
npm run dist:win
```

Build outputs are placed in the `release/` directory.

### Build Stella.app from source (macOS)

Run the complete build from the repository root so the packaged application
contains the latest Python backend and Electron UI:

```bash
# 1. Install Electron dependencies (first build, or after package changes)
cd desktop
npm install
cd ..

# 2. Freeze the Python backend
bash desktop/build/build-backend.sh

# 3. Build Stella.app and the .dmg installer
cd desktop
npm run dist:mac
```

The outputs are:

```text
desktop/release/mac-arm64/Stella.app
desktop/release/Stella-<version>-arm64.dmg
```

That `<version>` comes from the repo-root `VERSION` file. The steps above rebuild the current number; they do not bump a release.

### Version numbers

One source: the repo-root `VERSION` file (`X.Y.Z`, no `v` prefix).

**Do not run `npm version`.** `npm run build` / `npm run dist:mac` run `scripts/sync-version.mjs`, which overwrites `desktop/package.json` (and the lockfile version fields) from `VERSION`. Bumping only `package.json` is discarded.


| Place                            | Form                           | Example                  |
| -------------------------------- | ------------------------------ | ------------------------ |
| `VERSION`                        | `X.Y.Z`                        | `0.0.1`                  |
| `desktop/package.json` `version` | same `X.Y.Z` (copied at build) | `0.0.1`                  |
| git tag                          | `v` + that number              | `v0.0.1`                 |
| dmg name                         | `Stella-<X.Y.Z>-<arch>.dmg`    | `Stella-0.0.1-arm64.dmg` |


The packaged app compares `app.getVersion()` (`X.Y.Z`) against GitHub Release tags (`vX.Y.Z`). Drafts, GitHub prereleases, and tags that are not exactly `vX.Y.Z` are ignored.

```bash
# 1. Bump VERSION only (X.Y.Z, no v prefix)
echo 0.0.2 > VERSION

# 2. First build, or after desktop dependency changes
cd desktop && npm install && cd ..

# 3. Freeze the Python backend, then package the macOS dmg (dmg only; no zip)
bash desktop/build/build-backend.sh
cd desktop && npm run dist:mac && cd ..

# 4. Commit the synced version files, tag, push
git add VERSION desktop/package.json desktop/package-lock.json
git commit -m "release: v0.0.2"
git tag v0.0.2
git push && git push --tags
```

Then on GitHub, create a **published** (not draft, not pre-release) Release for tag `v0.0.2`, upload `desktop/release/Stella-0.0.2-arm64.dmg` (and the Intel dmg if you built it), and write the notes.

The running app checks GitHub Releases and **prompts** you to open the download; it does not install or restart in the background. These builds are unsigned: first launch on macOS needs a right-click → Open.

If GitHub downloads require the macOS system proxy, expose it to the build
process explicitly:

```bash
HTTP_PROXY=http://127.0.0.1:7890 \
HTTPS_PROXY=http://127.0.0.1:7890 \
NO_PROXY=127.0.0.1,localhost \
npm run dist:mac
```

## Architecture

```
desktop/
├── src/
│   ├── main/              # Electron main process
│   │   ├── index.ts       # Window management, IPC
│   │   ├── python-manager.ts  # Python backend lifecycle
│   │   ├── updater.ts     # GitHub Releases check; opens download, no in-app install
│   │   └── preload.ts     # Context bridge for renderer
│   └── renderer/          # React UI (Vite)
│       └── src/
│           ├── api/       # HTTP client for backend APIs
│           ├── components/ # Reusable UI components
│           ├── hooks/     # React hooks
│           ├── pages/     # Page components
│           └── types.ts   # TypeScript types
├── resources/             # App icons
├── package.json           # Dependencies and build config
└── vite.config.ts         # Vite config
```

### How it Works

1. Electron main process starts and creates the app window
2. It spawns the Python backend (`app.py`) as a child process
3. The React UI communicates with the Python backend via HTTP APIs
4. SSE (Server-Sent Events) is used for streaming chat responses and live logs
