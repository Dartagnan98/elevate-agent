# Elevate Agent

AI chief of staff for real estate agents. Run by Elevation Real Estate HQ.

Elevate Agent installs locally, connects to the realtor's tools, and keeps a
source-of-truth operating system for leads, listing admin, marketing, memory,
tasks, agent handoffs, and approvals. The base install is local-first. Paid real
estate packs unlock through Elevation Real Estate HQ.

## One-Shot Install

Works now:

```bash
npx --yes github:Dartagnan98/elevate-agent install
```

Future NPM registry install after the NPM bootstrap package is published:

```bash
npx @elevationrealestate/elevate install
```

Or keep the bootstrap command installed:

```bash
npm install -g @elevationrealestate/elevate
elevate install
```

Private beta install, only if the repo is private again:

```bash
export ELEVATE_GITHUB_TOKEN="$(gh auth token)"
npx @elevationrealestate/elevate install
```

If you are using a personal access token instead of GitHub CLI auth, set
`ELEVATE_GITHUB_TOKEN` to a token with read access to `Dartagnan98/elevate-agent`.

If NPM returns `404 Not Found` for `@elevationrealestate/elevate`, the bootstrap
package has not been published yet. Publish it from
`cli/packaging/npm/elevate` with `npm publish --access public`, or run the
`Publish NPM bootstrap` GitHub Action after adding the `NPM_TOKEN` repository
secret.

GitHub fallback while the NPM package is unpublished:

```bash
npx --yes github:Dartagnan98/elevate-agent install
```

Direct shell installer, once the base installer is published publicly:

```bash
curl -fsSL https://raw.githubusercontent.com/Dartagnan98/elevate-agent/main/cli/scripts/install.sh | bash
```

The installer downloads Elevate, creates the Python environment, links the
`elevate` command, syncs base bundled skills, creates `~/.elevate`, and
initializes the local SQLite stores:

- `~/.elevate/state.db` for sessions, messages, usage, and chat history.
- `~/.elevate/data/operational.db` for leads, profiles, deal files, admin
  action runs, phase gates, handoffs, tasks, and workflow state.
- `~/.elevate/memory_store.db` for memory, graph recall, and embedding metadata.

Git is optional for normal installs. If Git is available, the installer uses a
checkout. If Git is not available, it downloads the source archive and keeps
going. No hosted database project is required for the local runtime.

## After Install

```bash
elevate model      # choose or verify the LLM provider
elevate            # start the agent
elevate dashboard  # open the local dashboard
```

The base dashboard shows the local operating system: Agent Hub, Tasks, Memory,
Setup, Skills, Automations, and Project. Real estate sections like Leads,
Admin, Listings, Social Media, and Today unlock when the matching paid packs are
activated.

## Activate Paid Packs

```bash
elevate activate
```

Activation signs in to Elevation Real Estate HQ, stores a local license, syncs
pack entitlements, unlocks matching dashboard sections, and mounts paid skill
packs for the current session.

For beta or self-hosted HQ environments:

```bash
elevate activate --backend-url https://YOUR-ELEVATION-HQ-API
```

## Updates

```bash
elevate update
```

`elevate update` updates the app, reinstalls dependencies, rebuilds web assets
when needed, syncs base bundled skills, and restarts installed gateways. Archive
installs and Git installs both use the same command.

## What It Does

- Executive Assistant plus focused agents for admin, outreach, ads, marketing,
  and social media.
- Per-agent Telegram lanes so the Executive Assistant and focused agents can be
  configured separately.
- Local memory with durable facts, search, entity graph recall, trust scoring,
  journals, and optional semantic embeddings.
- Agent handoffs and wake loops for always-on workflows.
- Real estate skill packs for CMA, seller packages, listing admin, marketing,
  seller updates, document routing, photo cleanup, and transaction workflows.
- Browser and connector based workflows for MLS, SkySlope, ShowingTime, Gmail,
  Drive, calendar, CRM, ads, and other realtor-specific tools.

## Repository Layout

```text
elevate/
├── cli/      # local agent runtime, dashboard, gateway, skills, and SQLite data layer
├── backend/  # Elevation HQ licensing and paid skill-pack API
└── db/       # HQ API database migrations
```

Most users only need the one-shot installer. Developers can work from source:

```bash
git clone https://github.com/Dartagnan98/elevate-agent.git elevate-agent
cd elevate-agent/cli
./setup-elevate.sh
```

## Production Checks

```bash
cd cli
python3 -m py_compile elevate_cli/main.py elevate_cli/license.py elevate_cli/cloud_skills.py
npx tsc -b
./scripts/elevate-harness.sh smoke
./scripts/elevate-harness.sh memory
```

## License

MIT. See `cli/LICENSE` and `cli/NOTICE` for third-party attribution.
