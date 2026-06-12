# Elevate 1.2.37 — release notes

Reasoning stays whole, and long delegated jobs stop getting killed.

## Reasoning isn't truncated after a turn finishes

The agent's reasoning is shown the same way as before, but it's no longer cut
off once the turn completes — you now see the full thought, not a trimmed or
"not quite right" version, including after reloading the chat.

## Delegated subagents can run long jobs to completion

Delegated subagents were capped at 10 minutes by a stale config default,
which killed legitimately long work — bulk WEBForms/PDF downloads, multi-step
research, browser automation — partway through. The default is now 4 hours,
and existing installs are bumped automatically (unless you set your own
value). The internal "looks stuck" detector is also tunable now, so a long
job can be configured to run until it's actually done.
