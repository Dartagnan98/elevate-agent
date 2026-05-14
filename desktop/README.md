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

The app resolves the runtime in this order:

1. `ELEVATE_DESKTOP_CLI`
2. the repo-local `cli/.venv/bin/python -m elevate_cli.main`
3. an installed `elevate` command on `PATH`
4. the in-app installer using `npx --yes github:Dartagnan98/elevate-agent install --skip-setup`
