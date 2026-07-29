# Fork-customer upgrade runbook: Skyleigh 1.2.63 → 1.2.98+

Upgrading one specific live customer whose heavily-patched fork was merged into
mainline. This is not the ordinary update path and must not be run as one.

Her box is not a normal install. The app bundle has been edited in place, a
launchd guard re-injects those edits after every write to the bundle, two
headless dashboards run out of the bundle's Python, and both are published to
the internet through a Cloudflare tunnel. Roughly thirteen further scheduled
jobs touch the same database. Every one of those has to be understood and
stopped before the bundle is replaced, or the upgrade fails in a way that is
hard to see and hard to undo.

**Executor:** one human or agent with SSH to her Mac, working serially. Budget
90–120 minutes with her offline, plus a soak. Do not run any part of this while
she is working. Do not parallelise steps.

**Markers used below**

| Marker | Meaning |
| --- | --- |
| `[READ-ONLY]` | Observes only. Safe to run any time. |
| `[DESTRUCTIVE]` | Changes live state. Reversible by a named step in this document. |
| `[IRREVERSIBLE]` | No recovery except from the pre-flight backup. |
| `[OWNER GO]` | Stop. Get Dartagnan's explicit yes in chat before running. |

Her standing constraints, which this runbook does not have authority to change:

- She stays on the **Stable** channel. Never install a Beta artifact on her box.
- Surgical edits only. Stage on a copy first.
- Anything that takes her document workflow offline needs the owner's go.

---

## 0. Hard prerequisites — verify before touching her box

These are build-side and repo-side gates. If any is unmet, **stop**; nothing in
sections 1–7 is safe to start.

### 0.1 A Stable 1.2.98+ build must exist and be published `[OWNER GO]`

1.2.98 is on the **Beta** feed. As of this writing the Stable feed is still
**1.2.63** — the version she already runs. The channel is baked in at build
time (`desktop/src/release-profile.js`): a Beta build is a different app
(`Elevate Beta.app`, bundle id `…elevate.beta`, `ELEVATE_HOME=~/.elevate-beta`,
port 9139, gateway label `ai.elevate.gateway-beta`). Installing it would not
upgrade her install, it would create a second, empty one — and her
`message_loop.py` hardcodes `/Applications/Elevate.app/...`, so half her board
would silently point at the old bundle.

So a **Stable** build of 1.2.98+ must be cut, notarized, and published to
`https://api.elevationrealestatehq.com/updates/latest-mac.yml` first. That is
the release chain's job, not this runbook's. Confirm before starting:

```bash
curl -fsS https://api.elevationrealestatehq.com/updates/latest-mac.yml | head -5
```

The `version:` line must be ≥ 1.2.98. Record the exact version; every later
step's expectations are pinned to it.

### 0.2 Why she must not be moved to Beta

Independent of packaging, the Beta channel breaks her daily work by design:

- `_require_exact_beta_forms_provider_for_local_document_mutation()`
  (`cli/elevate_cli/web_routes/admin_deals.py:455`) returns **409
  `local_reference_form_route_disabled`** on every local Offer Kit / form-pack
  mutation when `ELEVATE_RELEASE_CHANNEL == "beta"`. That is thirteen call
  sites covering offer-kit build, offer-prep gather/generate/form/package, deal
  documents, and draft signatures — her entire CPS and document workflow.
- On Beta, `_normalize_forms_provider_value()`
  (`cli/elevate_cli/data/admin_setup.py:406`) rejects any `forms_provider`
  value key outside `{provider, playbook}`. The `documentPackRoot` she needs in
  section 4 **cannot be saved at all** on Beta.
- On Beta, `get_runtime_skills_dir()` serves only the signed, code-bundled
  skills tree; her `~/.elevate/skills` customisations are ignored.

### 0.3 The fork-reconcile migration must be in the shipped bundle

The upgrade depends on two changes landing together in the build:

1. `_COMPATIBLE_PRIOR_HASHES` in `cli/elevate_cli/data/migrations.py`,
   populated with her five fork migration hashes at versions 0035–0039.
2. A new `cli/elevate_cli/data/migrations_pg/0040_crm_fork_reconcile.sql` that
   carries the **net** schema effect of mainline 0035–0039 forward
   idempotently.

**At the time this runbook was written, (1) is present in the working tree and
(2) does not yet exist.** Verify both inside the *installed* bundle in step
3.2 before letting anything connect to her database. If `0040` is missing, the
allowlist skips mainline 0035–0039 and nothing replaces them: her box comes up
without `contacts.tags_json`, `crm_settings`, `account_goals`, and the rest, and
the new CRM UI 500s on read. Stop and get the build fixed.

### 0.4 Why the allowlist is load-bearing (read this before improvising)

Her ledger holds five migrations at 0035–0039 that mainline used for unrelated
CRM work. On merge her files were renumbered to 0041–0044 (0036 had no mainline
counterpart). The four renumbered files are byte-identical to hers — verified:

| Her ledger version | Renumbered file | sha256 |
| --- | --- | --- |
| `0035_crm_goals.sql` | `0041_crm_goals.sql` | `9c59e596…56b7` |
| `0036_pipeline_stages_expand.sql` | *(none — dropped)* | `b66be780…fe2d` |
| `0037_contact_items.sql` | `0042_contact_items.sql` | `19d23a3f…586d` |
| `0038_contacts_recency_segment.sql` | `0043_contacts_recency_segment.sql` | `d53d22e6…2d0c` |
| `0039_contact_documents.sql` | `0044_contact_documents.sql` | `cb4eefc5…ceb2` |

Without the allowlist, `run_pending()` takes the version-slot-reuse branch
(`migrations.py:160`): stored name ≠ on-disk name, so it deletes her ledger row
and applies mainline's DDL on top of her fork schema. It dies at the first
file. Mainline `0035_crm_redesign.sql` re-adds a `pipeline_status` CHECK whose
stage list contains `'attempted_contact'`; her live rows use the slug
`'attempted'`. `ADD CONSTRAINT` fails, the migration raises, and — because
`_ensure_schema()` runs `run_pending()` on the first `connect()` of *every*
process — her two dashboards, the gateway, and all thirteen cron jobs die on
every start. Nothing recovers on its own.

With the allowlist, all five are relabelled in the ledger and skipped, `0040`
carries the net effect forward, and `0041–0044` apply as no-ops against schema
she already has.

**Known scar, document it for whoever audits later:** after a successful
upgrade her ledger shows `0035_crm_redesign.sql` with mainline's hash even
though that DDL never ran on her box. The ledger is a relabelling, not a
history. Section 3.5's schema assertions — not the ledger — are the real proof.

---

## 1. Pre-flight `[READ-ONLY]`

Nothing in this section changes her box. Run all of it, keep every artifact,
and do not proceed to section 2 until 1.9 passes.

Create a dated evidence directory on the operator machine and put everything in
it. If the upgrade fails at 03:00, this directory is the only thing standing
between her and data loss.

```bash
EV=~/skyleigh-upgrade-$(date +%Y%m%d-%H%M)
mkdir -p "$EV"
SK="admin@100.110.80.124"      # Tailscale
```

### 1.1 Reach the box and pin the facts

```bash
ssh "$SK" 'sw_vers; uname -m; id -un; echo "HOME=$HOME"; uptime' | tee "$EV"/00-host.txt
```

Expect `HOME=/Users/admin`. Record the architecture (`arm64` vs `x86_64`) — it
selects the DMG in step 3.1.

### 1.2 Installed version and bundle integrity

```bash
ssh "$SK" '
  defaults read /Applications/Elevate.app/Contents/Info.plist CFBundleShortVersionString
  ls -la /Applications/Elevate.app/Contents/Resources/cli/elevate_cli/data/migrations_pg/
  codesign --verify --deep --strict /Applications/Elevate.app 2>&1 || true
  spctl --assess --type execute -vv /Applications/Elevate.app 2>&1 || true
' | tee "$EV"/01-bundle.txt
```

