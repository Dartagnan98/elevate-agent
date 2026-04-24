---
sidebar_position: 12
sidebar_label: "Built-in Plugins"
title: "Built-in Plugins"
description: "Plugins shipped with Elevate that run automatically via lifecycle hooks — disk-cleanup and friends"
---

# Built-in Plugins

Elevate ships a small set of plugins bundled with the repository. They live under `<repo>/plugins/<name>/` and load automatically alongside user-installed plugins in `~/.elevate/plugins/`. They use the same plugin surface as third-party plugins — hooks, tools, slash commands — just maintained in-tree.

See the [Plugins](/docs/user-guide/features/plugins) page for the general plugin system, and [Build a Elevate Plugin](/docs/guides/build-a-elevate-plugin) to write your own.

## How discovery works

The `PluginManager` scans four sources, in order:

1. **Bundled** — `<repo>/plugins/<name>/` (what this page documents)
2. **User** — `~/.elevate/plugins/<name>/`
3. **Project** — `./.elevate/plugins/<name>/` (requires `ELEVATE_ENABLE_PROJECT_PLUGINS=1`)
4. **Pip entry points** — `elevate_agent.plugins`

On name collision, later sources win — a user plugin named `disk-cleanup` would replace the bundled one.

`plugins/memory/` and `plugins/context_engine/` are deliberately excluded from bundled scanning. Those directories use their own discovery paths because memory providers and context engines are single-select providers configured through `elevate memory setup` / `context.engine` in config.

## Bundled plugins are opt-in

Bundled plugins ship disabled. Discovery finds them (they appear in `elevate plugins list` and the interactive `elevate plugins` UI), but none load until you explicitly enable them:

```bash
elevate plugins enable disk-cleanup
```

Or via `~/.elevate/config.yaml`:

```yaml
plugins:
  enabled:
    - disk-cleanup
```

This is the same mechanism user-installed plugins use. Bundled plugins are never auto-enabled — not on fresh install, not for existing users upgrading to a newer Elevate. You always opt in explicitly.

To turn a bundled plugin off again:

```bash
elevate plugins disable disk-cleanup
# or: remove it from plugins.enabled in config.yaml
```

## Currently shipped

### disk-cleanup

Auto-tracks and removes ephemeral files created during sessions — test scripts, temp outputs, cron logs, stale chrome profiles — without requiring the agent to remember to call a tool.

**How it works:**

| Hook | Behaviour |
|---|---|
| `post_tool_call` | When `write_file` / `terminal` / `patch` creates a file matching `test_*`, `tmp_*`, or `*.test.*` inside `ELEVATE_HOME` or `/tmp/elevate-*`, track it silently as `test` / `temp` / `cron-output`. |
| `on_session_end` | If any test files were auto-tracked during the turn, run the safe `quick` cleanup and log a one-line summary. Stays silent otherwise. |

**Deletion rules:**

| Category | Threshold | Confirmation |
|---|---|---|
| `test` | every session end | Never |
| `temp` | >7 days since tracked | Never |
| `cron-output` | >14 days since tracked | Never |
| empty dirs under ELEVATE_HOME | always | Never |
| `research` | >30 days, beyond 10 newest | Always (deep only) |
| `chrome-profile` | >14 days since tracked | Always (deep only) |
| files >500 MB | never auto | Always (deep only) |

**Slash command** — `/disk-cleanup` available in both CLI and gateway sessions:

```
/disk-cleanup status                     # breakdown + top-10 largest
/disk-cleanup dry-run                    # preview without deleting
/disk-cleanup quick                      # run safe cleanup now
/disk-cleanup deep                       # quick + list items needing confirmation
/disk-cleanup track <path> <category>    # manual tracking
/disk-cleanup forget <path>              # stop tracking (does not delete)
```

**State** — everything lives at `$ELEVATE_HOME/disk-cleanup/`:

| File | Contents |
|---|---|
| `tracked.json` | Tracked paths with category, size, and timestamp |
| `tracked.json.bak` | Atomic-write backup of the above |
| `cleanup.log` | Append-only audit trail of every track / skip / reject / delete |

**Safety** — cleanup only ever touches paths under `ELEVATE_HOME` or `/tmp/elevate-*`. Windows mounts (`/mnt/c/...`) are rejected. Well-known top-level state dirs (`logs/`, `memories/`, `sessions/`, `cron/`, `cache/`, `skills/`, `plugins/`, `disk-cleanup/` itself) are never removed even when empty — a fresh install does not get gutted on first session end.

**Enabling:** `elevate plugins enable disk-cleanup` (or check the box in `elevate plugins`).

**Disabling again:** `elevate plugins disable disk-cleanup`.

## Adding a bundled plugin

Bundled plugins are written exactly like any other Elevate plugin — see [Build a Elevate Plugin](/docs/guides/build-a-elevate-plugin). The only differences are:

- Directory lives at `<repo>/plugins/<name>/` instead of `~/.elevate/plugins/<name>/`
- Manifest source is reported as `bundled` in `elevate plugins list`
- User plugins with the same name override the bundled version

A plugin is a good candidate for bundling when:

- It has no optional dependencies (or they're already `pip install .[all]` deps)
- The behaviour benefits most users and is opt-out rather than opt-in
- The logic ties into lifecycle hooks that the agent would otherwise have to remember to invoke
- It complements a core capability without expanding the model-visible tool surface

Counter-examples — things that should stay as user-installable plugins, not bundled: third-party integrations with API keys, niche workflows, large dependency trees, anything that would meaningfully change agent behaviour by default.
