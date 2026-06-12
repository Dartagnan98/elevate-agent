# Elevate 1.2.46 — release notes

Steering tells the truth, and the app opens fast.

## The app opens in ~2 seconds again

A change in 1.2.40 accidentally made every launch wait ~11 seconds on a
cosmetic macOS Dock call before showing anything. The window now appears
immediately and the Dock registration happens in the background.

## A steered run is one honest timeline

- Your steered message waits visibly in the queue bar ("applies at the next
  safe moment") and enters the conversation exactly where it was injected —
  with the green "Conversation steered" marker — never above thinking that
  was already on screen when you sent it.
- Thinking that arrives in buffered chunks now sits where it actually
  happened in the flow.
- If the run continues past an answer it had already written, that text
  stays in the timeline as its own block and the final answer stands alone —
  no more duplicated or vanishing text.
- One "Worked for" card per run — live, after leaving and returning, and
  when reopening the session later.

## Leaving and returning loses nothing

Re-entering a running session rebuilds the full timeline — complete
thinking, tool cards, steered messages, markers, in the original order. A
turn that finishes while you're away keeps its entire reasoning, not just
the last stretch.
