# Elevate 1.2.1 — release notes

A chat-experience release: the conversation now shows the work it does, reads
like Claude, and lets you drill into and talk to subagents. Plus a round of
agent-loadout and UI fixes.

## Chat
- **Tool calls show what they actually did** — `ran npm run build`, `searched
  "psycopg"`, `edited App.tsx` — with full results, instead of "ran a command".
- **Reload == live**: a resumed turn now renders the same reasoning, diffs, and
  tool output it did live (no fidelity loss on reopen).
- **Subagents are first-class**: each shows inline in the turn, and you can
  **open any subagent's own thread to read it and message it** (a "Subagent"
  badge marks when you're in one). Works for past subagents, not just new runs.
- **Per-turn footer**: duration · model · tokens · cost under each answer; live
  status shows `↑ in · ↓ out` tokens as the turn works.
- Reasoning renders as quiet muted thinking (no bold section titles); the active
  tool **shimmers** while it runs.
- **Clickable local file/dir paths** in messages open the file preview.
- Artifacts no longer pin to the bottom of a message — a diff lives in its tool
  call; the Artifacts panel is grouped (Changes / Images / Documents / Outputs).
- Handoffs show inline ("Handed off to Admin") when work crosses agents.

## Agents & UI
- The Executive Assistant can now see the pipeline (`deals_overview` +
  `leads_overview`); the ISA Agent gets `leads_overview`.
- Sidebar: a new chat reads "General session" until titled and no longer
  flickers out mid-work; an untouched draft no longer lingers.
- Side panels default to ~1/3 width (still drag-resizable).

## Font
- Anthropic Sans Display is the primary UI font (renders where installed,
  falls back to Geist).
