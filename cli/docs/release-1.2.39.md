# Elevate 1.2.39 — release notes

Live chat streams that never go deaf, sessions that stay one session, and
compaction that waits until the window is actually full.

## Your open chat keeps streaming, no matter what else is looking at it

A session's live event stream was bound to a single connection, and anything
else resuming the same session — the sidebar, the agent hub panel, a second
window, a reconnect — silently took the stream away. The chat you were
watching went quiet mid-turn: no reasoning, no tool calls, no response until
you left the session and came back. The "truncated" reasoning some of you saw
was the same problem — you were reading the lossy catch-up snapshot instead of
the live stream. Sessions now broadcast to every connected viewer at once, so
the chat you're watching keeps rendering in real time regardless of what else
attaches.

## Compacting no longer splits your session in two

When a long conversation compacted, the continuation could appear as a
brand-new, untitled session containing only the latest response, while your
original session froze in place. The rotation step that links the new session
back to the old one was crashing halfway. It's fixed at three layers — the
crash itself, a guard so a future error can't strand the rotation halfway
again, and a self-heal that re-links any continuation that lost its parent.

## Compaction at 85% of the window, not 50%

Boxes set up before June carried the old 50% compaction threshold in their
config file, and an explicit value beats the new defaults — so those sessions
compacted when the context bar showed only ~50-60%. A config migration bumps
the stale default to 85%. If you deliberately set a custom threshold, it is
left alone.

## Slash command worker cleanup

Closing a session at the exact moment its slash-command worker was starting
could leak that worker process until the app quit. The race is now detected
and the worker is shut down.
