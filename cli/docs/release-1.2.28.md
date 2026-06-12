# Elevate 1.2.28 — release notes

Background work gets a kill switch and shows its real thinking.

## Stop button on background tasks

- **Kill from the panel.** Every running background task card now has a Stop
  button — it interrupts the subagent and suppresses its pending result, so
  nothing ghosts back into the chat minutes later.
- **Kill by asking.** "Kill it" now works: the agent has a real cancel control
  for its own dispatched delegations (it previously had to admit it couldn't
  stop them). Cancelling marks the task so any late result is dropped.

## Sub-agent drill-in shows real reasoning

Opening a running sub-agent used to show status faces ("(◔_◔) reflecting…")
where its thinking should be. The child's actual reasoning stream now relays
upward and renders as flowing paragraphs — exactly like the main chat.
