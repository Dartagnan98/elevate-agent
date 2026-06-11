# Elevate 1.2.20 — release notes

Configure agents from the dashboard, and the assistant can reconfigure the fleet
properly — no more editing files by hand.

## What's new

- **Add/remove an agent's tools & skills in the Agent Hub.** Open an agent →
  Profile → the new **Tools & Skills** panel: toggle any toolset or skill on/off
  and Save. Applies to new/restarted agent sessions. Previously there was no way
  to do this in the UI — you had to ask the assistant, which it did unreliably.
- **The Executive Assistant can now reconfigure the fleet directly.** New
  `manage_agent` capability: it can add/remove toolsets and skills on any agent
  (including itself or *all* agents at once), change an agent's role/prompt,
  enable/disable, and create or retire agents — e.g. "give every agent Composio"
  now just works in one step instead of the assistant flailing.

## Safety

- **The app can no longer be corrupted by an agent editing its own code.** Writes
  to anything inside the app bundle are now hard-blocked at the tool level (it was
  possible for the assistant to patch bundled files, which breaks the macOS
  signature and causes "Elevate is damaged"). The assistant is steered to the
  proper reconfiguration tool and its own workspace instead.

## Under the hood

`manage_agent` and the UI both write through the existing per-account agent store
(`update_agent_config`) — never config files or bundled code. The bundle-write
guard lives in the file tool's sensitive-path check. Carries the 1.2.19 baseline
(per-call wall-clock budget + sidebar working indicator) and everything before.