Expect `1.2.63`; migrations `0001`–`0034` **plus** her injected
`0035_crm_goals.sql` … `0039_contact_documents.sql`; and a codesign failure
(`a sealed resource is missing or invalid`) — the injected files broke the seal
long ago. A *valid* seal here would mean the guard has not re-injected, which
changes the picture; investigate before continuing.

Record the sha256 of each injected `.sql`. These are what step 1.9 compares
against the allowlist.

```bash
ssh "$SK" 'shasum -a 256 /Applications/Elevate.app/Contents/Resources/cli/elevate_cli/data/migrations_pg/003[5-9]_*.sql' \
  | tee "$EV"/02-injected-migration-hashes.txt
```

### 1.3 Snapshot every launchd job

```bash
ssh "$SK" '
  ls -la ~/Library/LaunchAgents/
  for p in ~/Library/LaunchAgents/*.plist; do
    echo "=== $p"; /usr/libexec/PlistBuddy -c Print "$p" 2>/dev/null
  done
' | tee "$EV"/03-launchagents.txt

ssh "$SK" 'launchctl print gui/$(id -u) | sed -n "/services/,\$p"' \
  | tee "$EV"/04-launchd-services.txt
```

`04-launchd-services.txt` is the authoritative "what was running before" list.
Section 7 restores from it. Known labels to expect:

| Label | What it does |
| --- | --- |
| `com.skyleigh.elevate-bundle-guard` | Runs `scripts/elevate-wedge-fixes-reapply.sh` — **re-injects her patches into the app bundle** |
| `com.skyleigh.elevate-dashboard-9120` | `elevate dashboard --no-open` on :9120, from the bundle's Python |
| `com.skyleigh.elevation-dashboard` | elevation-dashboard server on :8787 |
| `com.elevation.dashboard-auth-proxy` | node basic-auth proxy on :9122 |
| `com.elevation.dashboard-cloudflared` | Cloudflare tunnel — **publishes the above to the internet** |
| `ai.elevate.gateway` | Elevate gateway |
| ~13 more | `seller-updates-weekly`, `mir-daily-pull`, `ig-engage-daily`, `skyslope-audit`, `imsg-ingest`, `dedupe-contacts`, heartbeats, … |

**Uncertainty:** the :9121 `dashboard --tui` process is confirmed running but
its launchd label is not recorded here. Find it in `03`/`04` before section 2
— do not assume it shares the 9120 label. If it has no plist, it is either a
second `ProgramArguments` entry in an existing job or a hand-started process;
either way, identify it or you will not know how to stop or restart it.

### 1.4 Snapshot the live process and port picture

```bash
ssh "$SK" '
  pgrep -fl "elevate_cli.main|dashboard|cloudflared|basic-auth|elevation-dashboard" || true
  lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(9119|9120|9121|9122|8787)" || true
' | tee "$EV"/05-processes-ports.txt
```

### 1.5 Inventory `~/skyleigh-tools` and classify the 14 scripts

`~/skyleigh-tools` is a symlink to `~/elevate-premium`. Record both.

```bash
ssh "$SK" '
  ls -la ~/skyleigh-tools
  ls -la ~/skyleigh-tools/scripts/ | sed -n "1,80p"
  echo "=== scripts that write into the app bundle ==="
  grep -rln "/Applications/Elevate.app" ~/skyleigh-tools/scripts/ 2>/dev/null || true
  echo "=== scripts that copy .sql into migrations_pg ==="
  grep -rln "migrations_pg" ~/skyleigh-tools/scripts/ 2>/dev/null || true
' | tee "$EV"/06-skyleigh-tools.txt
```

The second and third greps are the ones that matter. Two scripts are already
known to copy fork `.sql` files into the bundle's `migrations_pg`:

- `recency-segment-reapply.sh` → drops in `0038_contacts_recency_segment.sql`
- `deploy-client-docs-phase1.sh` → drops in `0039_contact_documents.sql`

Under 1.2.98 those version slots are taken by `0038_lead_lists.sql` and
`0039_drop_chat_sessions_title_unique.sql`. Two files, same `NNNN` →
`discover()` raises `MigrationError: duplicate migration version 0038`
(`migrations.py:93`) — on **every** `connect()`, in **every** process. The
backend does not start, the dashboards do not start, the cron jobs do not run,
and nothing logs anything more useful than that one line.

Treat the grep output as authoritative over this list. If a third script also
writes `migrations_pg`, it is just as fatal.

### 1.6 Copy her fork source off the box `[READ-ONLY]`

```bash
ssh "$SK" 'cd ~/.elevate/elevate-current-src && git rev-parse HEAD && git status --porcelain | head -50' \
  | tee "$EV"/07-fork-src-state.txt

ssh "$SK" 'tar -czf /tmp/elevate-current-src.tgz -C ~/.elevate elevate-current-src'
scp "$SK":/tmp/elevate-current-src.tgz "$EV"/
ssh "$SK" 'rm -f /tmp/elevate-current-src.tgz'
```

Base commit should be `0056717e8`. Uncommitted work in that tree is patches
that may never have reached mainline — read `07-fork-src-state.txt` before
concluding the merge captured everything.

### 1.7 Back up the database `[READ-ONLY]` — do not skip

Her operational DB is `elevate_op_acct_f956ca5305ff5aaf` (the account key is
`acct_<sha1(license email)[:16]>`; it changes if she signs out and back in with
a different address, so confirm the name rather than assuming it).

The embedded Postgres listens on a **Unix socket only**, inside `pgdata`. Read
the socket directory and port from `postmaster.pid` rather than assuming:

```bash
ssh "$SK" bash -s <<'REMOTE' | tee "$EV"/08-databases.txt
PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
PGDATA=$HOME/.elevate/pgdata
PORT=$(sed -n 4p "$PGDATA/postmaster.pid")
SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
echo "port=$PORT sock=$SOCK"
"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d postgres -Atc \
  "SELECT datname FROM pg_database WHERE datname LIKE 'elevate_op%';"
REMOTE
```

If `postmaster.pid` is absent, the embedded Postgres is not running — start one
dashboard, or accept that the app will boot it on first `connect()`. Do not
guess the socket path.

Then dump. Custom format, so `pg_restore` can be selective in section 6:

```bash
ssh "$SK" '
  PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
  PGDATA=$HOME/.elevate/pgdata
  PORT=$(sed -n 4p "$PGDATA/postmaster.pid"); SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
  "$PGBIN/pg_dump" -h "$SOCK" -p "$PORT" -U postgres \
    -d elevate_op_acct_f956ca5305ff5aaf -Fc -f /tmp/skyleigh-preupgrade.dump
  ls -la /tmp/skyleigh-preupgrade.dump; shasum -a 256 /tmp/skyleigh-preupgrade.dump
' | tee "$EV"/09-dump.txt

scp "$SK":/tmp/skyleigh-preupgrade.dump "$EV"/
shasum -a 256 "$EV"/skyleigh-preupgrade.dump   # must match 09-dump.txt
ssh "$SK" 'rm -f /tmp/skyleigh-preupgrade.dump'
```

Also take a plain-SQL dump. `pg_restore` can fail on a corrupt custom archive;
a text dump can be salvaged by hand.

```bash
ssh "$SK" '
  PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
  PGDATA=$HOME/.elevate/pgdata
  PORT=$(sed -n 4p "$PGDATA/postmaster.pid"); SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
  "$PGBIN/pg_dump" -h "$SOCK" -p "$PORT" -U postgres \
    -d elevate_op_acct_f956ca5305ff5aaf | gzip > /tmp/skyleigh-preupgrade.sql.gz
'
scp "$SK":/tmp/skyleigh-preupgrade.sql.gz "$EV"/
ssh "$SK" 'rm -f /tmp/skyleigh-preupgrade.sql.gz'
```

