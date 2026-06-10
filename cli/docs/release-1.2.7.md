# Elevate 1.2.7 — release notes

A correctness fix for the deals board.

## Fix

- **No more demo deals on your board.** The Admin / deals kanban fell back to
  hardcoded sample listings ("Demo Listing", "Sample Drive", MLS DEMO…) whenever
  you had no real deals yet — so a freshly-onboarded account saw a fake pipeline
  instead of an empty board. The board is driven entirely by your live deals
  now; with none, you get a clean empty board, and your real deals show up as
  you add them.

The stage columns and per-stage automation steps are unchanged — only the
fabricated sample deal cards are gone.
