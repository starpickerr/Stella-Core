# Stella Desktop

Cross-platform desktop client for Stella, built with Electron + React + TypeScript.

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

Start the renderer dev server and Electron together:

```bash
npm run dev
```

Or run them separately:

```bash
# Terminal 1: Start Vite dev server
npm run dev:renderer

# Terminal 2: Start Electron (after renderer is ready)
npm run dev:main
```

The app will automatically start the Python backend from the parent directory.

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
contains the latest Python backend, Web console, and Electron UI:

```bash
# 1. Install Electron dependencies (first build, or after package changes)
cd desktop
npm install
cd ..

# 2. Freeze the Python backend and Web assets
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

### Publish a GitHub Release (v0.0.1 and later)

1. Set the product version in the repo-root `VERSION` file (single source for CLI, Python, and desktop).
2. Build the backend and the macOS dmg as above.
3. Commit, tag with a `v` prefix matching `VERSION`, and push:

```bash
echo 0.0.1 > VERSION
bash desktop/build/build-backend.sh
cd desktop && npm run dist:mac && cd ..
git add VERSION desktop/package.json desktop/package-lock.json
git commit -m "release: v0.0.1"
git tag v0.0.1
git push && git push --tags
```

4. On GitHub, create a Release for tag `v0.0.1`, upload `desktop/release/Stella-0.0.1-arm64.dmg` (and the Intel dmg if you built it), and write the notes.

The running app checks GitHub Releases and prompts you to download; it does not install in the background. Unsigned builds need a right-click → Open the first time.

If GitHub downloads require the macOS system proxy, expose it to the build
process explicitly:

```bash
HTTP_PROXY=http://127.0.0.1:7890 \
HTTPS_PROXY=http://127.0.0.1:7890 \
NO_PROXY=127.0.0.1,localhost \
npm run dist:mac
```

An unsigned local build can be opened for testing. Public distribution should
use an Apple Developer ID certificate and notarization.

## Architecture

```
desktop/
├── src/
│   ├── main/              # Electron main process
│   │   ├── index.ts       # Window management, IPC
│   │   ├── python-manager.ts  # Python backend lifecycle
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
