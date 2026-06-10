# Notes for skills audit — browser loop guard landed in tools/browser_tool.py

The browser tool now emits loop-level stuck signals. Skills that drive browser
work (surface-heartbeat, xposure-pcs / xposure-pcs-views, real-estate-admin
onboarding flows, anything using browser_navigate/click/type/snapshot) should
be updated to tell the model to HONOR these signals instead of relying on
skill-specific retry advice:

## New fields in browser tool results

1. `stuck_warning` (string) — appended when N consecutive state-affecting
   actions (default 3, config `browser.stuck_threshold`) leave the page
   fingerprint unchanged. Text instructs: wait + re-snapshot once, reload via
   browser_navigate, or STOP and report needs_operator if a
   login/CAPTCHA/2FA wall is visible. When a blocker is also classified the
   warning explicitly says "Report needs_operator with this blocker — do not
   keep retrying" (consent overlays instead get "click the dismiss button").

2. `page_blocker` (string) + a one-line `page-blocker: <kind>` notice
   prefixed to the snapshot text. Kinds: `login_wall`, `captcha`, `2fa`,
   `consent_overlay` (includes a "Likely dismiss: click @eN." hint when an
   accept/agree button is found), `paywall`, `antibot_interstitial`.

3. `action_budget` (string, e.g. "action 87/120") — appears once a session
   passes 50% of `browser.max_actions_per_session` (default 120, per
   task_id). Past the cap every further browser command returns
   `success: false` with an instruction to wrap up and report what was
   accomplished + what blocked it (and needs_operator if a wall blocked
   progress). Cap <= 0 disables.

## Suggested skill-instruction changes

- Where a skill currently says "retry the click / re-snapshot until it
  works", replace with: "if a tool result contains `stuck_warning`, follow
  it — do not loop. If it names a page-blocker other than consent_overlay,
  stop browser work and mark the run needs_operator (xposure-pcs:
  status.json `needs_operator`, with the blocker kind and URL as the
  reason)."
- xposure-pcs / xposure-pcs-views: the MFA → needs_operator pattern is now
  generalized at the tool level; the skill can reference `page_blocker:
  2fa` / `login_wall` as the trigger instead of describing MFA detection
  heuristics itself.
- Skills with long browse loops should mention `action_budget`: when the
  counter appears, prioritize finishing; when the budget error fires, stop
  issuing browser commands and write the partial-result summary.

## Telemetry (for any skill that reads surface activity)

Stuck/blocker events append `surface_activity` rows with event
`browser_stuck` (agent = ELEVATE_AGENT_ID or "browser"; metadata: task_id,
url, fingerprint_repeats, blocker, action_count). Dashboards/heartbeat
reviews can query where browser work gets stuck.

## Config keys (all optional, conservative defaults)

```yaml
browser:
  stuck_threshold: 3            # consecutive unchanged actions before warning
  max_actions_per_session: 120  # per-task_id command cap; <=0 disables
```

## Note on browser_use caps (item raised by ops)

There is NO autonomous browser_use loop in this repo —
`plugins/browser/browser_use/provider.py` and
`tools/browser_providers/browser_use.py` are session lifecycle only
(create/close a cloud CDP session); the `browser_use` pip library is not
imported anywhere. All commands against Browser Use sessions flow through
`_run_browser_command`, so the action budget + stuck detection above already
cap them. Managed-gateway sessions additionally carry a 5-minute server-side
session timeout. No `browser_use.max_steps` / `max_wall_seconds` keys were
added because nothing would read them.

## Anti-false-flag stealth for authorized authenticated sessions (new)

Elevate agents log into the **user's/clients' own** accounts (SkySlope, Lofty,
Xposure PCS, GHL, MLS portals) to do authorized work, and naive automation
trips bot-detection heuristics that false-positive on these legitimate sessions
(login walls, "unusual activity", soft challenges). `tools/browser_stealth.py`
makes that authorized automation not *look* like a crude bot so the walls come
up less. It is NOT challenge-defeat — it solves no CAPTCHA, bypasses no 2FA. A
real challenge still routes to `needs_operator` via the loop guard above.

Three levers, all default-on, all overridable in config.yaml:

```yaml
browser:
  persistent_profiles: true     # reuse a warm, logged-in per-site profile
  profile_dir: ~/.elevate/browser-profiles   # where per-domain profiles live
  fingerprint_hardening: true   # navigator.webdriver=undefined, WebGL/UA/etc
  human_pacing: true            # delay + keystroke jitter on state-affecting acts
  pacing_min_ms: 120            # pre-action delay floor
  pacing_max_ms: 650            # pre-action delay ceiling
  type_jitter_min_ms: 8         # per-keystroke jitter (typing)
  type_jitter_max_ms: 45
  preclick_scroll_prob: 0.15    # chance of scroll-into-view before a click
```

**Persistent per-site profiles — what skills should know:**
- The **single managed visible Chrome** (the download-and-go default on the
  user's box) already drives the user's own **warmly-cloned profile** — it is
  logged into everything the user is. That is the warm profile; nothing extra
  is needed for SkySlope/Lofty/GHL/Xposure when running on the user's machine.
- The **per-site profile resolver** maps a navigation URL's registrable domain
  → `<profile_dir>/<domain>/` for the **headless/local-sidecar** path (no
  managed window), so login state survives across tasks there too. First time a
  site is hit headless it's a cold login; after that it's warm.
- **Concurrency decision:** the managed path is a single Chrome shared across
  tasks via tabs (one user-data-dir, never two procs on it) — no corruption
  risk. The resolver hands out **named per-domain dirs** and exposes a PID
  lockfile (`mark_profile_locked` / `profile_is_locked`); if anything would
  launch a *second* Chrome on a held dir it must copy-on-write (snapshot +
  sync cookies back), never share the live dir. Don't point two concurrent
  headless launches at the same per-site dir.

**Pacing only touches state-affecting actions** (navigate/click/type/press/
scroll) — `browser_snapshot` and reads are never slowed. Set `human_pacing:
false` to disable entirely. Pacing sleeps and the internal clear/keystroke/
init-script commands are **unguarded** — they do NOT consume the loop-guard
action budget or reset the stuck counter, so stuck detection still works.
