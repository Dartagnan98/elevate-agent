# Langfuse Observability Plugin

This plugin ships bundled with Hermes but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

```bash
pip install langfuse
hermes plugins enable observability/langfuse
```

Or check the box in the interactive `hermes plugins` UI.

## Required credentials

Set these in `~/.elevate/.env`:

```bash
ELEVATE_LANGFUSE_PUBLIC_KEY=pk-lf-...
ELEVATE_LANGFUSE_SECRET_KEY=sk-lf-...
ELEVATE_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
hermes plugins list                 # observability/langfuse should show "enabled"
hermes chat -q "hello"              # then check Langfuse for a "Hermes turn" trace
```

## Optional tuning

```bash
ELEVATE_LANGFUSE_ENV=production       # environment tag
ELEVATE_LANGFUSE_RELEASE=v1.0.0       # release tag
ELEVATE_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ELEVATE_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ELEVATE_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
hermes plugins disable observability/langfuse
```