A dump that has not been copied off the box and checksummed does not count as a
backup. Verify both files landed and are non-trivial in size before continuing.

### 1.8 Record the ledger and the pipeline distribution `[READ-ONLY]`

This is the exact query pair to run and keep. The first is the go/no-go input
for 1.9; the second is the before-picture that section 5 compares against.

Pipe the script over stdin (`ssh … bash -s`) rather than wrapping it in single
quotes — the SQL is full of quoted literals and the nested-quote form is where
these get mistyped.

```bash
ssh "$SK" bash -s <<'REMOTE' | tee "$EV"/10-ledger-and-pipeline.txt
set -e
PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
PGDATA=$HOME/.elevate/pgdata
PORT=$(sed -n 4p "$PGDATA/postmaster.pid")
SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
DB=elevate_op_acct_f956ca5305ff5aaf

"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d "$DB" <<'SQL'
\pset pager off

-- (a) Migration ledger. Sentinels live at 9001-9010; real migrations are < 9000.
SELECT version, name, sha256, applied_at
  FROM _schema_migrations
 WHERE version < '9000'
 ORDER BY version;

-- (b) Sentinel rows, recorded separately so a later diff is unambiguous.
SELECT version, name FROM _schema_migrations WHERE version >= '9000' ORDER BY version;

-- (c) Pipeline stage distribution. 'attempted' is the fork slug that mainline
--     0035 would have rejected; it must be visible here and unchanged later.
SELECT COALESCE(pipeline_status, '(null)') AS pipeline_status,
       COUNT(*) AS contacts
  FROM contacts
 GROUP BY 1
 ORDER BY contacts DESC, 1;

-- (d) Row counts of the tables the upgrade touches, so a silent loss is visible.
SELECT 'contacts' AS t, COUNT(*) AS n FROM contacts
UNION ALL SELECT 'contact_items', COUNT(*) FROM contact_items
UNION ALL SELECT 'contact_documents', COUNT(*) FROM contact_documents
UNION ALL SELECT 'crm_goals', COUNT(*) FROM crm_goals
UNION ALL SELECT 'deals', COUNT(*) FROM deals
UNION ALL SELECT 'lead_profile_flags', COUNT(*) FROM lead_profile_flags
ORDER BY 1;

-- (e) Is the fork pipeline CHECK still on contacts? Filter by NAME: the table
--     carries ~16 unrelated CHECK constraints and they all stay.
SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'contacts'::regclass
   AND conname = 'contacts_pipeline_status_check';
SQL
REMOTE
```

Expected shape of (a): a contiguous `0001`–`0034` from mainline, then her five
fork rows `0035_crm_goals` … `0039_contact_documents`. Expect (e) to show
`contacts_pipeline_status_check` — her `0036_pipeline_stages_expand.sql` added
the widened version. Mainline deliberately ends with **no** CHECK on that
column, so `0040` should drop it.

### 1.9 Go/no-go gate — do her hashes match the allowlist?

Compare `02-injected-migration-hashes.txt` and the `sha256` column of query (a)
against `_COMPATIBLE_PRIOR_HASHES` in the shipped build:

| Version | Required prior sha256 |
| --- | --- |
| 0035 | `9c59e596a8c1bc1871802ca91e9bb401c1dfd89c428ed9e9b9b880f24cd156b7` |
| 0036 | `b66be7804294839cadad0aa3cb890b3ad886c2703a4feb1642ef3e11cf39fe2d` |
| 0037 | `19d23a3f88a672dc2ae4d4b98ef46bace3cdb76f91ff01b3b5da046199e8586d` |
| 0038 | `d53d22e69a31f1a566c153622a7f0d64780daddc7aee2a7813a807c8edbe2d0c` |
| 0039 | `cb4eefc5d10553eb9a72f9a3c1c679166ad5b18a5eafe0d9910d1ccd0355ceb2` |

**0035 is the one that must match.** A miss there sends the runner down the
version-slot-reuse branch and applies the `'attempted_contact'` CHECK against
rows holding `'attempted'` — the fatal case in section 0.4.

0036–0039 mismatches are less severe but still stop the upgrade: mainline
0036/0038 are `IF NOT EXISTS` no-ops and 0039 drops an index, so they would
survive a mismatch, but a mismatch means the merge is not the fork you think it
is. Investigate before proceeding.

The 0036 hash is the weakest link: `0036_pipeline_stages_expand.sql` has no
mainline counterpart, so it cannot be re-derived from the repo. It can only be
confirmed against her live ledger. If it does not match, **stop** and get the
allowlist corrected from her actual row — do not edit the allowlist to whatever
her box reports without understanding why it differs.

**If any hash mismatches: stop. Do not continue to section 2.**

### 1.10 Stage the rollback artifact now, not later

Download the 1.2.63 Stable DMG for her architecture and put it in `$EV` before
you break anything. Section 6 assumes it is already in hand.

```bash
curl -fsSLO https://api.elevationrealestatehq.com/updates/Elevate-1.2.63-mac-arm64.dmg
shasum -a 256 Elevate-1.2.63-mac-arm64.dmg | tee -a "$EV"/11-rollback-artifact.txt
```

Substitute `-x64` if 1.1 reported `x86_64`. If the versioned artifact is no
longer on the update host, retrieve it from the release archive on
`5.78.46.234:/var/www/elevate-updates` before starting. **No 1.2.63 artifact in
hand means no rollback path — do not proceed.**

---

## 2. Neutralize the automation `[OWNER GO]`

From here on her dashboards are down and her tunnel is closed. Get the owner's
go, and tell her the window has started.

The order matters: **the bundle guard first**. It exists to re-inject her
patches after anything writes to the bundle. If it is still armed when you
install in section 3, it will re-inject fork `.sql` files into the new bundle's
`migrations_pg`, produce duplicate versions, and take the whole install down.

### 2.1 launchctl over SSH — the domain gotcha

Her jobs are user agents in `~/Library/LaunchAgents`, loaded into the GUI login
session. An SSH session is a *different* launchd domain. `launchctl bootout
<label>` with no domain silently addresses the wrong one and reports success
while the job keeps running. **Always specify `gui/$(id -u)`.**

`bootout` alone is also not enough: a job with `RunAtLoad` comes back at next
login. Use `disable` to persist, then `bootout` to stop the running copy.

```bash
UID_R=$(ssh "$SK" 'id -u')
```

### 2.2 Disarm the bundle guard `[DESTRUCTIVE]`

```bash
ssh "$SK" '
  L=com.skyleigh.elevate-bundle-guard
  launchctl disable  gui/$(id -u)/$L
  launchctl bootout  gui/$(id -u)/$L 2>&1 || true
  launchctl print    gui/$(id -u)/$L 2>&1 | head -3
'
```

Confirm: `launchctl print` must say `Could not find service`. Then confirm the
script is not running from anywhere else:

```bash
ssh "$SK" 'pgrep -fl elevate-wedge-fixes-reapply || echo "guard script: not running"'
```

Belt and braces — make the reapply scripts physically unable to run, since a
cron job or a hand-run could still invoke them:

```bash
ssh "$SK" '
  cd ~/skyleigh-tools/scripts
  for s in elevate-wedge-fixes-reapply.sh recency-segment-reapply.sh deploy-client-docs-phase1.sh; do
    [ -f "$s" ] && chmod a-x "$s" && ls -la "$s"
  done
'
```

Add any further script the 1.5 grep flagged as writing `migrations_pg` or
`/Applications/Elevate.app`. Section 7 decides which get their execute bit back.

