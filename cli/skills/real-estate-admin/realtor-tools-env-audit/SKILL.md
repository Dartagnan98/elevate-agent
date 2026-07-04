---
name: realtor-tools-env-audit
description: Audit and safely update the realtor tools .env without exposing secrets. Use when skills fail because env vars are missing, when adding aliases for AOIR/MLS/Buffer/Drive/Mailjet, or when the user asks what credentials/env pieces are missing.
---

# Realtor Tools .env Audit + Safe Update

Use this when the user asks what is missing in the realtor's tools `.env` file, asks to make the skills work, or reports that AOIR/Matrix/Buffer/Mailjet/Drive-related scripts cannot find credentials.

## Safety rules

1. Never print secret values. Report only key names, whether set, and value length.
2. Back up the tools `.env` file before editing.
3. Do not copy Claude/Elevate channel credentials into the tools `.env` unless the user explicitly asks for that local app stack.
   - Specifically leave out/remove: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TG_BOT_TOKEN`, `TG_CHAT_ID`.
   - These are for Claude/Elevate itself, not the realtor's tools project, unless the user says otherwise.
4. Prefer aliases over duplicating workflows: if a script expects AOIR but MLS creds are the actual AOIR login, create AOIR aliases from the existing MLS keys.
5. Do not overwrite non-empty values unless the user requested the correction or the value is a deterministic alias from an existing key.

## Current known mappings

Read the realtor's onboarding/config record for the actual values before assuming any of these — they vary per box. Common patterns observed across boxes:

- AOIR is often the realtor's MLS/Xposure login.
  - `AOIR_USER` should mirror `MLS_USERNAME`.
  - `AOIR_PASS` should mirror `MLS_PASSWORD`.
- Listing Drive parent folder:
  - `LISTING_DRIVE_PARENT=<drive-folder-id>` for the Google Drive folder holding the realtor's listing files. Verify the folder id by querying Drive rather than trusting a stale value (see Audit procedure below).
- Buffer legacy aliases used by older marketing scripts:
  - `BUFFER_ACCESS_TOKEN` can mirror `BUFFER_TOKEN`.
  - `BUFFER_PROFILE_IG=<buffer-profile-id>` for the brand's Instagram channel.
  - `BUFFER_PROFILE_FB=<buffer-profile-id>` for the brand's Facebook channel.
- Mailjet sender defaults:
  - `MAILJET_FROM=<realtor's sending address>`
  - `MAILJET_FROM_NAME=<realtor's display name>`
- Optional/manual tokens often left blank:
  - `CLOUDFLARE_API_TOKEN` unlocks autonomous DNS/Mailjet deliverability fixes.
  - `MAILERLITE_TOKEN` only matters if MailerLite campaign automation is used.
  - `RESEND_API_KEY` is optional alternate notification email provider.
  - `GOOGLE_API_KEY` is optional Google AI helper key.

## Audit procedure

1. Read `.env` with a masked parser, not `cat`, and report only set/length:

```python
from pathlib import Path
import json
p = Path('<realtor-tools-dir>/.env')
keys = []
for line in p.read_text(errors='ignore').splitlines():
    s = line.strip()
    if not s or s.startswith('#') or '=' not in s:
        continue
    k, v = s.split('=', 1)
    vv = v.strip().strip('"').strip("'")
    keys.append({'key': k.strip(), 'set': bool(vv), 'len': len(vv)})
print(json.dumps({'env_exists': p.exists(), 'key_count': len(keys), 'keys': keys}, indent=2))
```

2. Search for referenced env vars in active scripts/docs, but filter noisy false positives from `node_modules`, `.claude/worktrees`, session transcripts, runtime-only variables, and local shell variables. Use this to find integration keys, not to blindly add every uppercase string.

3. If a Drive parent folder id is needed, verify by querying Google Drive rather than guessing:

```bash
gws drive files list --params '{"q":"name = '\''<realtor listing folder name>'\'' and mimeType='\''application/vnd.google-apps.folder'\'' and trashed=false","fields":"files(id,name,webViewLink)","pageSize":10}'
```

If the quoting is awkward, search for folders containing the realtor's name/brand and pick the verified listing folder.

## Update procedure

1. Create a timestamped backup:

```python
from pathlib import Path
import shutil, time
p = Path('<realtor-tools-dir>/.env')
backup = p.with_name(f'.env.backup-before-env-update-{int(time.time())}')
shutil.copy2(p, backup)
print(backup)
```

