# Elevate macOS beta release runbook

## Channel contract

- Stable uses `latest-mac.yml` and `Elevate-latest-mac-{arch}.dmg`.
- Beta uses `beta-mac.yml` and `Elevate-beta-mac-{arch}.dmg`.
- Versioned ZIP and DMG names are immutable. Shipping aborts if the same remote
  name already exists with different bytes.
- Beta never updates stable aliases, purges stable blockmaps, or runs the stable
  retention pruner.
- The beta app is stamped with the beta channel so a realtor can install it
  without a Terminal opt-in step.
- A stamped beta version is beta-only. Production must use a higher version and
  a new `latest` build; do not repoint `latest-mac.yml` at a beta-stamped build.

## Release

Use a clean release worktree and Node 22.12 or newer.

```bash
export ELEVATE_RELEASE_PYTHON=/absolute/path/to/cli/.venv/bin/python
npm --prefix desktop run release:beta
```

For a hold point before upload, run the stages separately:

```bash
ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run preflight:apple
ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run build:mac
ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run finalize:mac
ELEVATE_RELEASE_PYTHON=/absolute/path/to/cli/.venv/bin/python npm --prefix desktop run smoke:mac
ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run ship:mac
```

Before `ship:mac`, verify both packaged apps contain
`elevateReleaseChannel: beta`, pass `codesign --verify`, and do not contain a
development `.venv`.

## Public verification

After shipping:

1. Confirm `beta-mac.yml` has the intended version and both architectures.
2. Hash every public versioned artifact against the feed.
3. Confirm each beta DMG alias is byte-identical to its versioned DMG.
4. Confirm the stable feed and both stable aliases have their pre-release hashes.
5. Install the beta DMG on a canary and run the critical realtor workflow.

The first beta proves manual bootstrap and runtime behavior. A second, higher
beta version is required to prove the beta over-the-air update path end to end.

## Production

After beta soak, increment to a version newer than both public feeds, build with
the `latest` channel, rerun the full release gate, and publish through the stable
lane. Keep the beta feed available until stable rollout is verified.
