# Elevate 1.2.43 — release notes

Updates now reach every part of the app on their own.

## Background services pick up updates even on busy accounts

The background service that handles scheduled jobs and Telegram could keep
running the previous version in memory after an app update: it waited for an
idle moment to restart, and on accounts with frequent scheduled jobs that
moment never came. It now restarts onto the new version within 30 minutes of
an update no matter how busy the account is, so fixes land everywhere without
a reboot.