### 2.3 Stop the dashboards, proxy, and tunnel `[DESTRUCTIVE]`

Close the tunnel **first** so nothing external hits a half-stopped stack.

```bash
ssh "$SK" '
  for L in com.elevation.dashboard-cloudflared \
           com.elevation.dashboard-auth-proxy \
           com.skyleigh.elevate-dashboard-9120 \
           com.skyleigh.elevation-dashboard \
           ai.elevate.gateway ; do
    echo "=== $L"
    launchctl disable gui/$(id -u)/$L
    launchctl bootout gui/$(id -u)/$L 2>&1 || true
  done
'
```

Then the :9121 `--tui` dashboard, using the label you identified in 1.3. If it
turns out to have no plist, stop it by PID from `05-processes-ports.txt` and
record how it was started — you will have to restart it by hand in section 5.

### 2.4 Stop the ~13 scheduled jobs `[DESTRUCTIVE]`

Do not hand-type these. Drive them from the snapshot so nothing is missed:

```bash
ssh "$SK" '
  for p in ~/Library/LaunchAgents/*.plist; do
    L=$(/usr/libexec/PlistBuddy -c "Print :Label" "$p" 2>/dev/null) || continue
    case "$L" in
      com.skyleigh.*|com.elevation.*|ai.elevate.*)
        launchctl disable gui/$(id -u)/$L
        launchctl bootout gui/$(id -u)/$L >/dev/null 2>&1 || true
        echo "stopped $L" ;;
    esac
  done
' | tee "$EV"/12-stopped-labels.txt
```

`12-stopped-labels.txt` is the re-enable list for section 5.7 and section 7.

### 2.5 Confirm everything is actually stopped

Three independent checks. All three must pass; `launchctl` alone has lied
before.

```bash
ssh "$SK" '
  echo "--- launchd services still present ---"
  launchctl print gui/$(id -u) | grep -E "skyleigh|elevation|elevate" || echo "none"
  echo "--- processes ---"
  pgrep -fl "elevate_cli.main|cloudflared|basic-auth|elevation-dashboard|gateway" || echo "none"
  echo "--- listening ports ---"
  lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(9119|9120|9121|9122|8787)" || echo "none"
' | tee "$EV"/13-stopped-confirmation.txt
```

All three must report `none`. If a dashboard is still bound to :9120, it is
holding an open Postgres connection and section 3's migration run will behave
unpredictably. Do not continue until this is clean.

### 2.6 Let the embedded Postgres settle

`pgserver` stops the postmaster when the **last** handle exits (it tracks PIDs
in `pgdata/.handle_pids.json`). With every Elevate process stopped it should
shut down cleanly. Confirm, and note that a stale PID left by a crashed process
can keep it up:

```bash
ssh "$SK" '
  cat ~/.elevate/pgdata/.handle_pids.json 2>/dev/null; echo
  pgrep -fl postgres || echo "postmaster: stopped"
'
```

A still-running postmaster is not itself a blocker — the migration step will
attach to it. It matters in section 6, where the database restore needs
exclusive access.

---

## 3. Install and first migration

### 3.1 Install with `ditto` `[DESTRUCTIVE]`

Never `cp -R` a signed app bundle — it does not preserve extended attributes
and breaks the code signature. Always `ditto`.

Keep the old bundle rather than replacing it in place: it is the fastest
rollback available.

```bash
# Copy the DMG over (substitute the published version and her architecture)
scp Elevate-1.2.98-mac-arm64.dmg "$SK":/tmp/

ssh "$SK" '
  set -e
  hdiutil attach -nobrowse -quiet /tmp/Elevate-1.2.98-mac-arm64.dmg
  MNT=$(ls -d /Volumes/Elevate* | head -1)
  # Preserve the current install, do not delete it.
  mv /Applications/Elevate.app "/Applications/Elevate 1.2.63 preupgrade.app"
  ditto "$MNT/Elevate.app" /Applications/Elevate.app
  hdiutil detach "$MNT" -quiet
  defaults read /Applications/Elevate.app/Contents/Info.plist CFBundleShortVersionString
  codesign --verify --deep --strict /Applications/Elevate.app && echo "codesign OK"
  spctl --assess --type execute -vv /Applications/Elevate.app 2>&1 | head -3
'
```

The new bundle **must** verify clean under both `codesign` and `spctl`. A
freshly installed bundle with a broken seal means either a bad artifact or
something already wrote into it — in which case the guard is not properly
disarmed. Go back to 2.2.

`[IRREVERSIBLE]` note: the preserved `Elevate 1.2.63 preupgrade.app` is a
`mv`, so its seal is intact and it is a genuine rollback target. Do not delete
it until the soak in section 7 is complete.

### 3.2 Verify the fork-reconcile machinery is in *this* bundle `[READ-ONLY]`

Before anything connects to her database:

```bash
ssh "$SK" '
  M=/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/data
  ls "$M/migrations_pg/" | tail -12
  echo "--- 0040 present? ---"
  test -f "$M/migrations_pg/0040_crm_fork_reconcile.sql" && echo YES || echo "NO — STOP"
  echo "--- allowlist ---"
  grep -A 20 "_COMPATIBLE_PRIOR_HASHES" "$M/migrations.py" | head -25
'
```

Requirements: `0035`–`0044` all present with **no gap at 0040**, and the
allowlist containing the five hashes from 1.9. If `0040` is missing, stop and
roll back via section 6.1 (bundle only — the database has not been touched
yet, so this is cheap).

### 3.3 Run the migrations deliberately, not by launching the app `[DESTRUCTIVE]`

Do not open the desktop app for the first migration. The app starts a backend,
a gateway, and background seeders at once; if a migration fails you get a
"backend unavailable" screen instead of the error. Drive it from the bundle's
Python so the failure, if any, lands on your terminal.

**Always pass `-B`, and set `PYTHONPYCACHEPREFIX`.** Running the bundle's
Python without `-B` writes `__pycache__` into `Contents/Resources/cli`, breaks
the code seal, and has cost a full reinstall before.

```bash
ssh "$SK" '
  APP=/Applications/Elevate.app/Contents/Resources
  PYTHONPATH="$APP/cli" \
  PYTHONNOUSERSITE=1 \
  PYTHONPYCACHEPREFIX="$HOME/Library/Caches/Elevate/python-pycache" \
  ELEVATE_HOME="$HOME/.elevate" \
  "$APP/runtime/python/bin/python3.12" -B -c "
from elevate_cli.data import connect
from elevate_cli.data import migrations
with connect() as conn:
    print(\"applied this run:\", migrations.run_pending(conn))
    print(\"head on disk:\", migrations.head_version())
"
' 2>&1 | tee "$EV"/14-migration-run.txt
```

Expected output: `applied this run: ['0040', '0041', '0042', '0043', '0044']`
and `head on disk: 0044`.

- `0035`–`0039` do **not** appear — they were relabelled and skipped by the
  allowlist. That is the correct, intended result.
- `0040` applies for real and carries mainline's net CRM schema.
- `0041`–`0044` apply for real but are no-ops: every statement in them is
  `CREATE TABLE / INDEX IF NOT EXISTS` or `ADD COLUMN IF NOT EXISTS` against
  objects she already has.

Failure modes and what they mean:

| Error | Cause | Action |
| --- | --- | --- |
| `duplicate migration version NNNN` | A reapply script re-injected a fork `.sql`. | Guard not disarmed. Remove the injected file, redo 2.2. |
| `MigrationDriftError` on 0035–0039 | Her hash is not in the allowlist. | Stop. 1.9 was skipped or wrong. Roll back. |
| `ADD CONSTRAINT … violated` / `check constraint "contacts_pipeline_status_check"` | The allowlist did not take; mainline 0035 ran. | Stop immediately, roll back the database (6.2). |
| `migration 0040_crm_fork_reconcile.sql failed` | Reconcile bug against her real schema. | Stop, capture the full error, roll back (6.2). This is a build defect, not a box defect. |

