# Elevate Desktop

Native desktop shell for Elevate. The app starts or reuses the local Elevate
dashboard backend, then opens the same Hub UI inside an Electron window. The
desktop shell and `elevate dashboard` use the same local web app, so unlocked
Admin, Leads, Social Media, Tasks, Memory, and Setup surfaces stay in sync.

By default the desktop app opens `/hub` and does not force the embedded chat
PTY. To test the heavier chat mode explicitly:

```bash
ELEVATE_DESKTOP_EMBEDDED_CHAT=1 npm start
```

## Development

```bash
npm install
npm start
```

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

## macOS Signing + Notarization

For public distribution outside the Mac App Store, install a valid
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

To finalize local artifacts without uploading them:

```bash
npm run build:mac
npm run finalize:mac
```

The app resolves the runtime in this order:

1. `ELEVATE_DESKTOP_CLI`
2. the repo-local `cli/.venv/bin/python -m elevate_cli.main`
3. an installed `elevate` command on `PATH`
4. the in-app installer using `npx --yes github:Dartagnan98/elevate-agent install --skip-setup`
