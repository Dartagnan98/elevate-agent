# Elevate 1.2.41 — release notes

Steering feels like steering, waits look alive, and crons stop repeating
themselves.

## Steering joins the run instead of ending it

Sending a steer mid-run no longer makes the turn settle to "Worked for Ns"
with your steer hanging below it. The run keeps going as one continuous
piece of work: a green "Conversation steered · +43s" row drops into the step
timeline at the exact moment your message was injected — the same way tool
calls show up — and the thinking continues underneath.

## No more 30-second blank stares

A long message into a big conversation can take the model 20-40 seconds to
ingest before the first reasoning appears. The turn now shows a live animated
"Thinking…" row with the running timer from the moment you send, on every
message, until real reasoning starts streaming.

## Crons stop saying everything twice — and stop repeating themselves

- Cron deliveries showed two stacked intro lines ("I ran X — here's what I
  found:" on top of "Just ran X — here's what happened:"). One title now.
- If a scheduled job would deliver substantially the same update it sent
  within the last 4 hours, it stays quiet. The run still happens and is
  logged — you're just not re-pinged with the same blocked-items list.
  Tune or disable with `cron.dedupe_window_hours` / `cron.dedupe_similarity`.
- You can now set your own formatting rules for every cron update with
  `cron.response_style` in config.yaml (or per job with `response_style`) —
  e.g. "3 bullets max, lead with anything that needs me."