### 3.4 A note on `check_write_schema`

`run_pending()` finishes by logging `SCHEMA/CODE DRIFT: …` at CRITICAL if a
column the code writes has no migration behind it. It **logs and continues** —
it does not raise. Read `14-migration-run.txt` for that string. If it appears,
her INSERTs into that table will fail at runtime even though the migration
"succeeded". Treat it as a stop.

### 3.5 Verify the schema, not the ledger `[READ-ONLY]`

The ledger will look right whether or not `0040` did its job (see the scar note
in 0.4). Assert the actual objects.

```bash
ssh "$SK" bash -s <<'REMOTE' | tee "$EV"/15-post-migration-verify.txt
set -e
PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
PGDATA=$HOME/.elevate/pgdata
PORT=$(sed -n 4p "$PGDATA/postmaster.pid")
SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
DB=elevate_op_acct_f956ca5305ff5aaf

"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d "$DB" <<'SQL'
\pset pager off

-- 1. Ledger: 0035-0044 present, 0035-0039 relabelled to mainline names.
SELECT version, name FROM _schema_migrations
 WHERE version BETWEEN '0035' AND '0044' ORDER BY version;

-- 2. Columns mainline 0035-0039 create (0040 must carry them) plus her own from
--    0043. Selecting want.col, not c.column_name, so a MISSING row still names
--    the column it is missing.
SELECT want.col AS expected_column,
       CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'ok' END AS state
  FROM (VALUES
        ('tags_json'),('search_criteria_json'),('custom_fields_json'),
        ('documents_json'),('outreach_paused'),('lists_json'),
        ('recency_segment'),('recency_segment_set_at')) AS want(col)
  LEFT JOIN information_schema.columns c
    ON c.table_name = 'contacts' AND c.column_name = want.col
 ORDER BY want.col;

-- 3. lead_profile_flags Top 25 (mainline 0035).
SELECT want.col AS expected_column,
       CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'ok' END AS state
  FROM (VALUES ('top25'),('top25_at')) AS want(col)
  LEFT JOIN information_schema.columns c
    ON c.table_name = 'lead_profile_flags' AND c.column_name = want.col
 ORDER BY want.col;

-- 4. Tables from both sides of the merge. Expect all five.
SELECT want.t AS expected_table,
       CASE WHEN i.table_name IS NULL THEN 'MISSING' ELSE 'ok' END AS state
  FROM (VALUES ('account_goals'),('crm_settings'),('crm_goals'),
               ('contact_items'),('contact_documents')) AS want(t)
  LEFT JOIN information_schema.tables i ON i.table_name = want.t
 ORDER BY want.t;

-- 5. crm_settings columns from mainline 0036/0037/0038.
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'crm_settings' ORDER BY column_name;

-- 6. The PIPELINE check must be gone (mainline 0037 drops it; stages are
--    free-form now). Match by name — contacts carries ~16 other CHECK
--    constraints and every one of them must stay.
SELECT conname FROM pg_constraint
 WHERE conrelid = 'contacts'::regclass
   AND conname = 'contacts_pipeline_status_check';

-- 7. The chat-session title unique index must be gone (mainline 0039).
SELECT indexname FROM pg_indexes WHERE indexname = 'idx_chat_sessions_title_unique';

-- 8. Row counts — compare against pre-flight query (d). Nothing may have shrunk.
SELECT 'contacts' AS t, COUNT(*) AS n FROM contacts
UNION ALL SELECT 'contact_items', COUNT(*) FROM contact_items
UNION ALL SELECT 'contact_documents', COUNT(*) FROM contact_documents
UNION ALL SELECT 'crm_goals', COUNT(*) FROM crm_goals
UNION ALL SELECT 'deals', COUNT(*) FROM deals
UNION ALL SELECT 'lead_profile_flags', COUNT(*) FROM lead_profile_flags
ORDER BY 1;

-- 9. Her stage slugs survived. 'attempted' must still be here, unchanged.
SELECT COALESCE(pipeline_status, '(null)') AS pipeline_status, COUNT(*) AS contacts
  FROM contacts GROUP BY 1 ORDER BY 2 DESC, 1;
SQL
REMOTE
```

Pass criteria, all required:

1. Ten rows, `0035`–`0044`, with `0035`=`0035_crm_redesign.sql`,
   `0036`=`0036_crm_full.sql`, `0037`=`0037_crm_unpinned.sql`,
   `0038`=`0038_lead_lists.sql`,
   `0039`=`0039_drop_chat_sessions_title_unique.sql`,
   `0040`=`0040_crm_fork_reconcile.sql`, and `0041`–`0044` her renumbered files.
2. All eight `contacts` columns `ok`, none `MISSING`.
3. Both `top25` and `top25_at` `ok`.
4. All five tables `ok`.
5. `crm_settings` has `custom_columns_json`, `custom_stages_json`,
   `lead_lists_json`.
