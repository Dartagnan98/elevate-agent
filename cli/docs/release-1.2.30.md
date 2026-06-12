# Elevate 1.2.30 — release notes

Browser automation stops going rogue.

## Agents use the managed browser, not hand-rolled Selenium

A WEBForms login session was observed rebuilding browser automation from
scratch through the terminal — Selenium scripts, raw CDP websockets, Chrome
launched on debug ports with custom profiles — instead of using the built-in
browser tools that already provide a visible, logged-in, persistent Chrome
window.

- **The WEBForms skill now has hard Browser Rules:** built-in `browser_*`
  tools only; the managed window already handles MFA "remember this browser"
  persistence; terminal-scripted browser automation is explicitly forbidden;
  and missing browser tools are reported as an environment blocker instead of
  worked around.
- **Fixed the install bug that made browser tools vanish:** a system Chrome
  used to satisfy the "browser" dependency check even when the `agent-browser`
  CLI (what the tools actually run on) was missing — so the self-installer
  never ran and the browser toolset stayed dead on those machines. The check
  now targets the CLI itself, and the lazy install fires as designed.
