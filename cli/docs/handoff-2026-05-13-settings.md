# Handoff — Settings audit + Plugins manager UI

**Date:** 2026-05-13
**Scope:** `web/src/pages/ConfigPage.tsx`, `web/src/components/AutoField.tsx`, `web/src/contexts/PageHeaderProvider.tsx`
**Status:** Shipped. Web bundle rebuilt at `elevate_cli/web_dist/`.

---

## What landed

### 1. Settings page audit fixes

Ran `/audit` across the settings layout. Addressed accessibility, anti-patterns, and visual polish.

**Layout**
- Content column now `mx-auto max-w-4xl` so settings are visually centered, not pulled left.
- Sidebar and content scrollbars hidden via `[scrollbar-width:none] [&::-webkit-scrollbar]:hidden`. Scroll still works, the gutter just doesn't cut into the panes.
- Brightened muted text across sidebar nav and field labels to `text-foreground/70-/85` for readability against the warm dark surface.

**Card-grid anti-pattern**
- `SourceConnectorSettingsPanel` and `CrmIntegrationSettingsPanel` converted from `<Card>` chrome to flat `<section>` with `divide-y` list rows. Differentiates them from the CRM tile picker.
- Removed `line-clamp-2` truncation, `rounded-2xl` borders, and mono-uppercase headers in those panels.

**Accessibility**
- Added `aria-label`/`aria-labelledby` to inputs, switches, dialog regions, and icon-only buttons.
- `text-emerald-500` → semantic `text-success`. Matching `text-warning`/`text-destructive` substitutions where applicable.
- `AutoField` object fallback rewritten to horizontal row pattern with proper `aria-label={${label} – ${subKey}}` per nested input.

### 2. Plugins manager UI (new)

The Plugins category used to render `plugins.enabled` and `plugins.disabled` as raw comma-separated text inputs — the backend has real plugin discovery, the UI was just not using it.

**What's there now:** a `PluginsPanel` component that
- Fetches `/api/dashboard/plugins` on mount (existing endpoint, returns discovered manifests).
- Lists each plugin in a `divide-y` row: label, source badge (`user`/`bundled`/`project`), version, description, internal name.
- Each row has a `Switch` that adds/removes the plugin from `plugins.enabled` (and clears it from `plugins.disabled`).
- Rescan button hits `/api/dashboard/plugins/rescan` to pick up newly dropped plugin directories without restarting.
- Orphan section: shows names in `plugins.enabled` that didn't match any discovered manifest, with a one-click remove.

The raw `plugins.enabled` / `plugins.disabled` schema fields are filtered out of the generic field loop when the active category is `plugins` — the panel replaces them. The rest of `plugins.*` (the full `elevate-memory-store` sub-config) still renders normally below the panel.

**Files touched:**
- `web/src/pages/ConfigPage.tsx` — added `PluginsPanel`, wired into active-category render, filtered `plugins.enabled`/`plugins.disabled` from `activeFields`.
- `web/src/components/AutoField.tsx` — brightness + object fallback rewrite.
- `web/src/contexts/PageHeaderProvider.tsx` — overflow + scrollbar polish.

---

## How to verify

```sh
cd ~/elevate/cli/web
npx vite build   # writes to ../elevate_cli/web_dist/
# Restart the FastAPI dashboard server (port 9119) and reload /config
```

Hard-refresh the browser (cmd+shift+R) — the bundle hash changes every build, but stale service-worker copies can stick.

**Manual checks:**
1. `/config` → Plugins tab → see discovered plugins as rows with toggles, not raw text inputs.
2. Toggle a plugin off → click Save → re-open `/config` → still off.
3. Click Rescan → loading spinner → list refreshes.
4. Manually add a fake name to `plugins.enabled` via `~/.elevate/config.yaml` → reload `/config` → fake name appears in "Enabled but not found" with a remove button.

---

## Known follow-ups

1. **Per-plugin settings drilldown.** Currently the panel only toggles enabled state. Plugins like `elevate-memory-store` have ~25 sub-keys still rendered as a flat AutoField list below. A future pass could collapse those behind a "Configure" affordance on the plugin row itself.
2. **Plugin source filter.** Once user plugin count grows, a "User / Bundled / Project" filter chip row above the list would help.
3. **Plugin install path.** The empty-state copy says "drop a plugin directory under `~/.elevate/plugins/`" — could become a button that opens that path in Finder via a server endpoint.
4. **Description quality.** Many plugin manifests have empty/short descriptions. Not a code issue, but the UI would feel richer if manifests carried 1-2 sentences of "what this plugin does."

---

## Backend contracts used (unchanged)

- `GET /api/dashboard/plugins` → `PluginManifestResponse[]` — `web_server.py:6526`
- `GET /api/dashboard/plugins/rescan` → `{ ok, count }` — `web_server.py:6537`
- Config schema: `plugins.enabled: list`, `plugins.disabled: list` — `config.py:933`
- Plugin discovery scans (in order): `~/.elevate/plugins/`, `<repo>/plugins/memory/`, `<repo>/plugins/`, optionally `./.elevate/plugins/` when `ELEVATE_ENABLE_PROJECT_PLUGINS` is set.

No backend changes were needed — everything was already in place, the settings UI just wasn't using it.
