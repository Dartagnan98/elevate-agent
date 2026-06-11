---
name: env-management
description: "You need to add a new API key to the system, update an existing credential, check what secrets are configured for the org or a specific agent, onboard a new third-party tool that needs credentials, diagnose why an agent cannot access a service because a key appears missing, rotate a compromised or expired key, or reconfigure affected agents after a credential change. This skill covers the full lifecycle of environment variables and secrets in Elevate."
triggers: ["add key", "api key", "env file", ".env", "secret", "credential", "token", "environment variable", "configure key", "set key", "missing key", "key not set", "where do I put", "shared secret", "org secret", "agent secret", "key not loading", "configure credentials", "new api key", "add to env", "rotate key", "rotate token", "key compromised", "token expired", "update api key", "new bot token", "revoke key", "credential rotation", "key rotation", "secret rotation", "key was leaked", "compromised credential", "force rotation", "provider rotated", "expired key", "rotate credentials", "update secret"]
category: agent-ops
---

# Environment Variable Management

Elevate keeps secrets out of agent reach by design. Agents do not edit credential files directly — credential storage and agent configuration are managed through Elevate tools and surfaces. An agent's job here is to identify what key is needed, where it should live, and then reconfigure the affected agent(s) through `manage_agent` so the new credential is picked up. Anything that requires writing to a host file or a system shell has no agent mechanism and must be raised as a [HUMAN] task.

---

## Where Each Key Lives

| Key type | Scope | Example |
|----------|-------|---------|
| Shared API keys (multiple agents use) | Org-level secret store | `OPENAI_API_KEY`, `APIFY_TOKEN`, `GEMINI_API_KEY` |
| Agent-specific service credentials | Agent-level secret store | service tokens used by only one agent |
| Agent OAuth tokens | Agent-level secret store | `CLAUDE_CODE_OAUTH_TOKEN` |

**Rule:** If more than one agent uses a key, it belongs in the org-level secret store. If only one agent uses it, it belongs in that agent's own secret store.

`ANTHROPIC_API_KEY` is provided by the host environment that runs Elevate — it is never stored in an agent or org secret store, and agents cannot change it.

---

## Adding a New Shared Secret

1. Confirm the key is genuinely shared (used by more than one agent). If not, scope it to the single agent instead (next section).
2. Adding a secret to the org-level secret store is a privileged action that writes to host credential storage. Agents have **no Elevate tool to write the org secret store directly**. Raise a **[HUMAN]** task describing the exact key name, scope (org), and which agents need it.
3. Once the human confirms the secret is stored, reconfigure every agent that uses it with the **manage_agent** tool so the credential is loaded into their toolset/runtime config. Never edit any file by hand.

---

## Adding an Agent-Specific Secret

1. Confirm only one agent uses the key.
2. Writing to an agent's secret store is privileged and writes to host credential storage. Agents have **no Elevate tool to write the agent secret store directly**. Raise a **[HUMAN]** task with the exact key name, scope (agent), and the agent name.
3. After the human confirms it is stored, use the **manage_agent** tool to reconfigure THAT agent so it picks up the new credential.

---

## Checking What Keys Are Configured

To see what an agent or the org has configured, inspect the agent's configuration through the **manage_agent** tool (read/inspect mode) rather than reading any file.

To verify a key is available in the current session, check the environment variable name only — never print the value:

```bash
[[ -n "${SOME_KEY:-}" ]] && echo "SET" || echo "NOT SET"
```

If a value is missing where you expect it, that is a configuration/reconfigure issue — raise a [HUMAN] task to confirm the secret is stored, then reconfigure the agent via **manage_agent**.

---

## Rotating a Secret

Updating a key's stored value does nothing for a running agent until that agent is reconfigured — the old value stays loaded in the agent's runtime until **manage_agent** reapplies its configuration.

### Rotation Decision Tree

```
Is this a shared org-level key (OPENAI_API_KEY, APIFY_TOKEN, etc.)?
  → Raise a [HUMAN] task to update the org secret store value
  → Then reconfigure ALL affected agents via manage_agent

Is this an agent-specific key (a service token, OAuth token)?
  → Raise a [HUMAN] task to update that agent's secret store value
  → Then reconfigure THAT AGENT ONLY via manage_agent

Is this ANTHROPIC_API_KEY?
  → Host-environment only. Agents have no mechanism to change it.
  → Raise a [HUMAN] task. Do NOT store it in any agent/org secret store.
```

### Rotating a Shared Org Secret

1. Raise a **[HUMAN]** task to update the value of `KEY_NAME` in the org secret store (agents cannot write it).
2. After confirmation, reconfigure every affected agent with the **manage_agent** tool so each one reloads the new value.
3. Log the rotation: use the **agent_bus** tool (action `log_event`) with action `secret_rotated`, level `info`, and metadata `{"key":"KEY_NAME","scope":"org"}`.

### Rotating an Agent-Specific Secret

1. Raise a **[HUMAN]** task to update the value of `KEY_NAME` in that agent's secret store.
2. After confirmation, reconfigure that agent with the **manage_agent** tool so it reloads the value.
3. Log the rotation: use the **agent_bus** tool (action `log_event`) with action `secret_rotated`, level `info`, and metadata `{"key":"KEY_NAME","scope":"agent","agent":"AGENT_NAME"}`.

### Rotating a Bot Token

1. Revoke the old token with the provider (e.g. for a Telegram bot: @BotFather → `/mybots` → select the bot → `API Token` → `Revoke current token`).
2. Copy the new token.
3. Raise a **[HUMAN]** task to update the agent's secret store with the new token value (the old token is already invalid).
4. After confirmation, reconfigure that agent with the **manage_agent** tool immediately.

---

## Critical Rules

1. **Never print secret values** — log key names only, never values.
2. **Agents never write credential stores directly** — secret writes are privileged; raise a [HUMAN] task for the actual store update.
3. **Never reconfigure an agent expecting it to load a value that isn't stored yet** — confirm the secret is stored first, then reconfigure via **manage_agent**.
4. **Always reconfigure via manage_agent after a credential change** — a credential change without reconfiguring leaves the old value loaded in the agent's runtime.
5. **Each agent that needs its own bot must have its own bot token** — never share one bot token across agents at org scope.
6. **ANTHROPIC_API_KEY is host-only** — agents cannot change it; raise a [HUMAN] task.
7. **Log every rotation** via the **agent_bus** tool (action `log_event`) with action `secret_rotated`.
