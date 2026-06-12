# Elevate 1.2.38 — release notes

No more compacting twice in a row.

## A compaction sticks the first time

When the agent compacted its context and you sent the next message, the
session could compact a second time right away. The compressed result of the
first compaction was being discarded in a rare timing case, so the next turn
saw the full conversation again and re-compacted it. The compaction is now
always saved, so it holds and the next turn starts from the compressed
context.
