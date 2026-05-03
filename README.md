# Elevate

AI chief of staff for real estate agents. By Ctrl Strategies.

Subscription-gated skill library on top of an open-source agent runtime. Agents bring their own LLM key (Anthropic or OpenAI); Elevate adds the skills, the install, and the support.

## Current Work Handoff

As of May 3, 2026, the active build focus is the local-first Elevate Hub for real-estate operators.

The Hub should lead with actionable work, not passive contact inventory:

1. **Today / Leads top priority** — hot leads, open threads, draft follow-ups, timed tasks, and approval gates should appear before contact overview.
2. **Source inbox** — Apple Messages and Lofty CRM already feed normalized local source records. Composio social has a prepared `social` source folder/contract, but the actual Instagram/Facebook import worker still needs to be built.
3. **Draft follow-ups** — approval-gated message drafts now flow through the source inbox. The UI supports Approve, Edit, and Skip; approval marks a draft ready and must not auto-send.
4. **Contact overview** — useful for context, dedupe, and CRM/message matching, but it belongs below the active workboards.
5. **Next connector work** — build the Composio social importer so connected Instagram/Facebook DMs/comments/posts write normalized records into `data/sources/social/`.

Relevant implementation files:

- `cli/elevate_cli/source_connectors.py`
- `cli/elevate_cli/web_server.py`
- `cli/web/src/lib/api.ts`
- `cli/web/src/pages/RealEstateHubPages.tsx`

## Layout

```
elevate/
├── cli/        # the agent runtime (Python 3.11+)
│              #   + elevate_cli/license.py      — subscription gate
│              #   + elevate_cli/cloud_skills.py — fetch skills from backend
├── backend/    # Next.js API — login, license refresh, skill serve, stripe webhook
└── db/         # Supabase SQL migrations
```

## What Elevate adds on top of the upstream agent runtime

1. **License check on startup** — `cli/elevate_cli/license.py`. `~/.elevate/license.json` holds a JWT + refresh token. `cmd_chat` calls `ensure_valid()` before anything else; refreshes when <5min remain; exits with paywall msg if revoked.
2. **Cloud skill fetch** — `cli/elevate_cli/cloud_skills.py`. On chat start, fetches all subscription skills from backend and writes them to a tmp dir that is wiped on exit. Never persists to disk between sessions.
3. **Stripe-driven revocation** — `backend/src/app/api/stripe/webhook/route.ts` handles `customer.subscription.deleted` and marks all of that user's licenses `revoked=true`. The CLI's next refresh call gets 402, wipes the license, prompts re-login.

## Dev setup

### Backend

```bash
cd backend
npm install
cp .env.example .env.local   # supabase + stripe + JWT_SECRET
npm run dev                   # :3000
```

### Supabase

```bash
psql $SUPABASE_DB_URL -f db/001_init.sql
psql $SUPABASE_DB_URL -f db/002_password_hash.sql
```

### CLI

```bash
git clone YOUR_ELEVATE_REPO_URL elevate
cd elevate/cli
./setup-elevate.sh            # creates venv, installs, symlinks elevate bin
elevate subscribe              # log in with email+password -> license.json
elevate model                  # choose model/provider
elevate license status         # check token state
elevate cloud-skills list      # list skills at your tier
elevate cloud-skills fetch <name>
ELEVATE_BACKEND_URL=http://localhost:3000 elevate  # point CLI at local backend
```

Replace `YOUR_ELEVATE_REPO_URL` with the published Elevate repository URL.
For a local checkout, start from this repo and run `cd cli && ./setup-elevate.sh`.

Existing Hermes installs are not imported automatically. To migrate an old
`~/.hermes` profile into Elevate, run
`ELEVATE_MIGRATE_HERMES=1 ./setup-elevate.sh`. Set
`ELEVATE_FORCE_HERMES_MIGRATION=1` only when you intentionally want to overwrite
an existing Elevate config after writing a timestamped backup under
`~/.elevate/migration-backups/`. The migrator copies all non-ephemeral Hermes
profile files, rewrites legacy toolset names in `config.yaml`, safely backs up
`state.db`, and writes `migration-report.json`; setup fails if verification
finds missing files or mismatched SQLite table counts.

### Uninstall

```bash
elevate uninstall --full --dry-run  # preview full removal
elevate uninstall --full --yes      # remove gateway, command links, profiles, and ~/.elevate
elevate uninstall --yes             # remove command links/install copy but keep ~/.elevate data
```

Source checkouts are protected by default. Add `--delete-source-checkout` only
when you intentionally want the uninstaller to delete the Git checkout too.

### Harness

```bash
cli/scripts/elevate-harness.sh audit    # fail on non-allowlisted legacy coupling
cli/scripts/elevate-harness.sh smoke    # syntax, compile, launcher, uninstall dry-run
cli/scripts/elevate-harness.sh memory   # local SQLite + embedding retrieval smoke
cli/scripts/elevate-harness.sh memory-stress # local embedding volume/concurrency stress
cli/scripts/elevate-harness.sh memory-openai # live OpenAI embedding smoke with API key
cli/scripts/elevate-harness.sh context-efficiency # focused wrapper payload check
cli/scripts/elevate-harness.sh context-stress # prompt/schema ghost-tool stress
cli/scripts/elevate-harness.sh adversarial # bounded hostile prompt/tool/schema stress
cli/scripts/elevate-harness.sh all      # temp install, migration, and uninstall rehearsal
```

Elevate's local memory store uses Python's built-in SQLite. Semantic
embeddings are optional and can use OpenAI, Ollama, or an OpenAI-compatible
provider.

Dev flag to bypass the subscription gate while building: `ELEVATE_DEV_MODE=1 elevate`.

## License

MIT. The agent runtime is forked from the open-source Hermes-Agent project (Nous Research) — upstream attribution lives in `cli/LICENSE` and `cli/NOTICE`.
