# Elevate 1.2.11 — release notes

Foundation release for the chat-reliability work. No visible behavior change —
this lays the groundwork that makes the "a reply briefly disappeared" class of
glitch impossible to reproduce in the next release.

## Under the hood

- **Every chat message now has a stable identity.** Messages are persisted and
  streamed with their own durable id (separate from any external messaging
  platform id), so the app can reconcile what's on screen with what's saved by
  identity instead of guessing by content. Older messages keep working via a
  deterministic fallback id.
- **The id flows end to end** — through live streaming events, session resume,
  and the history API — and starts accruing on all new messages immediately.

A new transcript engine that uses these ids ships dark in this build and turns
on in the next release after a short soak.
