# Elevate Desktop

Native desktop shell for Elevate. The app starts or reuses the local Elevate
dashboard backend, then opens the same app UI inside an Electron window. The
desktop shell and `elevate dashboard` use the same local web app, so unlocked
Admin, Leads, Social Media, Tasks, Memory, and Setup surfaces stay in sync.

By default the desktop app opens `/chat` with the embedded chat runtime enabled.
To test the lighter dashboard-only mode explicitly:

```bash
ELEVATE_DESKTOP_EMBEDDED_CHAT=0 npm start
```

## Development

```bash
npm install
npm start
```

Desktop release builds require Node.js 22.12 or newer. If the default shell
`node` is older, put a current Node binary first in `PATH` before running the
release scripts.

From the repository root:

```bash
npm run desktop
```

## macOS Build

```bash
npm run pack:mac
npm run build:mac
```

Artifacts are written to `desktop/dist/`.

Run the Apple release preflight before a public build:

```bash
npm run preflight:apple
```

Bump `desktop/package.json` before each public release. The preflight checks the
local update feed, when present, and rejects a package version that is not newer.

## macOS Signing + Notarization

The current production lane is Developer ID distribution outside the Mac App
Store. Install a valid
`Developer ID Application` certificate in Keychain, then store Apple
notarization credentials in Keychain before running the build:

```bash
security find-identity -v -p codesigning | grep "Developer ID Application"

xcrun notarytool store-credentials elevate-notarization \
  --apple-id "you@example.com" \
  --team-id "TEAMID"

export CSC_NAME="Your Name (TEAMID)"
export APPLE_KEYCHAIN_PROFILE="elevate-notarization"

npm run release:mac
```

Do not commit Apple credentials. The build config signs and notarizes the app
bundles through the local Keychain certificate and electron-builder's
notarization support.

`npm run release:mac` also finalizes the DMG containers, refreshes
`latest-mac.yml` after stapling changes the DMG bytes, and uploads the update
feed artifacts to `https://api.elevationrealestatehq.com/updates`.

`npm run release:apple` runs the preflight first, then performs the full
Developer ID build, notarization, stapling, feed refresh, and upload.

To finalize local artifacts without uploading them:

```bash
npm run build:mac
npm run finalize:mac
```

The app resolves the runtime in this order:

1. the packaged Python runtime and CLI under `Elevate.app/Contents/Resources`
2. `ELEVATE_DESKTOP_CLI`
3. the repo-local `cli/.venv/bin/python -m elevate_cli.main`
4. an installed `elevate` command on `PATH`
5. the in-app installer using `npx --yes github:Dartagnan98/elevate-agent install --skip-setup`

## Mac App Store Lane

Mac App Store submission is a separate release lane from this Developer ID DMG.
Apple requires App Sandbox for Mac App Store apps, while this desktop shell
currently starts a local Python backend, uses the bundled runtime, self-heals
the local gateway, and requests Apple Events for approved Messages delivery.
Those pieces are intentionally kept in the Developer ID lane until a separate
MAS sandbox architecture is designed and tested.
