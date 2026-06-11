# Elevate 1.2.12 — release notes

Two fixes you'll see right away.

## Fixes

- **Chat list status is honest again.** The little indicator on each chat in the
  sidebar reflects what's actually happening: animated dots while the agent is
  working, amber when it's waiting on your input (a question/approval), and a
  green dot when it's done. It no longer spins "working" forever after a turn
  finishes — including when you navigate away mid-reply.
- **Telegram `/start` no longer dead-ends.** Texting `/start` to an agent's
  Telegram bot now properly continues into pairing/connection instead of going
  quiet, so you get a pairing code (or a welcome if you're already connected).
