# Elevate 1.2.9 — release notes

Background system jobs actually run now.

## Fix

- **Calendar sync, DB maintenance, and the freshness snapshot were silently
  failing on every desktop install.** The scheduled system scripts couldn't
  import the Elevate runtime (`ModuleNotFoundError: No module named
  'elevate_cli'`) because the script runner never told the child process where
  the bundled code lives. Fixed — the runner now passes its own runtime path to
  every script it launches.

What you'll notice: upcoming Google Calendar events flow into the deals-board
ticker again, deal-stage maintenance and CRM note pushes run on schedule, and
the account health snapshot stays fresh.
