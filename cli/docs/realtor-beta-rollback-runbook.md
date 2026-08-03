# Realtor Beta rollback: restore 1.2.65 without touching Stable

This runbook is only for the isolated `beta` updater lane. It restores the
pre-release Beta feed and Beta download aliases to the candidate receipt's
rollback target (1.2.65 for the current launch). It does not roll back or write
realtor data, Admin data, sessions, `$HOME/.elevate-beta`, Stable, or
`latest-mac.yml`. That distribution-only boundary gives the rollback RPO 0.

Two Beta recovery lanes exist. The body of this document is the downgrade
lane (restore 1.2.65). For the pinned 1.2.102 candidate there is also a
roll-forward lane that advances Beta to the minimal 1.2.103 recovery package;
read "Roll-forward recovery (1.2.103)" below and choose the lane first.

## Required retained evidence

- The final candidate receipt and its SHA-256.
- The exact pre-release `beta-mac.yml` bytes whose SHA-256 equals
  `candidate-receipt.json.rollback_target.sha256`.
- The pre-release `latest-mac.yml` SHA-256 from
  `candidate-receipt.json.public_feeds_at_finalize.latest.sha256`.
- All four versioned 1.2.65 updater artifacts (x64/arm64 ZIP and DMG) already
  on the update host. Their sizes and SHA-512 values must match the rollback
  target's `files` entries.
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

Use the candidate-bound command below. Do not run ad hoc `scp`, `rsync`, `cp`,
or `mv` commands against the update directory. The receipt path may point at
the immutable release archive created by `ship:mac`. The retained feed path is
always explicit; the command never reconstructs or discovers those bytes.

Set these values from the failed candidate's immutable release proof:

```bash
RECEIPT=/absolute/path/to/candidate-receipt.json
RECEIPT_SHA256=<sha256-of-that-exact-receipt>
RETAINED_BETA_FEED=/absolute/path/to/retained-1.2.65-beta-mac.yml
FAILED_BETA_FEED_SHA256=<published-failed-candidate-beta-mac.yml-sha256>
```

First run the read-only public/host preflight:

```bash
npm --prefix desktop run rollback:realtor-beta -- \
  --mode preflight \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256" \
  --retained-feed "$RETAINED_BETA_FEED" \
  --expected-failed-feed-sha256 "$FAILED_BETA_FEED_SHA256"
```

Then run the locked remote drill. It streams the retained feed into a unique
mode-0700 directory under the update root, exercises all five atomic replaces
inside that directory, removes it, and proves the public files did not change:

```bash
npm --prefix desktop run rollback:realtor-beta -- \
  --mode dry-run \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256" \
  --retained-feed "$RETAINED_BETA_FEED" \
  --expected-failed-feed-sha256 "$FAILED_BETA_FEED_SHA256"
```

Only after both modes pass, execute with the candidate ID copied from the same
receipt. `execute` is rejected without the exact confirmation value:

```bash
CANDIDATE_ID=<candidate-id-from-the-receipt>
npm --prefix desktop run rollback:realtor-beta -- \
  --mode execute \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256" \
  --retained-feed "$RETAINED_BETA_FEED" \
  --expected-failed-feed-sha256 "$FAILED_BETA_FEED_SHA256" \
  --confirm-candidate-id "$CANDIDATE_ID"
```

All three modes acquire `/var/lock/elevate-release-publish.lock`. `preflight`
does not create a remote path. `dry-run` writes only its hidden staging
directory. `execute` prepares and verifies compensation copies before the
first alias replacement; any catchable failure before the final post-check
restores the failed candidate feed and all four aliases. It also creates the
candidate-bound hidden `.realtor-beta-rollback-freeze` under that same lock.
Both Stable and Beta publication fail closed while this durable marker exists,
and Stable pruning skips. The marker remains in force after the remote commit
while public readback and the immutable execute archive are sealed. It is
retired under the global lock only after that archive exists and the exact
rollback pointers plus retained Stable feed are reverified. The command never
writes Stable, backend, application, session, or profile paths.

