# Elevate 1.2.2 — release notes

A security-hardening release. No user-facing feature changes; everything here
tightens the trust boundary around the desktop app and the local agent endpoint.

## Desktop
- The renderer now runs **sandboxed**. The preload bridge only exposes
  `contextBridge` + `ipcRenderer`, so renderer-side script injection can no
  longer reach Node.
- **External-link opening is allowlisted** to `http(s)` and `mailto` — a
  `file://` or OS-handler scheme can no longer be launched from a link.
- **Top-level navigation is locked** to the trusted local origin.
- **Permission checks are scoped** to microphone/media only (previously every
  permission auto-passed).
- A **Content-Security-Policy** is enforced on the dashboard origin (strict on
  scripts, embeds, and framing; permissive on fonts/images so rendering is
  unaffected).

## Agent endpoint
- The local API server **never runs keyless**. If no key is configured it
  auto-generates one, persists it `0600`, and requires a Bearer token on every
  request — closing the loopback CSRF / DNS-rebinding path to the agent's
  terminal tool.

## HQ backend (deployed separately)
- Admin search sanitizes PostgREST filter-grammar metacharacters before
  interpolation.
