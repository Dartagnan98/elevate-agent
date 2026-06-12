# Elevate 1.2.35 — release notes

Background results never interrupt you mid-thought.

## A finished sub-agent waits for a good moment

When a delegated background task finished at the same instant the agent was
mid-turn (for example, right after you steered it), the result could barge in
and collide with the running turn — the live thinking would freeze, the
spinner would hang, and follow-up messages could get stuck.

A completed sub-agent now behaves like a steer: it waits for a genuinely
quiet moment before the agent addresses it, and never interferes with the
work in progress. If you keep typing, the result simply folds into your next
turn. Either way it's always delivered — it can no longer be dropped or
double-reported.
