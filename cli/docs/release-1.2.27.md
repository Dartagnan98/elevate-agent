# Elevate 1.2.27 — release notes

Steering gets decisive.

## Steer cuts in mid-think

Until now, a message steered into a running turn waited for the next safe
boundary — which, mid-reasoning, could mean watching the agent think down the
wrong path for a long time before your correction landed.

- **Mid-think: it cuts.** A steer that arrives while the model is still
  reasoning aborts the in-flight call on the spot, discards the partial
  thinking, and re-issues the request with your guidance folded in. The agent
  redirects within seconds.
- **Almost done: it waits.** If the final answer is already streaming, the
  call is left to finish — your steer applies the moment the answer completes,
  so a nearly-finished result is never thrown away.
- Works in the dashboard and on every platform chat, and follows steers
  forwarded into running delegations (sub-agents cut mid-think too).
- The steered bubble's chip reflects the new behavior and still flips to
  "Applied mid-run" the moment the injection actually happens.
