# Elevate NPM Bootstrap

This folder contains the public NPM bootstrap package for Elevate Agent.

The package is intentionally small. It installs an `elevate` command that can:

- run `elevate install` to bootstrap the local Python runtime;
- forward normal commands to the installed local Elevate CLI;
- keep the base installer public while paid real estate packs stay licensed.

## Local Smoke Test

```bash
cd cli/packaging/npm/elevate
npm pack --dry-run
node bin/elevate.js --help
node bin/elevate.js install --dry-run --skip-setup
```

## Publish

```bash
cd cli/packaging/npm/elevate
npm publish --access public
```

First release target:

```bash
npx @elevationrealestate/elevate install
```

For private beta builds, pass a GitHub token through the environment:

```bash
ELEVATE_GITHUB_TOKEN="$(gh auth token)" npx @elevationrealestate/elevate install
```
