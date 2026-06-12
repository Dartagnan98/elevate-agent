# Elevate 1.2.36 — release notes

Stopping a turn no longer breaks the next one.

## Live thinking stays put after an accidental stop

If you stopped the agent and then sent another message, the new turn's
thinking and reasoning would show for a second or two and then vanish — the
turn was still running, but the live view went dark, and it kept happening
even after leaving and reopening the chat.

The cause was the stopped turn finishing a moment late and its completion
landing on the new turn, clearing it. The chat now tags each completion to
the exact turn it belongs to, so a stopped turn's late wrap-up can no longer
interrupt the turn that's actually streaming.

## /compress now shows progress, marks done, and sticks

Running `/compress` had three rough edges: no "Compacting context" indicator
while it worked (the chat just sat silent for ~30s), no clear "Session
compacted" at the end, and — most importantly — it didn't survive leaving and
returning to the chat. Compression rotates to a fresh session under the hood,
but the manual command never saved the compressed history into it, so a
reload reverted to the full conversation and compacted it a second time (with
totally different numbers). All three are fixed: the pill shows during, the
session is marked compacted at the end, and the compression is now saved so
it holds across a resume.
