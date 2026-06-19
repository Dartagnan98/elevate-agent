# Elevate Support Runbook

Updated: 2026-06-19

Use this when a customer reports that the desktop app, local agent runtime,
gateway, chat, updates, uploads, or platform sends are broken. Keep support
intake evidence-based: collect versions, route status, and redacted diagnostics
before asking for screenshots or private chat content.

## First Questions

- What exact app version is installed? Ask for `Elevate -> About Elevate` or run:
  `defaults read /Applications/Elevate.app/Contents/Info CFBundleShortVersionString`
- Is this a fresh install, upgrade, or first launch after an update?
- What path is failing: app boot, sign-in, chat, tools, upload/preview, update,
  cron/heartbeat, Telegram, WhatsApp, Apple Messages, or another connector?
- Is the user on Apple Silicon or Intel, and which macOS version?
- Did the failure start after the app updated, after credentials changed, or
  after macOS permission prompts?

## Safe Diagnostics

Prefer local redacted diagnostics first:

```bash
elevate debug share --local --session <session_id>
```

If there is no session id:

```bash
elevate debug share --local
```

For remote sharing, do not use `--no-redact`. Remote `--no-redact` is blocked by
the CLI, and support should not ask for raw prompts, raw messages, tokens, local
paths, or full unredacted stack payloads.

## First Checks

```bash
git status --short
tail -n 120 ~/Library/Logs/Elevate/main.log
tail -n 120 ~/.elevate/logs/gateway.error.log
curl -s http://127.0.0.1:9120/api/status | python -m json.tool
```

If the app picked a different local port, get it from `main.log` startup lines
or check ports near `9119-9129`.

## Desktop Boot

- If the app opens but stays on loading, check `main.log` for
  `window:load-dashboard`, `dashboard-loaded`, `backend-unavailable`, and
  `window:dashboard-retry-exhausted`.
- If loading resolves to setup, the local runtime was not reachable. Use the
  Install/Retry buttons first; they should show visible result text and re-enable.
- If the app closes and will not reopen, confirm `activate` recreates the main
  dashboard window and that only the overlay window is left hidden.

## Sign-In And License

- Use `/link` device-code sign-in when password login is blocked.
- Check `~/.elevate/license.json` exists and has mode `0600`.
- Do not paste license tokens into tickets. If a token appears in logs, treat it
  as sensitive and rotate it.
- If startup refresh fails but `refresh_token` exists, the app should leave the
  dashboard open and retry in the background instead of forcing a modal.

## Chat And Agent Turns

- Ask for the session id shown in the app or in `elevate debug share --local`.
- Confirm session recorder events exist under `~/.elevate/logs/session-events/`.
- The recorder must contain content-free event metadata, not raw prompts or raw
  message bodies. If needed, collect:
  `elevate debug share --local --session <session_id> --last 30m`
- For blank or vanished answers, check `blank-trace.log` and confirm secrets are
  redacted before sharing.

## Uploads And Previews

- File previews are allowed only from scoped preview roots and must not serve
  `license.json`, `.env`, `credentials.json`, or symlink escapes.
- Upload failures should return generic messages such as `Upload failed`, not
  local filesystem paths.
- Oversized uploads should return `413` and remove partial files.

## Gateway, Cron, And Heartbeats

- Check `~/.elevate/logs/gateway.error.log` for skipped cron jobs, platform
  setup failures, and stale job errors.
- Check launchd status if the gateway is missing or stale:
  `launchctl print gui/$(id -u)/ai.elevate.gateway`
- If a gateway version changed but the plist is stale, run `elevate gateway install`
  rather than only kickstarting the old job.

## Platform Sends

- Telegram: confirm bot token and target chat/channel are both configured.
- WhatsApp: distinguish `whatsapp_not_paired` from bridge missing or transport
  failure; pairing is an owner action.
- Apple Messages/SMS: see [mac-sms-transport.md](mac-sms-transport.md). The
  foreground desktop app drains `~/.elevate/sms-outbox`; missing `imsg` should
  create a visible result JSON with `ok: false`.

## Updates And Rollback

- Update checks are only valid in packaged builds. Unpacked app directories
  should skip updater checks when `app-update.yml` is absent.
- For a suspected bad update, preserve the current installed app before replacing
  it:
  `cp -R /Applications/Elevate.app /Applications/Elevate.app.backup-$(date +%Y%m%d-%H%M%S)`
- Verify the replacement app before launch with the installed runtime smoke.

## Escalation

Escalate as a release blocker when:

- App boot cannot reach dashboard or setup.
- Login/license refresh loses a valid session.
- Debug/share output leaks tokens, prompts, messages, or full local paths.
- Upload/preview can read arbitrary local files.
- Gateway cannot recover after reinstall or launchd bootstrap.
- Platform send failures do not leave visible status/log evidence.
