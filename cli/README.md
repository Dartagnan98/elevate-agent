# Elevate

AI chief of staff for real estate agents. By Ctrl Strategies.

## What it is

A terminal-based AI agent that runs on the user's machine, connects to their tools (GHL, SkySlope, Google Workspace, Meta/Google Ads), and executes real estate workflows. BYOK — bring your own Anthropic or OpenAI key.

Paid subscription unlocks access to the Ctrl Strategies skill library: CMA generation, listing pipeline automation, seller reports, outreach scripts, pricing strategy.

## Install

```bash
git clone YOUR_ELEVATE_REPO_URL elevate
cd elevate/cli
./setup-elevate.sh
```

Replace `YOUR_ELEVATE_REPO_URL` with the published Elevate repository URL.
For a local checkout, run `cd cli && ./setup-elevate.sh` from the repository
root.

`setup-elevate.sh` creates a local virtual environment, installs the default
desktop bundle, links `elevate` into `~/.local/bin`, syncs bundled skills, and
seeds `~/.elevate/SOUL.md` when missing.

If an older Hermes install exists at `~/.hermes`, setup can migrate config,
auth, sessions, skills, memories, cron jobs, and secrets into `~/.elevate`.
Migration is opt-in for standalone Elevate installs. Use
`ELEVATE_MIGRATE_HERMES=1 ./setup-elevate.sh` when you intentionally want to
import the old profile. Setup copies all non-ephemeral Hermes profile files,
rewrites legacy toolset names in `config.yaml`, safely backs up `state.db`, and
writes a `migration-report.json`; verification failures stop the install.

## First run

```bash
elevate subscribe       # authenticate with your Elevate subscription
elevate model           # choose model/provider
elevate                 # start chatting
elevate gateway install # optional: run Telegram/Discord/cron in the background
```

## Uninstall

```bash
elevate uninstall --full --dry-run  # preview full removal
elevate uninstall --full --yes      # remove gateway, command links, profiles, and ~/.elevate
elevate uninstall --yes             # remove command links/install copy but keep ~/.elevate data
```

Source checkouts are protected by default. Add `--delete-source-checkout` only
when you intentionally want the uninstaller to delete the Git checkout too.

## Harness

```bash
./scripts/elevate-harness.sh audit    # fail on non-allowlisted legacy coupling
./scripts/elevate-harness.sh smoke    # syntax, compile, launcher, uninstall dry-run
./scripts/elevate-harness.sh memory   # local SQLite + embedding retrieval smoke
./scripts/elevate-harness.sh memory-stress # local embedding volume/concurrency stress
./scripts/elevate-harness.sh memory-openai # live OpenAI embedding smoke with API key
./scripts/elevate-harness.sh context-efficiency # focused wrapper payload check
./scripts/elevate-harness.sh context-stress # prompt/schema ghost-tool stress
./scripts/elevate-harness.sh adversarial # bounded hostile prompt/tool/schema stress
./scripts/elevate-harness.sh all      # temp install, migration, and uninstall rehearsal
```

Elevate's local memory store uses Python's built-in SQLite. Semantic
embeddings are optional and can use OpenAI, Ollama, or an OpenAI-compatible
provider.

## Architecture

- CLI (Python 3.11+) runs the agent loop locally
- Backend (Next.js, sibling `../backend/`) validates subscription + serves skills
- Skills live server-side and are fetched on invocation — never cached to disk
- Stripe webhook revokes licenses on subscription cancel

## License

MIT. The agent runtime is forked from the open-source Hermes-Agent project (Nous Research) — upstream attribution lives in `LICENSE` and `NOTICE`.
