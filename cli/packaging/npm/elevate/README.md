# @elevationrealestate/elevate

Public bootstrap installer for Elevate Agent, the local AI chief of staff for
real estate agents by Elevation Real Estate HQ.

## Install

One-shot:

```bash
npx @elevationrealestate/elevate install
```

Or install the bootstrap command globally:

```bash
npm install -g @elevationrealestate/elevate
elevate install
```

## Private Beta

If the source release is private, provide a GitHub token with read access:

```bash
ELEVATE_GITHUB_TOKEN="$(gh auth token)" npx @elevationrealestate/elevate install
```

## After Install

```bash
elevate setup
elevate dashboard
elevate update
```

The NPM package is only the bootstrapper. The local Elevate runtime, SQLite
stores, base memory/tasks system, and licensed real estate packs are installed
under `~/.elevate`.
