# Elevate 1.2.33 — release notes

Your agents were never disconnected.

## Agent status tells the truth after updates

The last update gave every customer-facing agent Telegram capability by
default — and the dashboard then flagged any agent without its own dedicated
bot as needing attention, which read as a roster full of "disconnected"
agents. Nothing was broken. Now an untouched Telegram lane counts as
healthy: an agent is only flagged when a dedicated bot is half-wired (token
without chat target, or vice versa) or genuinely conflicting (a specialist
reusing the shared bot's token).

## Consolidated agents keep their bots

The agent consolidation (Transaction Coordinator → Admin, Ads and Listing
Marketing → Marketing & Ads, ISA Lead Nurture → Inside Sales, Market Analyst
→ Analyst) retired the old agent entries — but a retired agent's dedicated
Telegram bot silently stopped answering. The bot token now migrates to the
agent that absorbed the role, so the same bot keeps responding as its new
self. Boxes that already went through the consolidation heal automatically.
