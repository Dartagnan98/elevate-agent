# Elevate Agent

AI chief of staff for real estate agents. Run by Elevation Real Estate HQ.

Elevate Agent runs locally on the realtor's machine, connects to their tools,
and keeps a source-of-truth operating system for leads, listing admin,
marketing, memory, tasks, and agent handoffs. The core runtime is local-first.
Paid real estate skill packs unlock through Elevation Real Estate HQ.

## What It Does

- Executive Assistant plus focused agents for admin, outreach, ads, marketing,
  and social media.
- Local dashboard with Agent Hub, leads, admin board, listings, tasks,
  automations, memory, and approvals.
- SQLite source of truth under `~/.elevate` for sessions, memory, deal files,
  admin action runs, handoffs, and local workflow state.
- Per-agent Telegram lanes so the Executive Assistant and focused agents can be
  configured separately.
- Real estate skill packs for CMA, seller packages, listing admin, marketing,
  seller updates, document routing, and transaction workflows.
- Browser and connector based workflows for MLS, SkySlope, ShowingTime, Gmail,
  Drive, calendar, CRM, ads, and other realtor-specific tools.

## Install

One command installs Elevate and creates the local databases:

```bash
curl -fsSL https://raw.githubusercontent.com/Dartagnan98/elevate-agent/main/cli/scripts/install.sh | bash
```

The installer downloads Elevate, creates the Python environment, links the
`elevate` command, syncs base bundled skills, creates `~/.elevate`, and
initializes the local SQLite stores. Git is optional: if it is available the
installer uses a normal checkout, and if it is not available the installer
downloads the source archive automatically.

- `~/.elevate/state.db` for sessions, messages, usage, and chat history.
- `~/.elevate/data/operational.db` for leads, profiles, deal files, admin
  runs, phase gates, handoffs, tasks, and workflow state.
- `~/.elevate/memory_store.db` for local memory, graph recall, and embeddings
  metadata.

No hosted database project is required for the local runtime.

For a manual source checkout:

```bash
git clone https://github.com/Dartagnan98/elevate-agent.git elevate-agent
cd elevate-agent/cli
./setup-elevate.sh
```

If you already have a local checkout:

```bash
cd elevate/cli
./setup-elevate.sh
```

Setup creates the same local profile and databases as the one-line installer.

## One-Shot Activation

```bash
elevate activate
```

Activation logs in to the Elevation Real Estate HQ subscription service, stores
the local license, syncs paid pack entitlements, unlocks the matching dashboard
sections, and mounts available paid skill packs for the current session.
Production installers should provide `ELEVATE_BACKEND_URL` so activation knows
which Elevation HQ API origin to use.
For a manual beta install, pass it once and Elevate will save it locally:

```bash
elevate activate --backend-url https://YOUR-ELEVATION-HQ-API
```

`elevate subscribe` remains as a compatibility alias, but new installs should
use `elevate activate`.

After activation:

```bash
elevate model           # choose or verify the LLM provider
elevate                 # start the agent
elevate dashboard       # open the local dashboard
```

## Gateway

Use the gateway when agents should keep working outside the terminal through
Telegram, Discord, scheduled automations, or background handoffs.

```bash
elevate gateway setup
elevate gateway install
elevate gateway start
elevate gateway status
```

Agent-specific Telegram bot tokens and chat lanes are configured in Agent Hub
or through the local environment. Keep the Executive Assistant and Admin agent
on separate bot tokens when they need separate conversations.

## Memory And LightRAG-Style Recall

Elevate ships with a local SQLite memory store using durable facts, FTS5 search,
entity graph recall, trust scoring, journal organization, and optional semantic
embeddings. The built-in holographic memory provider includes LightRAG-style
local, global, hybrid, naive, mix, and prompt/context modes without requiring an
external LightRAG server.

```bash
elevate memory setup
elevate memory status
elevate memory organize --drain
elevate memory daily --force
```

Semantic embeddings are optional. Configure them in Agent Hub or through
`elevate memory setup` with OpenAI, Ollama, OpenAI-compatible endpoints, or the
local MiniLM option.

## Updates

```bash
elevate version
elevate update
```

`elevate update` pulls the latest code, reinstalls Python dependencies, rebuilds
web assets when needed, syncs base bundled skills, and restarts installed
gateways.
When the dashboard or gateway reports that an update is available, the user can
run one command:

```bash
elevate update
```

Gateway-triggered updates use:

```bash
elevate update --gateway
```

## Uninstall

```bash
elevate uninstall --yes             # remove command links/install copy, keep ~/.elevate
elevate uninstall --full --dry-run  # preview full removal
elevate uninstall --full --yes      # remove gateway, command links, profiles, and ~/.elevate
```

Source checkouts are protected by default. Add `--delete-source-checkout` only
when you intentionally want the uninstaller to delete the Git checkout too.

## Production Checks

```bash
python3 -m py_compile elevate_cli/main.py elevate_cli/license.py elevate_cli/cloud_skills.py
npx tsc -b
./scripts/elevate-harness.sh smoke
./scripts/elevate-harness.sh memory
./scripts/elevate-harness.sh adversarial
```

The local dashboard also exposes runtime posture through Agent Hub and the
Harness card.

## Architecture

- Python CLI runs the agent loop locally.
- Local FastAPI dashboard/API serves Agent Hub, chat, admin, leads, memory, and
  automation views.
- SQLite under `~/.elevate` is the local source of truth.
- Gateway runs background agents, Telegram/Discord lanes, cron jobs, and
  handoff drains.
- Elevation Real Estate HQ validates paid access and serves entitlement-gated
  real estate skill packs.
- Paid skills are mounted at runtime; local user data stays local unless a
  configured connector or workflow intentionally sends it out.

## License

MIT. See `LICENSE` and `NOTICE` for third-party attribution.
