# Elevate Desktop

Native desktop shell for Elevate. The app starts or reuses the local Elevate
dashboard backend with embedded chat enabled, then opens Elevate Chat inside an
Electron window.

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
