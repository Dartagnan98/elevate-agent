# Elevate 1.2.8 — release notes

Follow-up to 1.2.7's deals-board fix.

## Fix

- **No more demo showings in the ticker.** The upcoming-events ticker above the
  deals board fell back to hardcoded sample showings ("Tomorrow · 10:00 AM ·
  Sample Drive") when you had no real events. It now shows only your real feed
  — Google Calendar entries and deal milestone dates — and simply hides when
  there's nothing upcoming.

With this, every surface on the deals board is driven by your live data: the
deal cards (1.2.7) and the events ticker (1.2.8). The stage columns and
automation steps are static structure by design.