Freeze retirement is a two-phase durable operation: while the active marker
still exists, the command writes, hash-checks, and fsyncs the exact
candidate-specific cleared marker; it then unlinks the active marker and
fsyncs the update root. A retry that sees both exact markers finishes the
unlink, while the exact cleared marker alone means retirement already
completed. The cleared marker is also a permanent candidate-specific
publication tombstone: under the same global lock, every Beta publisher derives
and verifies that exact marker before committing, so a delayed stage for the
rolled-back candidate cannot republish it. A different later candidate remains
eligible. Never delete either marker manually.

1. Freeze all Stable and Beta release publication. Leave the application
   backend and existing Stable clients online. The command enforces this with
   the durable candidate-bound release-freeze marker; do not rely on a verbal
   maintenance window alone.
2. Under `/var/lock/elevate-release-publish.lock`, verify all compare-and-swap
   inputs before moving any file:
   - `latest-mac.yml` still equals the retained Stable SHA-256.
   - `beta-mac.yml` equals the failed candidate's published SHA-256.
   - the retained rollback feed equals the receipt's rollback SHA-256.
   - all four versioned 1.2.65 ZIP/DMG artifacts match the receipt's size and
     SHA-512;
   - all four failed-candidate versioned ZIP/DMG artifacts still match the
     candidate receipt's size, SHA-512, and SHA-256.
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
   - cache-bypassed downloads of all four versioned 1.2.65 ZIP/DMG artifacts
     match those sizes and SHA-512 values byte-for-byte;
   - all four Beta aliases match their 1.2.65 source DMGs;
   - `latest-mac.yml` still equals the preflight Stable SHA-256.

If any compare-and-swap or staged hash check fails, stop. Let the command clean
an untrusted preflight/dry-run stage itself. Never manually remove an execute
journal, deterministic stage, release-freeze marker, or durable local intent;
rerun the exact command so it can classify and recover them. Do not partially
replace aliases, do not touch Stable, and do not improvise a new feed.

If SSH, the local process, or the machine stops at any point during `execute`,
rerun the exact same candidate-bound command. Do not delete the deterministic
remote stage, the release-freeze marker, `execute-pending`, or
`execute-complete`. The transaction journal classifies every pointer as the
failed or rollback generation and resumes safely after an uncatchable
`SIGKILL`, including a commit whose acknowledgement was lost. A completed
archive is idempotent: a retry clears an exact still-active freeze, while an
already-cleared freeze is accepted without requiring a later legitimate
release to retain the old feed bytes.

On a successful mode, the command writes an immutable candidate-bound archive
under `desktop/dist/rollback-receipts/beta/`. The execute archive contains the
exact receipt, retained feed, public Beta/Stable bytes before and after, all
four public alias digests, all four versioned updater-artifact digests, the
global-lock/staging contract, and the ordered five-path commit record. Do not
declare rollback complete without this archive. Public readback downloads all
four aliases plus all four versioned updater artifacts and can take several
minutes.

### If the execute archive is lost or the freeze was left half-retired

The pointer commit and the freeze retirement are decoupled by design, so two
rare post-commit states can look like a dead end even though the command still
converges on its own. In both cases the fix is the same: rerun the exact
candidate-bound `execute` command. Never hand-delete a marker or hand-edit a
feed to force progress.

- A freeze left half-retired — both the active and cleared markers present, or
  only the cleared marker present — resolves on the rerun. The two-phase clear
  writes, hash-checks, and fsyncs the exact cleared marker before it unlinks the
  active marker, so a crash between those two steps leaves both markers; the
  rerun re-verifies the exact freeze hash and finishes the unlink, and a crash
  after the unlink leaves only the cleared marker, which is accepted as already
  retired.
- A lost immutable `execute-complete` archive is rebuilt on the rerun as long as
  the durable `execute-pending` intent still exists. That intent is sealed under
  the lock before the first pointer move and holds the pre-commit public
  baseline, so the rerun replays the current committed readback against it,
  rewrites the archive from the committed pointer state, and only then runs the
  two-phase clear.

Each of those two faults converges on its own, but the compound double-fault —
the archive lost *and* the freeze still half-retired with both markers present —
does not. With no archive to adopt, the rerun re-runs the remote `execute`,
which fails closed with `RELEASE_FREEZE_STATE_CONFLICT` (exit 66) on the
two-marker state instead of finishing the unlink. That is the safe direction:
Beta publication stays blocked and Stable is untouched. Restore the
`execute-complete` archive so the rerun adopts it and runs only the two-phase
clear, or escalate — never hand-delete the active marker to unstick it.

