# Elevate 1.2.0 — release notes

A foundation release: surface heartbeat state and agent definitions move into
the per-account Postgres, so the dashboard and the agents operate on one source
of truth. Plus a wide bug + quality sweep across the harness, memory, skills,
and browser layers.

## Single source of truth (Postgres)
- Surface heartbeat state — config, goals, cycles, experiments, run history,
  activity feed, and the surface registry — moved from per-account JSON files
  into the account database (migrations 0024–0027). Dashboard cards and the
  agent's `agent_bus` tool now read/write the same rows; approvals are enforced
  in the data layer.
- Agent Hub definitions move from `config.yaml` to the per-account `hub_agents`
  table (migration 0026). Two accounts on one machine now get separate rosters.
- Existing data imports itself on first launch (idempotent, crash-safe); the
  legacy files are kept as frozen archives. Markdown artifacts (learnings, run
  transcripts, playbooks) stay file-based by design.

## New
- Six real-estate-native installable agent packs: Transaction Coordinator,
  Listing Marketing, ISA Lead Nurture, Market Analyst, Compliance Reviewer,
  Sphere Farming.
- Weekly memory recall-quality benchmark (self-recall hit rate, duplicate-
  injection rate, latency, injected-token cost) with regression alerting.
- Browser loop-guard: stuck detection, blocker classification (login/CAPTCHA/
  2FA/consent), per-session action budget, and `needs_operator` routing.
- Browser stealth for authorized sessions: persistent per-site logins,
  fingerprint hardening, human-like pacing.

## Fixes & quality
- Compaction now triggers on real server-reported token counts (0.90 ceiling)
  with a fixed output-headroom reserve, instead of estimates at a lower bar.
- Backfill cron progress is persisted crash-safe (it never persisted before —
  an undefined-name bug); delegated children return partial results on failure
  instead of a bare error; child rate-limit pressure is visible to the parent.
- Stale admin/outreach skills that pointed at removed SQLite stores are
  rewritten to the current data layer, with a self-clearing corrective resync
  that reaches even user-modified installs.
- Memory write quality: a durability gate keeps task-chatter out of long-term
  facts, near-duplicate facts merge at write time, and a conservative decay
  pass archives historical chatter (heavily-recalled facts are immune).
- Request-body limit on the OpenAI-compatible API restored to 10MB so vision
  and long-conversation requests aren't 413-rejected.

## Known
- The holographic-journal audit/replay/hygiene test cluster (~20 tests) has
  pre-existing failures unrelated to this release; tracked for a follow-up.
