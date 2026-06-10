# Elevate 1.2.6 — release notes

A small, focused fix: your Executive Assistant can now see your leads and deals
directly in chat.

## Fix

- **The assistant can read your pipeline.** Asking the main chat "show me my hot
  leads" or "what's on the deal board" used to come back with "I can't query the
  database" — the leads/deals read tools were never wired into the chat's
  toolset, so the assistant genuinely couldn't see them. They're now available:
  `leads_overview`, `deals_overview`, and `lead_status` (all read-only).

- **Scoped work still routes to the right specialist.** Raw database queries and
  deal-board writes stay with the Admin agent — the assistant hands those off
  rather than doing them itself, so the EA sees everything but the specialist
  owns the work in its lane.

Read-only and entitlement-gated, so nothing changes for accounts without the
real-estate packs.
