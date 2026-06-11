---
name: oauth-rotation
category: agent-ops
description: "Rotate, refresh, or repair OAuth/provider credentials through Elevate's agent configuration and approval surfaces without exposing secrets."
triggers: ["oauth", "token rotation", "refresh token", "expired token", "connector auth", "reauthorize", "api key rotation", "credential rotation"]
---

# OAuth Rotation

Use this skill when an agent needs to rotate or repair OAuth credentials, API keys, refresh tokens, app passwords, webhook secrets, or provider-specific connector authorization.

Elevate keeps secrets out of agent reach by design. Agents do not edit credential files, environment variables, or any host config directly. An agent's job here is to identify which credential is unhealthy, get the new value stored by a human, then reconfigure the affected agent(s) through the **manage_agent** tool so the new credential is picked up. Anything that requires writing to a host file, editing a system shell, or restarting a process has no agent mechanism in Elevate and must be raised as a [HUMAN] task.

## Rules

1. Never print, summarize, or return raw secrets.
2. Never write credentials into prompts, Tasks, agent_handoffs, Comms, Activity, or memory.
3. You cannot store or rotate a secret yourself. Raise a [HUMAN] task to have the new credential stored, then reconfigure the agent(s) with **manage_agent**.
4. If a credential rotation affects external delivery, billing, deployment, legal, or user-facing communication, create an approval in **Approvals** (native) and wait for it to clear before reconfiguring.
5. After rotation, record only non-secret metadata: provider, account label, agent id, result, timestamp, and follow-up needed — via the **agent_bus** tool (action `log_event`).

## Elevate Mapping

- Credential reload after rotation -> reconfigure the agent with the **manage_agent** tool (read/inspect or update mode). Never edit files.
- Token / API-key / refresh-token edits -> raise a [HUMAN] task to store the value, then **manage_agent** so the agent reloads its config.
- Activity / event log of the rotation -> the **agent_bus** tool (action `log_event`).
- Human approval before a sensitive rotation -> native **Approvals**, or a `waiting_human` **agent_handoff** when no approval is queued.
- Per-agent channel / bot token repair -> reconfigure that agent's channel via **manage_agent**; route the operator request through native **Comms** + **agent_handoff** if another agent or a human must act.

## Procedure

1. Identify the unhealthy credential: provider, account label, and which agent(s) load it. To see what an agent has configured, inspect it through the **manage_agent** tool (read/inspect mode) — never read a file.
2. If the credential is missing or expired, raise a [HUMAN] task describing exactly which provider/account needs a fresh token or key. You cannot store it yourself.
3. If the rotation is sensitive (external delivery, billing, deployment, legal, user-facing comms), create an approval in native **Approvals** first. Hand the work off via **agent_handoff** (`waiting_human`) if it needs to park until a human acts.
4. Once the human confirms the new secret is stored, reconfigure every affected agent with the **manage_agent** tool so each one reloads its toolset/role config with the new credential. Updating a stored value does nothing for a running agent until **manage_agent** reapplies its configuration.
5. Log the rotation: use the **agent_bus** tool (action `log_event`) with action `credential_rotated`, level `info`, and metadata `{"provider":"PROVIDER","account":"LABEL","scope":"agent","agent":"AGENT_NAME"}`. Do not include the secret.
6. Note any non-secret follow-up in the agent's memory via the **memory** tool / `MEMORY.md` or `memory/<day>.md` — provider, account label, and what to re-check, never the value itself.

## Notes

- Reconfiguration is always **manage_agent**, never a file edit, shell command, or process restart.
- If a step has no Elevate mechanism (writing a host file, restarting a runtime, touching infrastructure), say so plainly and raise a [HUMAN] task. Do not invent commands.
- Recurring health checks for a credential -> schedule them with **cron**. Isolated verification work that should run in parallel without touching this agent's state -> **delegate_task** to a worker-agent.
- To see what tools an agent currently has for a given provider, use **/tools**.

## Output

Return a short status with:

- Provider or connector name and account label.
- Whether the credential is healthy, expired, missing, or waiting on human action.
- Non-secret next step.
- The approval id or agent_handoff id when one was created.
