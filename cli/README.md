# Elevate

AI chief of staff for real estate agents.

Forked from [Hermes-Agent](https://github.com/NousResearch/Hermes-Agent) (MIT, Nous Research). See `NOTICE` and `LICENSE`.

## What it is

A terminal-based AI agent that runs on the user's machine, connects to their tools (GHL, SkySlope, Google Workspace, Meta/Google Ads), and executes real estate workflows. BYOK — bring your own Anthropic or OpenAI key.

Paid subscription unlocks access to the CTRL Strategies skill library: CMA generation, listing pipeline automation, seller reports, outreach scripts, pricing strategy.

## Install

```bash
cd cli
./setup-elevate.sh
```

## First run

```bash
elevate login           # authenticate with your subscription
elevate config llm      # point to your anthropic/openai key
elevate start           # start chatting
```

## Architecture

- CLI (Python 3.11+) runs the agent loop locally
- Backend (Next.js, sibling `../backend/`) validates subscription + serves skills
- Skills live server-side and are fetched on invocation — never cached to disk
- Stripe webhook revokes licenses on subscription cancel

## License

MIT — see `LICENSE` for upstream (Nous Research) attribution and `NOTICE` for fork modifications.