6. **Zero rows** — `contacts_pipeline_status_check` is gone. (Query 6 filters by
   name; the table's other CHECK constraints are expected and must remain.)
7. **Zero rows** — the unique index is gone.
8. Every count ≥ its pre-flight value from query (d).
9. `attempted` still present with the same count as pre-flight query (c).

Any failure → section 6.

---

## 4. Configure

The migration succeeded; the app is still not usable by her until these three
are set. All are reversible.

### 4.1 Document pack root

Mainline replaced her fork's hardcoded `/Users/admin/skyleigh-tools/...` paths
with a configurable pack root. Without it, `_document_pack_config()` raises
**409 `document_pack_not_configured`** on every document route — offer kit,
CPS, clause library, deal documents, buyer agency, CMA runner.

Two ways to set it. They differ in an important way.

**Option A — admin setup (recommended).** Stored in the database, so every
process sees it: the desktop app, both launchd dashboards, the gateway, and
each cron job. Survives reboot. Only works on the Stable channel (see 0.2).

No backend is running at this point in the sequence, so do this through the
bundle's Python rather than the HTTP API. Read the current value first and
**merge** — `update_admin_setup()` overwrites `status`, `provider`, `value`,
and `notes` wholesale for the key you send (`admin_setup.py:1418`), so a
partial write silently discards her existing forms-provider config.

The status matters as much as the root: if `documentPackRoot` is set in the
database but the item's status is not one of `configured` / `connected` /
`manual`, the resolver raises **409 `document_pack_not_verified`** instead — a
different error with the same practical effect.

```bash
ssh "$SK" '
  APP=/Applications/Elevate.app/Contents/Resources
  PYTHONPATH="$APP/cli" PYTHONNOUSERSITE=1 \
  PYTHONPYCACHEPREFIX="$HOME/Library/Caches/Elevate/python-pycache" \
  ELEVATE_HOME="$HOME/.elevate" \
  "$APP/runtime/python/bin/python3.12" -B -c "
import json
from elevate_cli.data import connect, get_admin_setup, update_admin_setup

with connect() as conn:
    snap = get_admin_setup(conn)
    item = next(i for i in snap[\"items\"] if i[\"key\"] == \"forms_provider\")
    print(\"BEFORE:\", json.dumps(item, indent=2, default=str))

    value = dict(item.get(\"value\") or {})
    value[\"documentPackRoot\"] = \"/Users/admin/skyleigh-tools\"
    update_admin_setup(conn, items=[{
        \"key\": \"forms_provider\",
        \"status\": \"configured\",
        \"provider\": item.get(\"provider\"),
        \"value\": value,
        \"notes\": item.get(\"notes\"),
    }])

    after = next(i for i in get_admin_setup(conn)[\"items\"] if i[\"key\"] == \"forms_provider\")
    print(\"AFTER:\", json.dumps(after, indent=2, default=str))
"
' | tee "$EV"/16-forms-provider.txt
```

Read `16-forms-provider.txt` and confirm the AFTER block still carries every
key the BEFORE block had, plus `documentPackRoot`, with `status: configured`.
`update_admin_setup` runs `_normalize_forms_provider_value()`, which rejects
any key that looks like a password or token — if it raises, the existing value
already held something it should not, and that needs fixing before you retry.

**Option B — environment variable.** `ELEVATE_DOCUMENT_PACK_ROOT` is read
directly and, unlike option A, **bypasses the status check** entirely
(`admin_deals.py:361-372`). Useful as a fallback or for a single job. The catch
is scope: a GUI-launched app does not inherit your shell environment. You would
have to add `EnvironmentVariables` to each launchd plist *and* use
`launchctl setenv` for the desktop app — and `setenv` does not survive reboot.

Use A. If you use B, set it in every plist you re-enable in 5.7 and record that
you did.

Verify the pack contents exist, whichever option you chose. The resolver
requires each asset to be a real file **inside** the root (it rejects anything
that resolves outside it):

```bash
ssh "$SK" '
  R=~/skyleigh-tools
  for f in knowledge/deals/forms/webforms-clauses.json \
           knowledge/deals/forms/fill-form-generic.py \
           knowledge/deals/forms/assemble-cps-terms.py \
           knowledge/deals/forms/cps-residential-fillable-template.pdf \
           scripts/cps-prep-package.sh scripts/cps-generate.py \
           scripts/offer-prep-forms.py scripts/offer-prep-package.py \
           scripts/deal-docs-list.py scripts/buyer-agency-fill.py \
           scripts/pull-listing-by-mls.js scripts/cma-phase-runner.py \
           scripts/digisign_engine.py ; do
    [ -f "$R/$f" ] && echo "ok   $f" || echo "MISS $f"
  done
'
```

A `MISS` is not automatically fatal — the route only fails for the asset it
actually needs — but every miss is a route she cannot use. Record them.

### 4.2 Her two settings

Her preferences are now first-class config, not fork patches. Add to
`~/.elevate/config.yaml`:

```yaml
admin:
  auto_advance_enabled: false
  buyer_agency_agreement_required: false
```

Why each matters:

- `auto_advance_enabled: false` — completing a stage checklist no longer moves
  the card and fires the next stage's automations before she has reviewed it.
  Manual stage moves and the accepted-offer stage 5→6 move are unaffected
  either way.
- `buyer_agency_agreement_required: false` — drops the "Buyer's Agency
  Agreement signed (BAEC)" item from the buyer onboarding checklist, which she
  does not collect and which would otherwise block the gate permanently.

Both are read at **call time** (`_admin_flag`, `config.py:3976`), so no restart
is needed and a later edit takes effect immediately. A malformed value falls
back to the shipped default (`true`) silently — so verify rather than assume:

```bash
ssh "$SK" '
  APP=/Applications/Elevate.app/Contents/Resources
  PYTHONPATH="$APP/cli" PYTHONNOUSERSITE=1 \
  PYTHONPYCACHEPREFIX="$HOME/Library/Caches/Elevate/python-pycache" \
  ELEVATE_HOME="$HOME/.elevate" \
  "$APP/runtime/python/bin/python3.12" -B -c "
from elevate_cli.config import admin_auto_advance_enabled, admin_buyer_agency_agreement_required
print(\"auto_advance_enabled:\", admin_auto_advance_enabled())
print(\"buyer_agency_agreement_required:\", admin_buyer_agency_agreement_required())
"
'
```

Both must print `False`. If either prints `True`, the YAML is malformed or
nested wrong — fix it before section 5.

### 4.3 Channel

Nothing to set. The channel is compiled in. Her install is `Elevate.app` with
`ELEVATE_HOME=~/.elevate` and preferred port 9119 — that *is* Stable. What you
must do is confirm nothing is forcing Beta at runtime:

```bash
ssh "$SK" '
  grep -rl "ELEVATE_RELEASE_CHANNEL" ~/Library/LaunchAgents/*.plist 2>/dev/null || echo "no plist sets it"
  grep -n "ELEVATE_RELEASE_CHANNEL" ~/.elevate/.env 2>/dev/null || echo "not in .env"
  ls -d ~/.elevate-beta 2>/dev/null && echo "WARNING: beta home exists" || echo "no beta home"
'
```

`ELEVATE_RELEASE_CHANNEL=beta` anywhere in her environment turns on the
forms-provider gate from 0.2 even on the Stable build. It must be absent.

---

## 5. Verify her workflow

Bring the stack back one layer at a time and check each before adding the next.
Do not restore everything and then look for problems.

### 5.1 Backend alone

Start one dashboard by hand, in the foreground, and watch it:

```bash
ssh "$SK" '
  APP=/Applications/Elevate.app/Contents/Resources
  PYTHONPATH="$APP/cli" PYTHONNOUSERSITE=1 \
  PYTHONPYCACHEPREFIX="$HOME/Library/Caches/Elevate/python-pycache" \
  ELEVATE_HOME="$HOME/.elevate" \
  "$APP/runtime/python/bin/python3.12" -B -m elevate_cli.main dashboard --no-open --port 9119
'
```

In a second session:

```bash
ssh "$SK" 'curl -fsS http://127.0.0.1:9119/api/status | head -40'
```

`/api/status` is one of the few unauthenticated endpoints; everything else
under `/api/` needs `X-Elevate-Session-Token`. Export it once:

```bash
ssh "$SK" 'echo "TOK=$(cat ~/.elevate/dashboard-session-token)"'
```

### 5.2 Document pack — the single best probe

`GET /api/admin/clause-library` is read-only and routes through the full
document-pack resolver. If it returns JSON, the pack root, the status check,
and the asset mapping are all correct at once.

```bash
ssh "$SK" '
  TOK=$(cat ~/.elevate/dashboard-session-token)
  curl -sS -o /dev/null -w "%{http_code}\n" \
    -H "X-Elevate-Session-Token: $TOK" http://127.0.0.1:9119/api/admin/clause-library
'
```

| Code | Meaning |
| --- | --- |
| `200` | Pack resolved. Continue. |
| `409 document_pack_not_configured` | 4.1 not applied, or not visible to this process. |
| `409 document_pack_not_verified` | Root set in the database but item status is not ready. |
| `409 document_pack_missing` | Root points somewhere that is not a directory. |
| `409 local_reference_form_route_disabled` | Something set the Beta channel. Redo 4.3. |

### 5.3 Offer kit and CPS

These are mutating routes; run them against a **test deal**, never a live file.
Create a throwaway deal in the UI first.

- Offer kit build: `POST /api/admin/deals/{deal_id}/offer-kit/build`
- Offer prep gather: `POST /api/admin/offer-prep/gather`
- Offer prep generate: `POST /api/admin/offer-prep/generate`
- Deal documents list: `GET /api/admin/deals/{deal_id}/documents`

Every one of these passes through
`_require_exact_beta_forms_provider_for_local_document_mutation()`. On Stable
it returns immediately and the route proceeds; a `409` with code
`local_reference_form_route_disabled` means the channel is wrong.

Delete the test deal afterwards.

### 5.4 Client documents

`GET /api/admin/contact-documents/{doc_id}/file` for a document that existed
before the upgrade — pick an id from pre-flight query (d). This proves her
`contact_documents` rows (migration 0044, formerly her 0039) survived the
renumbering and are still readable end to end.

### 5.5 Message Loop

```bash
ssh "$SK" '
  TOK=$(cat ~/.elevate/dashboard-session-token)
  curl -sS -H "X-Elevate-Session-Token: $TOK" \
    "http://127.0.0.1:9119/api/leads/message-loop?days=2" | head -c 400; echo
'
```

Expect `"ok": true` and non-zero counts.

Two things to know about this route. It **never returns a non-200** — on any
failure it returns `{"ok": false, "error": …}` with empty lists, so a green HTTP
status means nothing; you must read `ok`. And it does **not** use the document
pack root: `message_loop.py` hardcodes
`~/skyleigh-tools/scripts/message-loop-check.py` and
`/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3`. It
works only because her tools happen to live at exactly that path. Do not move
or rename `~/skyleigh-tools`, and note this inconsistency for a later cleanup.

### 5.6 Desktop app

Only now open `/Applications/Elevate.app` from the Finder. Confirm it reaches
the dashboard rather than "backend unavailable", and that the version in the
about/settings pane matches what you installed. Then quit it — she does not
primarily use the UI, and leaving it running competes for port 9119.

### 5.7 Restore her services, in dependency order `[DESTRUCTIVE]`

Stop the hand-started dashboard from 5.1 first. Then re-enable from
`12-stopped-labels.txt`, innermost first:

1. `ai.elevate.gateway`
2. `com.skyleigh.elevate-dashboard-9120`
3. the :9121 `--tui` dashboard
4. `com.skyleigh.elevation-dashboard` (:8787)
5. `com.elevation.dashboard-auth-proxy` (:9122)
6. `com.elevation.dashboard-cloudflared` — **last**
7. the ~13 scheduled jobs

For each:

```bash
ssh "$SK" '
  L=<label>
  launchctl enable    gui/$(id -u)/$L
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$L.plist 2>&1 || true
  sleep 3
  launchctl print gui/$(id -u)/$L | grep -E "state|last exit code|pid"
'
```

`last exit code = 0` and a live pid. A non-zero exit code repeating every few
seconds is a crash loop — stop it again and read
`~/Library/Logs/` plus the plist's `StandardErrorPath` before adding the next
layer.

**Leave `com.skyleigh.elevate-bundle-guard` disabled.** Section 7 decides its
fate; it must not run before then.

### 5.8 Ports, tunnel, and the guard

```bash
ssh "$SK" '
  lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(9119|9120|9121|9122|8787)"
  curl -sS -o /dev/null -w "9120=%{http_code}\n" http://127.0.0.1:9120/api/status
  curl -sS -o /dev/null -w "9121=%{http_code}\n" http://127.0.0.1:9121/api/status
  curl -sS -o /dev/null -w "9122=%{http_code}\n" http://127.0.0.1:9122/
  pgrep -fl cloudflared || echo "TUNNEL DOWN"
  launchctl print gui/$(id -u)/com.skyleigh.elevate-bundle-guard 2>&1 | head -2
'
```

:9122 should answer `401` unauthenticated — that is the basic-auth proxy doing
its job, not a fault. The guard line must still say `Could not find service`.

Then confirm the tunnel from **outside** her network, and re-verify the seal
one last time — if the guard somehow ran, this is where it shows:

```bash
ssh "$SK" 'codesign --verify --deep --strict /Applications/Elevate.app && echo "seal still OK"'
```

### 5.9 Owner sign-off `[OWNER GO]`

Report to the owner: version installed, the five allowlist matches, the nine
pass criteria from 3.5, the pack-root probe result, and any `MISS` from 4.1.
Do not tell her the upgrade is done until the owner has that.

---

## 6. Rollback

Two independent lanes. Try 6.1 first — most failures are bundle-side and the
database is fine.

### 6.1 Bundle only (database untouched)

Use when you have not yet run section 3.3, or 3.3 failed *before* applying any
migration (`applied this run: []`).

```bash
ssh "$SK" '
  set -e
  rm -rf /Applications/Elevate.app
  mv "/Applications/Elevate 1.2.63 preupgrade.app" /Applications/Elevate.app
  defaults read /Applications/Elevate.app/Contents/Info.plist CFBundleShortVersionString
  codesign --verify --deep --strict /Applications/Elevate.app 2>&1 || true
'
```

Expect `1.2.63` and the familiar broken seal. If the preserved bundle is gone,
install from the 1.2.63 DMG staged in step 1.10.

Then re-arm the guard so her patches go back into the bundle (7.2 covers what
it should re-inject), re-enable the services from `12-stopped-labels.txt`, and
re-run section 5's checks against 1.2.63.

### 6.2 Database restore `[IRREVERSIBLE]` `[OWNER GO]`

Use when section 3.3 applied a migration and the schema is wrong, or 3.5
failed. **This discards every change made to her database since the pre-flight
dump** — including anything she or a cron job wrote during the window. That is
why section 2 stops all thirteen jobs and why the window must be short.

Get the owner's explicit go. Then:

1. **Stop everything again.** Repeat 2.3–2.5 and confirm all three checks
   report `none`. `DROP DATABASE` fails while any connection is open.
2. Roll the bundle back first (6.1), so the restore runs against the binaries
   that produced the dump.
3. Confirm the postmaster is up but no Elevate process is attached, then:

```bash
ssh "$SK" bash -s <<'REMOTE'
PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
PGDATA=$HOME/.elevate/pgdata
PORT=$(sed -n 4p "$PGDATA/postmaster.pid")
SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
DB=elevate_op_acct_f956ca5305ff5aaf
# Prove nobody is connected before destroying anything.
"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d postgres -Atc \
  "SELECT count(*) FROM pg_stat_activity WHERE datname = '$DB';"
REMOTE
```

That count must be `0`. Copy the dump back onto her box, verifying the checksum
against `09-dump.txt` before you rely on it:

```bash
scp "$EV"/skyleigh-preupgrade.dump "$SK":/tmp/
ssh "$SK" 'shasum -a 256 /tmp/skyleigh-preupgrade.dump'   # must match 09-dump.txt
```

Then restore. Renaming instead of dropping is deliberate: it is reversible, it
preserves the failed state for diagnosis, and it costs only disk.
**Do not `DROP DATABASE`.**

```bash
ssh "$SK" bash -s <<'REMOTE'
set -e
PGBIN=/Applications/Elevate.app/Contents/Resources/runtime/python/lib/python3.12/site-packages/pgserver/pginstall/bin
PGDATA=$HOME/.elevate/pgdata
PORT=$(sed -n 4p "$PGDATA/postmaster.pid")
SOCK=$(sed -n 5p "$PGDATA/postmaster.pid")
DB=elevate_op_acct_f956ca5305ff5aaf
STAMP=$(date +%Y%m%d-%H%M)

"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d postgres \
  -c "ALTER DATABASE $DB RENAME TO ${DB}_failed_${STAMP};"
"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d postgres \
  -c "CREATE DATABASE $DB;"
"$PGBIN/pg_restore" -h "$SOCK" -p "$PORT" -U postgres -d "$DB" \
  --no-owner --no-privileges /tmp/skyleigh-preupgrade.dump

echo "--- restored database list ---"
"$PGBIN/psql" -h "$SOCK" -p "$PORT" -U postgres -d postgres -Atc \
  "SELECT datname FROM pg_database WHERE datname LIKE 'elevate_op%';"
REMOTE
```

`pg_restore` exits non-zero on any error but also emits warnings that are
harmless here (ownership, extensions). Read the output; do not assume a clean
exit. If the custom-format archive will not restore, fall back to the
plain-SQL dump from 1.7 (`gunzip -c … | psql`).

4. Re-run pre-flight queries (a), (c), (d), (e) from 1.8 and diff against
   `10-ledger-and-pipeline.txt`. Ledger, stage distribution, row counts, and the
   fork CHECK constraint must all match the pre-upgrade values exactly.
5. Re-arm the guard, re-enable the services, re-verify section 5 against 1.2.63.
6. Delete the `_failed_` database only after the owner has agreed the incident
   is closed.

### 6.3 If both lanes fail

Stop. Do not improvise against a live customer's data. Escalate to the owner
with `$EV` intact. Everything needed to rebuild her box from scratch is in
there: the dump, the plain-SQL dump, her fork source, the launchd snapshot, and
the plist bodies.

---

## 7. Aftercare

### 7.1 Soak before declaring victory

Leave the guard disabled and watch for a full business day plus one run of each
scheduled job. Specifically confirm:

- No `duplicate migration version` in any log.
- The nightly and weekly jobs (`seller-updates-weekly`, `mir-daily-pull`,
  `ig-engage-daily`, `skyslope-audit`, `imsg-ingest`, `dedupe-contacts`) each
  completed once with exit 0.
- `codesign --verify --deep --strict /Applications/Elevate.app` still clean.
- Row counts still ≥ the 3.5 values.

Only then delete `Elevate 1.2.63 preupgrade.app`.

### 7.2 Triage the 14 scripts

The classification below follows from what the merge absorbed. **Confirm each
against the actual script body** from `06-skyleigh-tools.txt` before acting —
this list is derived from the merged migrations and route changes, not from
reading all fourteen files.

**Now obsolete — their feature is in mainline. Must stay disabled.**

| Script | Superseded by |
| --- | --- |
| `elevate-wedge-fixes-reapply.sh` | The whole point of the merge. Re-running it re-breaks the seal and can re-inject fork `.sql` into `migrations_pg`. **Permanently disable.** |
| `recency-segment-reapply.sh` | Migration `0043_contacts_recency_segment.sql`. Injecting `0038_*` now collides with `0038_lead_lists.sql`. |
| `deploy-client-docs-phase1.sh` | Migration `0044_contact_documents.sql`. Injecting `0039_*` now collides with `0039_drop_chat_sessions_title_unique.sql`. |

Any further script the 1.5 grep flagged as writing `migrations_pg` or
`/Applications/Elevate.app` belongs in this table. Disable it the same way and
add it here.

Disable properly rather than deleting — deletion loses the record of what her
fork did:

```bash
ssh "$SK" '
  cd ~/skyleigh-tools/scripts
  mkdir -p ../obsolete-post-merge
  for s in elevate-wedge-fixes-reapply.sh recency-segment-reapply.sh deploy-client-docs-phase1.sh; do
    [ -f "$s" ] && git mv "$s" ../obsolete-post-merge/ 2>/dev/null || mv "$s" ../obsolete-post-merge/
  done
  ls -la ../obsolete-post-merge/
'
```

Then bootout, disable, and **delete** `com.skyleigh.elevate-bundle-guard.plist`
— a disabled plist that still exists will be re-bootstrapped by anyone tidying
up later, and its whole purpose is now actively harmful. Record its body in
`03-launchagents.txt` first; you already have it.

**Still needed — do not remove.** These are runtime dependencies, not patches:

| Script / asset | Why it still has a job |
| --- | --- |
| `scripts/message-loop-check.py` + `data/messages.db` | `message_loop.py` shells to it by hardcoded path. |
| `scripts/cps-prep-package.sh`, `cps-generate.py` | `cpsGather` / `cpsGenerate` document-pack assets. |
| `scripts/offer-prep-forms.py`, `offer-prep-package.py` | `offerForms` / `offerPackage`. |
| `scripts/deal-docs-list.py` | `dealDocuments`. |
| `scripts/buyer-agency-fill.py` | `buyerAgency`. |
| `scripts/pull-listing-by-mls.js` | `listingPull`. |
| `scripts/cma-phase-runner.py`, `capture-prospecting.sh` | `cmaRunner` / `cmaCaptureProspecting`. |
| `scripts/digisign_engine.py` | `digisignEngine`. |
| `knowledge/deals/forms/*` | Clause library, form engine, CPS assembler, all PDF templates. |

**`~/skyleigh-tools` is now a runtime dependency of the product, not a patch
kit.** It must not be moved, renamed, or deleted, and the `~/skyleigh-tools →
~/elevate-premium` symlink must stay. Anything that syncs that repo now needs
the same care as a deploy.

The remaining scripts from the fourteen are unclassified here because their
contents were not available while writing this. Classify each from
`06-skyleigh-tools.txt` using one rule: **does it write into
`/Applications/Elevate.app`?** If yes, it is obsolete and dangerous. If no, it
is probably still doing a job — leave it and record what it does.

### 7.3 Follow-ups to file

- `message_loop.py` ignores the document pack root and hardcodes both
  `~/skyleigh-tools` and the app bundle's Python path. It should resolve
  through `_document_asset` like every other fork feature did after the merge.
- Her `0036_pipeline_stages_expand.sql` was dropped rather than renumbered, and
  `0040` drops the CHECK it added. That is deliberate (mainline stages are
  free-form) but it means a pipeline slug typo is no longer caught by the
  database. Worth confirming the app-layer sanitiser covers her stage set.
- Add the pre-flight hash comparison from 1.9 to the release gate, so a future
  build that changes 0035–0044 cannot ship without someone noticing her box.

---

## Appendix A — open uncertainties

Stated plainly rather than guessed at. Resolve each on the box during
pre-flight; none should be assumed.

1. **`0040_crm_fork_reconcile.sql` does not exist yet** in the working tree at
   the time of writing. Step 3.2 is the gate. Its exact contents were not
   available, so 3.5's assertions are derived from the *net effect* of mainline
   0035–0039 rather than from reading 0040.
2. **The :9121 `--tui` dashboard's launchd label is unknown.** Identify it in
   1.3 or you cannot cleanly stop and restart it.
3. **Only 3 of her 14 scripts are classified with confidence.** The other
   eleven were not readable from the repo. 1.5's greps, not this document, are
   authoritative.
4. **Her `0036` hash cannot be cross-checked** against any file, since
   `0036_pipeline_stages_expand.sql` has no mainline counterpart. It can only be
   confirmed against her live ledger.
5. **Which cron jobs write to the database is unmapped.** They are all stopped
   in section 2, so it does not affect the upgrade, but it does affect how much
   data a 6.2 restore discards. Worth mapping before the window.
6. **Whether her `~/.elevate/skills` or `config.yaml` carry other fork
   customisations** beyond the two admin flags was not audited. Diff her
   `config.yaml` against `DEFAULT_CONFIG` during pre-flight.
7. **Stable feed publication of 1.2.98 has not happened.** Everything here is
   blocked on it.

## Appendix B — failure quick reference

| Symptom | Cause | Go to |
| --- | --- | --- |
| Every process dies on start, `duplicate migration version NNNN` | A reapply script injected fork `.sql` into the new bundle | 2.2, then remove the injected file |
| `MigrationDriftError` at 0035–0039 | Her hash not in `_COMPATIBLE_PRIOR_HASHES` | Stop; 1.9; roll back |
| `check constraint "contacts_pipeline_status_check"` violated | Allowlist did not take; mainline 0035 ran against `'attempted'` rows | 6.2 immediately |
| Every document route 409s `document_pack_not_configured` | Pack root unset or invisible to that process | 4.1 |
| 409 `document_pack_not_verified` | Root set in DB, item status not ready | 4.1, set `status: configured` |
| 409 `local_reference_form_route_disabled` | `ELEVATE_RELEASE_CHANNEL=beta` in scope | 4.3 |
| Cards auto-advance and fire automations she has not reviewed | `auto_advance_enabled` fell back to `true` | 4.2, check YAML nesting |
| Message Loop returns 200 with empty lists | Route never 500s; read `ok` | 5.5 |
| Backend "unavailable" after install, no migration error | Port contention with a hand-started dashboard | 5.1, stop duplicates |
| Bundle seal broken right after install | Guard still armed, or bundle Python run without `-B` | 2.2 / 3.3 |