2. Add/update only deterministic aliases/defaults:

- `AOIR_USER` from `MLS_USERNAME`
- `AOIR_PASS` from `MLS_PASSWORD`
- `BUFFER_ACCESS_TOKEN` from `BUFFER_TOKEN`
- `BUFFER_PROFILE_IG` / `BUFFER_PROFILE_FB` from known Buffer channel IDs
- `LISTING_DRIVE_PARENT` from verified Drive folder ID
- `MAILJET_FROM` / `MAILJET_FROM_NAME` defaults
- blank placeholders for optional/manual keys (`CLOUDFLARE_API_TOKEN`, `MAILERLITE_TOKEN`) only if useful for future checks

3. Ensure Telegram Claude/channel tokens are absent from the tools `.env` unless the user explicitly requested that local bot stack.

## Verification procedure

After editing, parse the file again and report:

- Which keys were added/changed/removed.
- Which expected keys are now set, by key name + length only.
- Which optional/manual keys remain blank.
- Backup path.

Example final summary:

- `AOIR_USER` / `AOIR_PASS` now resolve from MLS credentials.
- Drive, Buffer, and Mailjet aliases are present.
- Telegram Claude tokens were not added to the realtor's tools env.
- Remaining manual tokens: `CLOUDFLARE_API_TOKEN`, `MAILERLITE_TOKEN` if still blank.

## MCP setup for Buffer + Mailjet

Use this when the user asks to “make Buffer/Mailjet into an MCP”, add them to MCPs, or make future sessions expose native `mcp_buffer_*` / `mcp_mailjet_*` tools.

Known paths (adjust to the actual box's home directory and tools project location):

- Elevate config: `~/.elevate/config.yaml`
- Buffer MCP server: `~/.elevate/mcp_servers/buffer_mcp.py`
- Mailjet MCP server: `<realtor-tools-dir>/mcp-servers/mailjet/server.js`
- Buffer token source: `<realtor-tools-dir>/.env` key `BUFFER_TOKEN`
- Mailjet secret source: `<realtor-tools-dir>/.env` keys `MAILJET_API_KEY` + `MAILJET_SECRET_KEY`

Config shape in `~/.elevate/config.yaml`:

```yaml
mcp_servers:
  buffer:
    command: ~/.local/bin/uv
    args:
      - run
      - --with
      - mcp
      - --with
      - pydantic
      - python
      - ~/.elevate/mcp_servers/buffer_mcp.py
    timeout: 120
    connect_timeout: 60
    sampling:
      enabled: false
  mailjet:
    command: node
    args:
      - <realtor-tools-dir>/mcp-servers/mailjet/server.js
    timeout: 120
    connect_timeout: 60
    sampling:
      enabled: false
```

Rules:

1. Back up `~/.elevate/config.yaml` before editing.
2. Do not paste API keys into `config.yaml`; both MCP servers load secrets from `<realtor-tools-dir>/.env`.
3. Buffer should run through `uv` with `--with mcp --with pydantic`; direct system Python may not have the `mcp` package.
4. Mailjet runs directly with `node` because its package dependencies are already installed under `<realtor-tools-dir>/mcp-servers/mailjet`.
5. After adding servers, verify with an MCP stdio client before reporting done:

```bash
~/.local/bin/uv run --with mcp --with pydantic python - <<'PY'
import asyncio, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def list_tools(command, args):
    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [t.name for t in tools.tools]

async def main():
    results = {}
    results['buffer'] = await list_tools('~/.local/bin/uv', ['run','--with','mcp','--with','pydantic','python','~/.elevate/mcp_servers/buffer_mcp.py'])
    results['mailjet'] = await list_tools('node', ['<realtor-tools-dir>/mcp-servers/mailjet/server.js'])
    print(json.dumps({k: {'count': len(v), 'tools': v} for k, v in results.items()}, indent=2))

asyncio.run(main())
PY
```

Expected discovery counts as of the last successful setup on one box:

- Buffer: 6 tools (`get_account`, `list_channels`, `get_post`, `create_post`, `create_forever_post`, `edit_post`)
- Mailjet: 20 tools including `send_email`, sender/list/contact tools, campaign draft/content/schedule/test/send tools, stats, and `mailjet_request`.

Tell the user they may need to restart Elevate for newly configured MCP tools to appear natively in future chats.
