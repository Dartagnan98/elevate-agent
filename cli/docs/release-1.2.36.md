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
