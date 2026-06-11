# Elevate 1.2.22 — release notes

The agents now speak Elevate, not a different product.

## What's fixed

The agent skills were bulk-imported from another system (cortextOS) and still
told agents to run commands that don't exist in Elevate — `cortextos bus …`, a
background daemon, PM2, `$CTX_…` paths. That mismatch is why an agent would
sometimes flail or "do nothing visible": it was following instructions for the
wrong machine. This release scrubs all of it:

- **58 agent skills rewritten to Elevate-native** — every step now points at the
  real Elevate tools (agent bus, Tasks, Comms, Approvals, memory, manage_agent,
  cron, delegation) instead of the old daemon commands.
- **11 skills that only made sense in the other product were retired.**
- **Stale command text fixed app-wide** — error messages that said "Run
  `hermes tools`" now correctly say `/tools` (the actual command).
- The Skills page, onboarding, and agent presets are de-branded to Elevate.

On update, the old skill folder is cleaned up automatically so you don't end up
with duplicate stale copies.

## Under the hood

Skills now resolve under `agent-ops` (renamed from `cortextos`), names preserved
so agent loadouts are unaffected. Zero cortextOS references remain in shipped code
or skills. 104 tests pass. Carries the full 1.2.21 baseline.