The command reconstructs the pre-commit baseline solely from the durable
`execute-pending` intent, which lives under the local evidence root on the host
that ran the command, not on the remote. If that intent is gone — the whole
local `desktop/dist` receipts tree was lost after the commit — the rerun cannot
re-derive the baseline and refuses rather than guess. Recover the intent
directory from that host and rerun. If it cannot be recovered, stop and
escalate: the public Beta pointer is already the committed target and Stable is
byte-unchanged, so there is no client-facing reason to force progress by
deleting a marker or editing a feed.

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
different identities and profile roots, no operational/profile data was
written or discarded, the immutable `execute-complete` archive validates, and
the exact rollback release-freeze marker has been retired.

## Roll-forward recovery (1.2.103)

The second recovery lane for the same isolated `beta` channel advances the
Beta feed and all four Beta download aliases forward to 1.2.103, a minimal
signed recovery build of `Elevate Beta.app`, instead of restoring 1.2.65.
The pairing is version-pinned in code: the recovery package binds only to the
exact 1.2.102 Beta candidate, its own version is exactly 1.2.103, and the next
full Beta release must be strictly newer than 1.2.103
(`next_full_beta_minimum_exclusive`). `verify-final` rejects a recovery
package attached to any other candidate version. The procedure ID is
`realtor-beta-recovery-roll-forward-v1`; downgrade-based recovery is
rejected.

Choose the lane first:

- Roll-forward when installed 1.2.102 Beta machines must be contained through
  the updater lane they already poll: the feed moves forward, the standard
  Beta auto-updater installs the minimal app, the exact Beta runtime is
  stopped, and the profile is preserved until a fixed full Beta newer than
  1.2.103 ships.
- Rollback (above) when the candidate must be pulled from distribution and
  the public Beta feed returned to the retained 1.2.65 bytes. Auto-updaters
  do not downgrade installed machines; an already-updated machine needs the
  installed-app rollback section above.
- Both lanes replace only `beta-mac.yml` and the four Beta aliases. Neither
  writes Stable, `latest-mac.yml`, realtor data, sessions, or
  `$HOME/.elevate-beta`; the roll-forward drill proves the same RPO 0
  boundary.

## What the 1.2.103 recovery package is

A minimal Electron app whose packaged entrypoint is `src/recovery-main.js`
(`elevateRecoveryMode: true`; it refuses to start from any other package). It
contains no backend, no CLI, no gateway, no agent runtime, and no tools; the
receipt-pinned runtime policy is `backend`, `cli`, `gateway`, `runtime`, and
`tools` all `false` with `profile_preserved: true`. On launch it proves and
stops only exact-Beta runtime processes (gateway, dashboard backend, embedded
Postgres, PTY workers) owned by `$HOME/.elevate-beta`, preserves the whole
profile and the Beta LaunchAgent plist, and only then starts the normal
`beta`-channel auto-updater against the same public update URL so the machine
can advance to the next full Beta release. If containment cannot be proven,
the app reports `blocked` and never starts the updater. It keeps the full
Beta identity (`Elevate Beta.app`, `com.elevationrealestate.elevate.beta`,
`.elevate-beta`), so Beta/Stable coexistence is unchanged.

`npm --prefix desktop run build:mac:recovery` builds it into
`desktop/dist/recovery/`: `Elevate-Beta-Recovery-1.2.103-mac-x64.zip/.dmg`,
`Elevate-Beta-Recovery-1.2.103-mac-arm64.zip/.dmg`, the recovery
`beta-mac.yml`, and per-architecture pre-sign evidence. The build requires
`ELEVATE_RECOVERY_SOURCE_RECEIPT_ID` to equal the exact candidate source
receipt ID.

## Recovery receipt binding

The 1.2.102 `candidate-receipt.json` carries a `recovery` block
(`kind: elevate-beta-recovery-package`) that pins the SHA-256 and SHA-512 of
the recovery `beta-mac.yml` and all four 1.2.103 artifacts, both recovery app
bundle manifests, Apple signing and notarization evidence for the apps and
DMGs, the per-architecture pre-sign contracts, the minimal runtime policy,
and the source receipt ID. `verify-final` recomputes every value from the
bytes in `desktop/dist/recovery/` and fails closed on any drift; a recovery
artifact whose hash equals any candidate artifact is rejected as reuse.

