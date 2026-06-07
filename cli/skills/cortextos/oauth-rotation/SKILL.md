---
name: oauth-rotation
category: cortextos
description: "Rotate, refresh, or repair OAuth/provider credentials using Elevate settings and connector state without exposing secrets."
triggers: ["oauth", "token rotation", "refresh token", "expired token", "connector auth", "reauthorize", "api key rotation", "credential rotation"]
---

# OAuth Rotation

> Elevate compatibility: CortextOS references `oauth-rotation`, but the current upstream checkout does not ship a matching skill folder. This Elevate compatibility skill maps that intent to the native Settings, Env, OAuth providers, connector config, Approvals, Activity, and Comms surfaces.

Use this skill when an agent needs to rotate or repair OAuth credentials, API keys, refresh tokens, app passwords, webhook secrets, or provider-specific connector authorization.

## Rules

1. Never print, summarize, or return raw secrets.
2. Never write credentials into prompts, tasks, handoffs, Activity, Comms, or memory.
3. Prefer the Elevate Settings/OAuth provider flow or connector reauth flow over manual environment edits.
4. If credential rotation affects external delivery, billing, deployment, legal, or user-facing communication, create an approval or waiting-human item first.
5. After rotation, record only non-secret metadata: provider, account label, agent id, result, timestamp, and follow-up needed.

## Elevate Mapping

- CortextOS daemon credential reload -> Elevate app config reload or connector reauth.
- CortextOS `.env` token edits -> Elevate Env/Settings provider config.
- CortextOS bus activity log -> Elevate Activity event.
- CortextOS human approval -> Elevate Approvals or `waiting_human` handoff.
- CortextOS Telegram token repair -> Agent Hub channel config with fallback to orchestrator/executive-assistant bot when no per-agent token exists.

## Output

Return a short status with:

- Provider or connector name.
- Whether the credential is healthy, expired, missing, or waiting on human action.
- Non-secret next step.
- Approval or handoff id when one was created.
