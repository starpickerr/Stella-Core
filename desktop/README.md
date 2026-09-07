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

# 3. Build Stella.app, DMG, ZIP, and updater metadata
cd desktop
npm run dist:mac
```

The outputs are:

```text
desktop/release/mac-arm64/Stella.app
desktop/release/Stella-<version>-arm64.dmg
desktop/release/Stella-<version>-arm64.zip
desktop/release/latest-mac.yml
```

To build a new release, bump the repo-root `VERSION` file first (that is
the single source for the CLI, the Python package, and the desktop app):

```bash
echo 0.0.2 > VERSION
bash desktop/build/build-backend.sh
cd desktop
npm run dist:mac
```

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