The drill evidence is bound the same way. Full-evidence verification
(`verify-final --require-evidence`) requires
`desktop/dist/evidence/realtor-beta-gate.json` for a Beta candidate and
cross-checks its `recovery` block field-by-field against the receipt: the
post-activation Beta feed hash must equal `recovery.local_feed.sha256`, the
pre-activation feed hash must equal the receipt's `beta-mac.yml` artifact
SHA-256, and Stable before/after/expected must all equal
`public_feeds_at_finalize.latest.sha256`. Evidence for a different
candidate, architecture, or receipt byte-state fails.

## Recovery upload ordering

All four versioned 1.2.103 recovery artifacts must already exist on the
update host, matching the receipt's recovery hashes, before the 1.2.102
candidate Beta feed is published. This upload-first ordering is enforced by
the locked publish transaction (`ship:mac`): for a recovery-carrying
candidate it SHA-256-verifies the staged recovery bytes (sizes and SHA-512
are verified against the same bytes locally before upload and publicly
after publication), commits all four recovery artifacts plus the retained
recovery feed (`.realtor-beta-recovery-1.2.103-beta-mac.yml`, a dot-name in
the update directory that no feed references) to their final names, and
only then moves any candidate alias or feed pointer. Missing or foreign recovery bytes abort publication
(`STAGED_HASH_FAILED` / `PUBLISH_RECOVERY_STATE_UNKNOWN`) with the old
release intact. Publishing the candidate without retention would open a
window where a Beta fault has no pre-staged roll-forward target and
recovery would require a mid-incident build, sign, and notarize cycle. The
recovery `beta-mac.yml` is never published live with the candidate;
activation is exactly the later replacement of the four Beta aliases and
then the feed from the retained bytes. The candidate-bound production
activation command is `recover:realtor-beta` (below). Do not improvise an
alternative with ad hoc `scp`, `rsync`, `cp`, or `mv` against the update
directory.

## Production roll-forward activation transaction

Activation uses the same script as the rollback lane with `--lane recover`
(npm script `recover:realtor-beta`). It takes only the candidate receipt and
its SHA-256: every expectation — the current candidate feed and alias
hashes, the recovery feed hash, all four recovery artifact sizes/SHA-512s/
SHA-256s, the Stable snapshot — is bound to `receipt.recovery` and
`receipt.artifacts`, and the payload bytes are exactly the retention the
locked publish transaction already committed on the update host. The
command refuses a receipt without a bound recovery package, a recovery
version other than exact 1.2.103, a recovery package bound to a different
candidate or source receipt, a non-minimal runtime policy, or any
recovery/candidate hash reuse. No operator-supplied hash or feed file is
accepted on this lane.

```bash
RECEIPT=/absolute/path/to/candidate-receipt.json
RECEIPT_SHA256=<sha256-of-that-exact-receipt>

npm --prefix desktop run recover:realtor-beta -- \
  --mode preflight \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256"

npm --prefix desktop run recover:realtor-beta -- \
  --mode dry-run \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256"

CANDIDATE_ID=<candidate-id-from-the-receipt>
npm --prefix desktop run recover:realtor-beta -- \
  --mode execute \
  --candidate-receipt "$RECEIPT" \
  --candidate-receipt-sha256 "$RECEIPT_SHA256" \
  --confirm-candidate-id "$CANDIDATE_ID"
```

All three modes acquire `/var/lock/elevate-release-publish.lock` and verify,
before any mutation: `latest-mac.yml` against the receipt's Stable snapshot;
`beta-mac.yml` and all four Beta aliases against the candidate's published
hashes; the retained recovery feed
(`.realtor-beta-recovery-1.2.103-beta-mac.yml`) and all four retained public
recovery artifacts against the receipt's recovery hashes; and the four
candidate versioned artifacts (still retained for forensics). Missing or
foreign retained bytes fail closed with the candidate state intact — that is
the upload-first contract paying off. `preflight` creates no remote path.
`dry-run` copies the retained bytes into a hidden mode-0700 staging
directory, exercises all five atomic replaces inside it, and removes it.
`execute` backs up the candidate feed and aliases into a deterministic
journaled stage, writes the candidate-bound activation release-freeze
marker, then atomically replaces the four Beta aliases and the feed last.
Compensation before the final post-check restores the exact candidate state;
after `SIGKILL` at any pointer move, rerunning the same command resumes from
the durable journal. The command never writes Stable, `latest-mac.yml`,
backend, application, session, or profile paths (RPO 0).

