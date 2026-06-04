# Persistent agent sessions (bringing the daemon model in, the native way)

> Decision (2026-06-04): agents should run as **persistent, resident sessions** with warm
> context — not one-shot `run_agent` per cron. This is the cortextOS agent-manager model,
> but built on Elevate's existing session machinery instead of a from-scratch daemon.

## The key fact: the persistent-session stack already exists

Elevate already runs resident, resumable sessions — it just points them at interactive chat,
not agents:

- `tui_gateway/slash_worker.py` — a persistent `ElevateCLI(resume=<session_key>)` subprocess.
  Holds **warm context** across turns. Protocol: stdin `{id, command}` → stdout `{id, ok, output|error}`.
- `tui_gateway/server.py`:
  - `_sessions: dict[str,dict]` — the session registry.
  - `_SlashWorker` (line 233) — wraps the subprocess (`subprocess.Popen`), drains stdout/stderr,
    `.run(command)` sends a turn and waits for the matching `id`.
  - `_restart_slash_worker` (751) + `.proc.poll()` — **liveness + auto-restart already done.**
  - `FanoutTransport` (206) — push emits into gateway-spawned sessions (cron/daemon side).
- `ElevateCLI.chat(message, images)` (cli.py:8432) — the **free-form agent-turn** entry point
  (the slash worker only calls `process_command`, i.e. `/commands`; agents need `.chat`).

So we are NOT building a daemon. We extend the existing resident-session model to agents.

## Process model: cortextOS vs Elevate (what maps to what)

| cortextOS (daemon of CLIs) | Elevate (native, this build) |
|---|---|
| Persistent PTY per agent (`agent-pty.ts`) | Persistent `ElevateCLI(resume="agent:<id>")` subprocess |
| PM2 daemon supervises | The gateway supervises (reuse `_SlashWorker` + `_restart`) |
| Bus `send-message` / IPC wake | Route a turn into the resident session via `.chat` |
| Heartbeat = agent's internal loop | Heartbeat cron routes its prompt INTO the resident session |
| Liveness file + force-restart-on-hang | `.proc.poll()` + restart (already exists) |
| Agent always polling | **Resident but idle** — process alive (warm context), only a turn costs tokens |

**Idle ≠ burning tokens.** A resident session is a live process holding context; tokens are
only spent when a turn runs. That kills the main cost objection and removes the file-reload
churn of one-shot runs — the agent *remembers* across heartbeats/handoffs.

## Build plan (flag-gated, non-breaking)

**1. Persistent agent worker — `tui_gateway/agent_worker.py`** ✅ (this commit)
A near-clone of `slash_worker.py` that runs `ElevateCLI(resume="agent:<id>")` and processes
free-form turns with `cli.chat(message)`. Protocol: stdin `{id, message}` → stdout
`{id, ok, output|error}`. Self-contained; nothing routes to it yet.

**2. Agent session supervisor — `cron/agent_sessions.py`** (next)
- `ensure_session(agent_id, model)` → resident worker (reuse `_SlashWorker`, keyed `agent:<id>`).
- `send_turn(agent_id, prompt) -> str` → `.run(prompt)` against the resident session.
- `reap()` / liveness → restart dead sessions (reuse `_restart_slash_worker`).
- A registry parallel to `_sessions`, owned by the gateway.

**3. Route work INTO sessions (behind `ELEVATE_PERSISTENT_AGENTS`)** (the switch)
In `cron/scheduler.py`, when a job's `origin.type ∈ {surface-heartbeat, surface-automation}`
fires AND the flag is on AND the agent has a resident session: send the prompt as a turn
(`agent_sessions.send_turn`) instead of spawning one-shot `run_agent`. Flag off → today's
one-shot path, unchanged. So we roll it per-agent and fall back safely.

**4. Event wake (real-time)** (the payoff)
Inbound events (new message/lead via Composio/source-connectors), handoffs, and dispatched
tasks wake the target agent's resident session immediately (route a turn), instead of waiting
for the next 60s tick. This is the real-time behavior persistent sessions buy.

**5. Lifecycle policy**
- Which agents get a resident session: only **enabled** Agent Hub agents (opt-in per agent via
  a `persistent: true` flag in the agent/surface config). Disabled → no process.
- Day/night: at night, keep the session resident but quiet (no proactive turns) — reuse
  `is_day_mode`. Or tear down at night to save RAM; resume in the morning (cheap — context is
  in `resume`).
- Cap: a max-resident-sessions guard so a many-agent fleet can't exhaust RAM.

## Risks / honest trade-offs

- **RAM**: each resident session is a Python+model-client process. Cap it; opt-in per agent.
- **Hung sessions**: the thing cortextOS fights hardest. Mitigated — liveness + restart already
  exist (`_restart_slash_worker`, `.proc.poll()`); a turn timeout (`_SLASH_WORKER_TIMEOUT_S`)
  already bounds a stuck turn.
- **Context drift**: a long-lived `resume` session accumulates context → compaction. ElevateCLI
  already has compaction; verify it triggers in headless resident mode.
- **Multi-account desktop ship**: this changes how agents execute for everyone. Ship behind the
  flag OFF by default; enable per-agent from the UI once burned in.

## Integration points (reference)
- `tui_gateway/server.py:233 _SlashWorker`, `:120 _sessions`, `:751 _restart_slash_worker`, `:206 FanoutTransport`.
- `tui_gateway/slash_worker.py` (the template to clone).
- `cli.py:8432 ElevateCLI.chat`.
- `cron/scheduler.py` — the dispatch path that currently spawns one-shot `run_agent` (the switch point).
- `cron/jobs.py` — `origin.type` on heartbeat/automation jobs (how to know a job targets an agent).
