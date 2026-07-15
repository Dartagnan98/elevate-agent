# Realtor Beta rollback: restore 1.2.65 without touching Stable

This runbook is only for the isolated `beta` updater lane. It restores the
pre-release Beta feed and Beta download aliases to the candidate receipt's
rollback target (1.2.65 for the current launch). It does not roll back or write
realtor data, Admin data, sessions, `$HOME/.elevate-beta`, Stable, or
`latest-mac.yml`. That distribution-only boundary gives the rollback RPO 0.

## Required retained evidence

- The final candidate receipt and its SHA-256.
- The exact pre-release `beta-mac.yml` bytes whose SHA-256 equals
  `candidate-receipt.json.rollback_target.sha256`.
- The pre-release `latest-mac.yml` SHA-256 from
  `candidate-receipt.json.public_feeds_at_finalize.latest.sha256`.
- The versioned 1.2.65 x64 and arm64 DMGs already on the update host. Their
  sizes and SHA-512 values must match the rollback target's `files` entries.
- The candidate's published `beta-mac.yml` SHA-256 for compare-and-swap.

Do not start if any retained byte or digest is missing. Do not reconstruct the
old feed from memory or from YAML metadata; use the exact retained bytes.

## Preflight and local drill

Run the candidate-bound gate before publishing. It performs this rollback
algorithm against a local fixture and emits
`desktop/dist/evidence/realtor-beta-gate.json`:

```bash
ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run smoke:mac:live
```

The evidence must say `ok: true`, `rollback.target_version: 1.2.65`,
`rollback.rpo_seconds: 0`, `rollback.production_mutated: false`, and show the
same Stable hash before and after. `ship:mac` rejects a Beta candidate without
this exact-candidate evidence.

## Production rollback transaction

1. Freeze Beta publishing. Leave Stable and the application backend online.
2. Under `/var/lock/elevate-release-publish.lock`, verify all compare-and-swap
   inputs before moving any file:
   - `latest-mac.yml` still equals the retained Stable SHA-256.
   - `beta-mac.yml` equals the failed candidate's published SHA-256.
   - the retained rollback feed equals the receipt's rollback SHA-256.
   - both versioned 1.2.65 DMGs match the receipt's size and SHA-512.
3. In a new mode-0700 staging directory on the same filesystem:
   - copy the retained rollback feed to `beta-mac.yml`;
   - copy the versioned 1.2.65 x64 DMG to both x64 Beta alias names;
   - copy the versioned 1.2.65 arm64 DMG to both arm64 Beta alias names;
   - verify every staged copy against its source.
4. Atomically replace only these Beta paths:
   - `Elevate-Beta-mac-x64.dmg`
   - `Elevate-beta-mac-x64.dmg`
   - `Elevate-Beta-mac-arm64.dmg`
   - `Elevate-beta-mac-arm64.dmg`
   - `beta-mac.yml` (move this last)
5. Do not delete the failed candidate's versioned artifacts. They are retained
   for forensics and do not affect clients after the feed pointer is restored.
6. Read back the public Beta feed with cache bypass and prove:
   - version is 1.2.65;
   - feed SHA-256 equals the retained rollback target;
   - every file URL, size, and SHA-512 matches the receipt;
   - all four Beta aliases match their 1.2.65 source DMGs;
   - `latest-mac.yml` still equals the preflight Stable SHA-256.

If any compare-and-swap or staged hash check fails, remove only the staging
directory and stop. Do not partially replace aliases, do not touch Stable, and
do not improvise a new feed.

## Installed-app rollback, if a machine must be recovered immediately

Install the notarized 1.2.65 `Elevate Beta.app` over only
`$HOME/Applications/Elevate Beta.app`. Never overwrite
`$HOME/Applications/Elevate.app`. Preserve `$HOME/.elevate-beta`; the rollback
does not erase or migrate user data. Verify the Beta bundle ID, signature,
Gatekeeper acceptance, updater channel, and local Beta status endpoint before
relaunching. Recheck Stable independently afterward.

## Exit criteria

Rollback is complete only when the Beta public readback is 1.2.65, Stable is
byte-identical to its preflight snapshot, Beta/Stable apps still coexist under
different identities and profile roots, and no operational/profile data was
written or discarded.