The activation freeze reuses the shared `.realtor-beta-rollback-freeze`
path, so Stable and Beta publication and the downgrade lane all fail closed
while activation is in force; a rollback-lane freeze and an activation
freeze reject each other as exact-hash conflicts. Retirement is the same
two-phase durable operation as the rollback lane, producing the
activation-specific cleared marker
(`.realtor-beta-rollback-freeze.cleared-<activation-freeze-id>`). Unlike the
rollback lane, no permanent publish tombstone is needed after clearing: a
stale `ship:mac` of the superseded candidate fails its own compare-and-swap
(`PUBLISH_STATE_NOT_OLD` / `PUBLISH_STATE_UNKNOWN`) because the activated
recovery feed matches neither that candidate's finalize snapshot nor its
committed state. Never delete either marker manually.

On success each mode writes an immutable candidate-bound archive under
`desktop/dist/rollback-receipts/beta/<version>-<candidate-id>/recovery-1.2.103/`
(procedure `realtor-beta-recovery-roll-forward-v1`) containing the exact
receipt, public Beta/Stable bytes before and after, all four public alias
digests, all four recovery artifact digests, and the RPO-0 record. `execute`
additionally seals a durable `execute-pending` intent before mutating and an
`execute-complete` archive before the freeze is retired; public readback
downloads all four aliases plus all four recovery artifacts and verifies
them against the receipt. Do not declare activation complete without the
`execute-complete` archive. Activation is complete only when the public
Beta readback is exactly 1.2.103 with the receipt-bound recovery feed hash,
Stable is byte-identical to its snapshot, and the activation freeze has been
retired through the two-phase cleared marker.

A lost `execute-complete` archive or a freeze left half-retired recovers the
same way as the rollback lane, because activation seals the identical durable
`execute-pending` intent and two-phase cleared marker: rerun the exact
candidate-bound `--lane recover` `execute` command. See "If the execute archive
is lost or the freeze was left half-retired" above; the same prerequisite holds
that the rerun rebuilds a lost archive only while the durable `execute-pending`
intent survives, and never by hand-deleting a marker or editing a feed.

## Recovery local drill and evidence

The candidate-bound Beta gate performs the roll-forward activation algorithm
inside a temporary local fixture only. It never modifies the installed app,
the user's Beta profile, Stable, public feeds, or any remote host:

```bash
npm --prefix desktop run gate:realtor-beta
```

(`ELEVATE_RELEASE_CHANNEL=beta npm --prefix desktop run smoke:mac:live` ends
by running the same gate.) The drill needs the installed candidate
`Elevate Beta.app` (override with `ELEVATE_LIVE_APP`),
`desktop/dist/candidate-receipt.json`, the candidate `beta-mac.yml` next to
the receipt, and the recovery feed at `desktop/dist/recovery/beta-mac.yml`.
It downloads the public `latest-mac.yml` and fails if Stable has drifted
from the receipt's finalize snapshot.

Inside the fixture it stages the recovery feed and four alias payloads in a
mode-0700 staging directory, hash-checks every staged copy, atomically
replaces the four Beta aliases and then the feed (feed last), and proves:

- the Beta feed advanced to exactly 1.2.103 with the receipt-bound recovery
  feed hash, and all four Beta aliases match the recovery DMG payloads;
- the Stable feed, Stable alias sentinels, and an operational-data sentinel
  are byte-identical before and after (`rpo_seconds: 0`);
- nothing remote or production was touched (`remote_mutation: false`,
  `production_mutated: false`, `profile_data_mutations: 0`);
- a recovery version not strictly newer than the candidate is rejected.

Alias payload bytes in the fixture are synthetic
(`artifact_bytes_mode: synthetic-local-fixture`); the real artifact bytes
stay bound through the receipt's sizes and SHA-512 values. The evidence must
say `ok: true`, `recovery.mode: local-fixture-roll-forward`, and
`recovery.procedure_id: realtor-beta-recovery-roll-forward-v1`. Do not treat
the drill as remote proof; it validates the algorithm and the hash bindings,
not the state of the update host.
