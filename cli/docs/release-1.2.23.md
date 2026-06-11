# Elevate 1.2.23 — release notes

Async sub-agents finally feel right, and a 1.2.22 database regression is fixed.

## Critical fix (everyone on 1.2.22 should update)

1.2.22's cortextOS cleanup edited a *comment* inside two already-applied database
migrations (`0022`, `0023`). That changed their checksums, and the app treats an
applied migration whose file changed as a hard error — so on 1.2.22, anything
that touched the database (deals, admin views, chat history) failed with
"migration 0022 on disk differs from applied copy." This release restores both
migration files to their applied content, so the database opens cleanly again.

## Background (async) sub-agents

When you hand work to a sub-agent in the background, the experience now matches
what you'd expect:

- **The result no longer shows up as if you typed it.** Previously the finished
  result was injected back as a fake user message (with an internal
  "[Delegated task result …]" tag). That's gone.
- **The main agent wakes up and responds.** When the sub-agent finishes, the
  orchestrator automatically re-engages, reads the result, decides whether it did
  the job, and replies to you in its own words — instead of dumping the raw output.
- **A clean "Sub-agent completed" card.** The completion shows as a compact card
  with a green (or coral, on error) status dot you can expand to see the summary —
  not a wall of text.

Legacy "[Delegated task result …]" messages from older sessions are now hidden
from the transcript.

## Notes

The blank sub-agent drill-in chat is still being investigated separately — the
data is there; it's a live-rendering issue we're pinning with a real run.
Carries the full 1.2.22 baseline (cortextOS scrub, nativized skills).
