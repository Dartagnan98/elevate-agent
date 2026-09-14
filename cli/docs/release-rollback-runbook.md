# Elevate Release Rollback Runbook

Updated: 2026-06-19

Use this when a shipped macOS release must be pulled back or a customer needs to
return to the previous known-good Elevate app. Do not run release or rollback
commands without owner approval.

## Inputs

- Bad version.
- Last known-good version.
- Architecture: `arm64` or `x64`.
- Whether the public update feed is already live.
- Whether the customer has already launched the bad version.

## Preserve Evidence First

Before replacing anything on a customer machine:

```bash
cp -R /Applications/Elevate.app \
  /Applications/Elevate.app.backup-$(date +%Y%m%d-%H%M%S)

elevate debug share --local
```

Keep the backup until the replacement app has passed installed-runtime smoke and
the customer has confirmed the critical workflow.

## Artifact Retention

The release ship script uploads versioned `zip`, `dmg`, and `latest-mac.yml`
artifacts, refreshes the `Elevate-latest-mac-<arch>.dmg` aliases, verifies the
public feed/artifact hashes, and then calls the remote prune script that keeps
the last three versioned builds.

Source references:

- `desktop/scripts/ship-to-hetzner.js` uploads only the current versioned
  artifacts plus `latest-mac.yml`.
- `desktop/scripts/ship-to-hetzner.js` refreshes
  `Elevate-latest-mac-arm64.dmg` and `Elevate-latest-mac-x64.dmg` aliases.
- `desktop/scripts/ship-to-hetzner.js` calls
  `/root/prune-elevate-updates.sh`, documented in-source as keeping the last
  three versioned builds.
- After successful ship, local `desktop/dist/*.dmg`, `desktop/dist/*.zip`, and
  `desktop/dist/latest-mac.yml` remain as a local release archive; only unpacked
  `desktop/dist/mac*` app bundles are removed.

## Feed Rollback

1. Identify the previous retained versioned `latest-mac.yml`, zip, and dmg
   artifacts on the update host.
2. Replace the public `latest-mac.yml` with the previous known-good feed.
3. Refresh the `Elevate-latest-mac-arm64.dmg` and/or
   `Elevate-latest-mac-x64.dmg` aliases to the previous known-good DMGs.
4. Verify the public feed and every referenced artifact before announcing the
   rollback live.

Verification:

```bash
curl -fsSL https://api.elevationrealestatehq.com/updates/latest-mac.yml
curl -I https://api.elevationrealestatehq.com/updates/Elevate-latest-mac-arm64.dmg
curl -I https://api.elevationrealestatehq.com/updates/Elevate-latest-mac-x64.dmg
```

## Customer Rollback

1. Back up the current installed app with the command in `Preserve Evidence`.
2. Download the known-good DMG for the customer's architecture.
3. Drag the known-good Elevate app into `/Applications`.
4. Launch once and confirm the version in About Elevate.
5. Run installed-runtime smoke against the installed app:

```bash
cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py \
  --installed-app /Applications/Elevate.app \
  --skip-sidecar
```

## Post-Rollback Checks

- `~/Library/Logs/Elevate/main.log` shows dashboard load milestones.
- `curl http://127.0.0.1:9120/api/status` returns a valid status payload.
- `elevate debug share --local` is redacted and includes current logs.
- The customer can open chat and run the workflow that failed on the bad build.
- No support bundle or diagnostics are stored in the public update directory.

## Escalate

Escalate as release-blocking when:

- The previous retained artifacts are missing.
- The feed references artifacts whose hash/size does not match.
- The known-good app fails codesign/spctl or installed-runtime smoke.
- A rollback still mutates the signed bundle on first launch.
- Diagnostics are needed but would require unredacted customer content.
