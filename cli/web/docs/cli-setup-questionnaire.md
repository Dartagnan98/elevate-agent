# CLI Setup Questionnaire

Snapshot of every prompt asked by `elevate setup` top-level functions in `cli/elevate_cli/setup.py`. Sub-flows that delegate into `cli/elevate_cli/gateway.py` are inlined here.

Format: `- prompt text → ENV_KEY` or `→ config.key.path` (config = config.yaml).

`SETUP_SECTIONS` registers: `setup_model_provider`, `setup_terminal_backend`, `setup_agent_settings`, `setup_memory`, `setup_admin`, `setup_gateway`, `setup_tools`. `setup_tts` is also exposed as a standalone section.

---

## Section: setup_model_provider (line 686)

Header: "Inference Provider". Delegates almost everything to `select_provider_and_model()` (the `elevate model` flow) for provider picker, credential prompting, model selection.

After the delegate returns, branches based on whether the selected provider supports same-provider pooling and whether vision is configured.

- (loop) "Add another credential for same-provider fallback?" yes/no → triggers `auth_add_command` for selected provider (creates new pool entry)
- "Select same-provider rotation strategy:" choice [fill-first / round-robin / random] → `config.credential_pool_strategies[<provider>]` ∈ {`fill_first`, `round_robin`, `random`}

Vision sub-flow (only fires when `not quick` and no vision backend is auto-detected for the active provider):

- "Configure vision:" choice [OpenRouter / OpenAI-compatible endpoint / Skip for now]
  - OpenRouter branch:
    - "  OpenRouter API key" (password) → `OPENROUTER_API_KEY`
  - OpenAI-compatible branch:
    - "  Base URL (blank for OpenAI)" → `config.auxiliary.vision.base_url` (defaults `https://api.openai.com/v1`)
    - "  API key" or "  OpenAI API key" (password) → `OPENAI_API_KEY`
    - If native OpenAI host: "Select vision model:" choice [gpt-4o / gpt-4o-mini / gpt-4.1 / gpt-4.1-mini / gpt-4.1-nano / default] → `AUXILIARY_VISION_MODEL`
    - Else: "  Vision model (blank = use main/custom default)" → `AUXILIARY_VISION_MODEL`

Then, if `not quick` and the selected provider != `nous`, falls through to `_setup_tts_provider(config)` (see TTS section below).

---

## Section: setup_tts (line 1184)

Standalone wrapper for `_setup_tts_provider`. Header: "Text-to-Speech Provider (optional)".

- "Select TTS provider:" choice [Elevate Subscription managed OpenAI TTS (if nous-managed) / Edge TTS / ElevenLabs / OpenAI TTS / xAI / MiniMax / Mistral Voxtral / Google Gemini / NeuTTS / KittenTTS / Keep current] → `config.tts.provider`
  - NeuTTS: "Install espeak-ng now?" yes/no, "Install NeuTTS dependencies now?" yes/no
  - ElevenLabs: "ElevenLabs API key" (password) → `ELEVENLABS_API_KEY`
  - OpenAI (direct): "OpenAI API key for TTS" (password) → `VOICE_TOOLS_OPENAI_KEY`
  - xAI: "xAI API key for TTS" (password) → `XAI_API_KEY`
  - MiniMax: "MiniMax API key for TTS" (password) → `MINIMAX_API_KEY`
  - Mistral: "Mistral API key for TTS" (password) → `MISTRAL_API_KEY`
  - Gemini: "Gemini API key for TTS" (password) → `GEMINI_API_KEY`
  - KittenTTS: "Install KittenTTS now?" yes/no

Any failed/blank API key path falls back to `selected = "edge"`.

---

## Section: setup_terminal_backend (line 1194)

Header: "Terminal Backend".

- "Select terminal backend:" choice [Local / Docker / Modal / SSH / Daytona / Singularity-Apptainer (Linux only) / Keep current] → `config.terminal.backend` and `TERMINAL_ENV`

Branches by selection:

**local:**
- "  Messaging working directory" → `config.terminal.cwd`
- "Enable sudo support? (stores password for apt install, etc.)" yes/no
  - "  Sudo password" (password) → `SUDO_PASSWORD`

**docker:**
- "  Docker image" → `config.terminal.docker_image` + `TERMINAL_DOCKER_IMAGE`
- then `_prompt_container_resources(config)` (CPU/mem/etc.)

**singularity:**
- "  Container image" → `config.terminal.singularity_image` + `TERMINAL_SINGULARITY_IMAGE`
- then `_prompt_container_resources(config)`

**modal:**
- (if managed gateway available) "Select how Modal execution should be billed:" choice [Use my Elevate subscription / Use my own Modal account] → `config.terminal.modal_mode` ∈ {`managed`, `direct`} + `TERMINAL_MODAL_MODE`
- "  Update Modal credentials?" yes/no (only when token already set)
- "    Modal Token ID" (password) → `MODAL_TOKEN_ID`
- "    Modal Token Secret" (password) → `MODAL_TOKEN_SECRET`
- then `_prompt_container_resources(config)`

**daytona:**
- "  Update API key?" yes/no (when key exists), else direct prompt
- "    Daytona API key" (password) → `DAYTONA_API_KEY`
- "  Sandbox image" → `config.terminal.daytona_image` + `TERMINAL_DAYTONA_IMAGE`
- then `_prompt_container_resources(config)`

**ssh:**
- "  SSH host (hostname or IP)" → `TERMINAL_SSH_HOST`
- "  SSH user" → `TERMINAL_SSH_USER`
- "  SSH port" → `TERMINAL_SSH_PORT` (only saved if non-22)
- "  SSH private key path" → `TERMINAL_SSH_KEY`
- "  Test SSH connection?" yes/no

---

## Section: setup_agent_settings (line 1560)

Header: "Agent Settings".

- "Max iterations" → `config.agent.max_turns` + `ELEVATE_MAX_ITERATIONS`
- "Tool progress mode" (off / new / all / verbose) → `config.display.tool_progress`
- "Compression threshold (0.5-0.95)" → `config.compression.threshold` (and sets `config.compression.enabled = True`)
- "Session reset mode:" choice [Inactivity + daily / Inactivity only / Daily only / Never auto-reset / Keep current] → `config.session_reset.mode` ∈ {`both`, `idle`, `daily`, `none`}
  - For `both` / `idle`: "  Inactivity timeout (minutes)" → `config.session_reset.idle_minutes`
  - For `both` / `daily`: "  Daily reset hour (0-23, local time)" → `config.session_reset.at_hour`

`_apply_default_agent_settings` (no prompts) writes the same keys with defaults: max_turns=90, tool_progress=all, compression.threshold=0.50, session_reset.mode=both, idle_minutes=1440, at_hour=4.

---

## Section: setup_memory (line 1826)

Header: "Memory & Embeddings". Always sets `config.memory.memory_enabled = True` and `config.memory.user_profile_enabled = True`.

- (only if non-holographic provider already set) "Switch to Elevate local memory store?" yes/no → if no, `config.memory.setup_completed = True` and return
- "Enable Elevate local memory graph?" yes/no
  - No → `config.memory.provider = ""` and return
  - Yes → `config.memory.provider = "holographic"` and toggles on turn_journal_enabled, organize_on_session_end, daily_organize_enabled, layered_prefetch_enabled, recent_recall_enabled, graph_recall_enabled in `config.plugins.elevate-memory-store`
- "Enable semantic memory embeddings? (recommended)" yes/no
  - "Embedding backend:" choice [OpenAI API key / Ollama/local / Skip]
    - OpenAI:
      - `embedding_provider = "openai"`, `embedding_model = "text-embedding-3-small"`, `embedding_api_key_env = "OPENAI_API_KEY"`
      - If key already set: "Update the OpenAI API key?" yes/no → "OpenAI API key" (password) → `OPENAI_API_KEY`
      - Else: "OpenAI API key" (password) → `OPENAI_API_KEY`
    - Ollama:
      - "Ollama embedding model" → `config.plugins.elevate-memory-store.embedding_model`
      - "Ollama base URL" → `config.plugins.elevate-memory-store.embedding_base_url`

Final write: `config.memory.setup_completed = True`, then initializes the SQLite store file.

---

## Section: setup_admin (line 2036)

Header: "Realtor Admin Setup". Persists to SQLite via `update_admin_setup`, not config.yaml.

- "Primary province for admin docs and deal workflows:" choice (PROVINCE_LABELS) → `profile.province`
- (skipped when `quick=True`) "How much admin setup do you want to do now?" choice [Fast setup / Full setup] → `full_setup` flag

Realtor Profile block:
- "Licensed / legal realtor name" → `profile.realtorLegalName`
- "Public license name" → `profile.licenseName`
- "Brokerage name" → `profile.brokerageName`
- "Team / PREC name (optional)" → `profile.teamName`
- "Primary market / service area" → `profile.market`
- "Board memberships (comma-separated, optional)" → `profile.boardMemberships[]`

Core Providers block (loops 10 keys, each `prompt(label, default)`):
- "Email provider" → `profile.emailProvider`
- "Calendar provider" → `profile.calendarProvider`
- "Document storage" → `profile.driveProvider`
- "CRM / lead source" → `profile.crmProvider`
- "MLS provider" → `profile.mlsProvider`
- "Forms provider" → `profile.formsProvider`
- "Signing provider" → `profile.signingProvider`
- "Compliance platform" → `profile.complianceProvider`
- "Showing feedback platform" → `profile.showingProvider`
- "FINTRAC / ID workflow" → `profile.fintracProvider`

Approval Lane block:
- "Where should Admin ask for approvals?" → `profile.approvalChannel`
- "Approval policy note" → `profile.approvalPolicy.notes`

Browser Portal Playbooks block (only when `full_setup`); loops 3 portals (mls / compliance / showing):
- "  Provider" → `items.browser_workflows.value.playbooks[<key>].provider`
- "  Login URL" → `…loginUrl`
- "  Credential reference (not the password)" → `…credentialRef`
- "  Browser-use notes" → `…notes`
- "Shared browser-use notes" → `items.browser_workflows.value.notes`

Photo Workflow block:
- "Photo cleanup workflow" → `items.photo_processing.value.provider`
- "Photo source folder/provider" → `items.photo_processing.value.source`
- "Photo workflow notes" → `items.photo_processing.value.notes`

Regional Memory block:
- "Local/regional notes for Admin memory" → `profile.regionalMemory.notes`

---

## Section: setup_gateway (line 2941)

Header: "Messaging Platforms".

- `prompt_checklist` "Select platforms to configure:" — pre-selects already-configured platforms, multi-select against `_GATEWAY_PLATFORMS` registry (17 platforms).

Then iterates `_setup_<platform>()` for each selected. Tail prompts (only if any platform was configured):

- "  Restart the gateway to pick up changes?" yes/no (when service running)
- "  Start the gateway service?" yes/no (when installed but not running)
- "  Install the gateway as a {systemd|launchd} service?" yes/no (when supported and not installed)
- "  Start the service now?" yes/no

### Sub-flow: _setup_telegram (line 2406)

Header: "Telegram".

- (if existing token) "Reconfigure Telegram?" yes/no
  - If keeping existing and no allowlist: "Add allowed users now?" yes/no → "Allowed user IDs (comma-separated)" → `TELEGRAM_ALLOWED_USERS`. If still blank, calls `_configure_telegram_access_without_allowlist`.
- "Telegram bot token" (password, regex `^\d+:[A-Za-z0-9_-]{30,}$`, loops until valid) → `TELEGRAM_BOT_TOKEN`. Instructions: "Create a bot via @BotFather on Telegram"
- "Allowed user IDs (comma-separated, leave empty for DM pairing)" → `TELEGRAM_ALLOWED_USERS` (+ sets `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR=ignore`). Instructions: "To find your Telegram user ID: 1. Message @userinfobot 2. It will reply with your numeric ID".
- If blank, `_configure_telegram_access_without_allowlist` (line 2383):
  - "How should Telegram authorize users?" choice [DM pairing / Open access / Deny unknown]
    - pair → `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR=pair` and prints pairing next steps ("elevate gateway start", "send /start", "elevate pairing approve telegram <code>", "/set-home")
    - open → `GATEWAY_ALLOW_ALL_USERS=true`, `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR=ignore`
    - deny → `TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR=ignore`
- If first allowed user exists: "Use your user ID ({first_user_id}) as the home channel?" yes/no → `TELEGRAM_HOME_CHANNEL`
- Else: "Home channel ID (...)" → `TELEGRAM_HOME_CHANNEL`

### Sub-flow: _setup_discord (line 2484)

Header: "Discord".

- (existing) "Reconfigure Discord?" yes/no; "Add allowed users now?" yes/no → "Allowed user IDs (comma-separated)" → `DISCORD_ALLOWED_USERS` (cleaned)
- "Discord bot token" (password) → `DISCORD_BOT_TOKEN`. Instructions: "Create a bot at https://discord.com/developers/applications".
- "Allowed user IDs or usernames (comma-separated, leave empty for open access)" → `DISCORD_ALLOWED_USERS`
- "Home channel ID (leave empty to set later with /set-home)" → `DISCORD_HOME_CHANNEL`

### Sub-flow: _setup_slack (line 2552)

Header: "Slack".

- (existing) "Reconfigure Slack?" yes/no
- Instructions: Slack app create + scopes + events list.
- "Slack Bot Token (xoxb-...)" (password) → `SLACK_BOT_TOKEN`
- "Slack App Token (xapp-...)" (password) → `SLACK_APP_TOKEN`
- "Allowed user IDs (comma-separated, leave empty to deny everyone except paired users)" → `SLACK_ALLOWED_USERS`

### Sub-flow: _setup_matrix (line 2605)

Header: "Matrix".

- (existing) "Reconfigure Matrix?" yes/no
- "Homeserver URL (e.g. https://matrix.example.org)" → `MATRIX_HOMESERVER`
- "Access token (leave empty for password login)" (password) → `MATRIX_ACCESS_TOKEN`
  - "User ID (@bot:server — optional, will be auto-detected)" → `MATRIX_USER_ID`
- (if no token) "User ID (@bot:server)" → `MATRIX_USER_ID`; "Password" (password) → `MATRIX_PASSWORD`
- "Enable end-to-end encryption (E2EE)?" yes/no → `MATRIX_ENCRYPTION=true`. Triggers `pip install mautrix[encryption]`/`mautrix`.
- "Allowed user IDs (comma-separated, leave empty for open access)" → `MATRIX_ALLOWED_USERS`
- "Home room ID (leave empty to set later with /set-home)" → `MATRIX_HOME_ROOM`

### Sub-flow: _setup_mattermost (line 2691)

Header: "Mattermost".

- (existing) "Reconfigure Mattermost?" yes/no
- "Mattermost server URL (e.g. https://mm.example.com)" → `MATTERMOST_URL`
- "Bot token" (password) → `MATTERMOST_TOKEN`
- "Allowed user IDs (comma-separated, leave empty for open access)" → `MATTERMOST_ALLOWED_USERS`
- "Home channel ID (leave empty to set later with /set-home)" → `MATTERMOST_HOME_CHANNEL`

### Sub-flow: _setup_whatsapp (line 2734)

Header: "WhatsApp".

- (existing `WHATSAPP_ENABLED`) returns early.
- "Enable WhatsApp now?" yes/no → `WHATSAPP_ENABLED=true`. Instructions to run `elevate whatsapp` for QR pairing.

### Sub-flow: _setup_signal (gateway.py line 3714)

Header: "Signal".

- (existing url + account) "Reconfigure Signal?" yes/no
- Detects `signal-cli` on PATH; prints install + link instructions.
- "HTTP URL [default `http://127.0.0.1:8080`]" → `SIGNAL_HTTP_URL`. Performs `/api/v1/check`.
  - On non-200 / connection fail: "Continue anyway?" / "Save this URL anyway?" yes/no
- "Account number" (E.164) → `SIGNAL_ACCOUNT`
- "Allowed users" (default = existing or self account) → `SIGNAL_ALLOWED_USERS`
- "Enable group messaging?" yes/no
  - "Group IDs" (default `*`) → `SIGNAL_GROUP_ALLOWED_USERS`

### Sub-flow: _setup_email (gateway.py line 3066)

Delegates to `_setup_standard_platform({key: email})`. Header: "📧 Email Setup".

- (existing token var) "Reconfigure Email?" yes/no
- Per-var loop with instructions ("Gmail: enable 2FA, create App Password"):
  - "  Email address" → `EMAIL_ADDRESS`
  - "  Email password (or app password)" (password) → `EMAIL_PASSWORD`
  - "  IMAP host" → `EMAIL_IMAP_HOST`
  - "  SMTP host" → `EMAIL_SMTP_HOST`
  - "  Allowed sender emails (comma-separated)" → `EMAIL_ALLOWED_USERS`
- (allowlist branch in `_setup_standard_platform`) If blank: "How should unauthorized users be handled?" choice [Open / DM pairing / Skip] → sets `GATEWAY_ALLOW_ALL_USERS` or `EMAIL_UNAUTHORIZED_DM_BEHAVIOR`

### Sub-flow: _setup_sms (gateway.py line 3072)

Delegates to `_setup_standard_platform({key: sms})`. Header: "📱 SMS (Twilio) Setup".

- (existing) "Reconfigure SMS (Twilio)?" yes/no
- "  Twilio Account SID" → `TWILIO_ACCOUNT_SID`
- "  Twilio Auth Token" (password) → `TWILIO_AUTH_TOKEN`
- "  Twilio phone number (E.164 format, e.g. +15551234567)" → `TWILIO_PHONE_NUMBER`
- "  Allowed phone numbers (comma-separated, E.164 format)" → `SMS_ALLOWED_USERS`
- "  Home channel phone number (for cron/notification delivery, or empty)" → `SMS_HOME_CHANNEL`
- (allowlist) "How should unauthorized users be handled?" choice [Open / DM pairing / Skip]

### Sub-flow: _setup_dingtalk (gateway.py line 3078)

Header: "💬 DingTalk Setup".

- (existing) "Reconfigure DingTalk?" yes/no
- "Choose setup method" choice [QR Code Scan / Manual Input]
  - QR branch: runs `dingtalk_qr_auth()` → writes `DINGTALK_CLIENT_ID`, `DINGTALK_CLIENT_SECRET`, `DINGTALK_ALLOW_ALL_USERS=true`. Falls back to manual on failure.
  - Manual branch: `_setup_standard_platform({key: dingtalk})`:
    - "  AppKey (Client ID)" → `DINGTALK_CLIENT_ID`
    - "  AppSecret (Client Secret)" (password) → `DINGTALK_CLIENT_SECRET`
    - Then `DINGTALK_ALLOW_ALL_USERS=true` auto-set.

### Sub-flow: _setup_feishu (gateway.py line 3432)

Header: "🪽 Feishu / Lark Setup".

- (existing) "Reconfigure Feishu / Lark?" yes/no
- "How would you like to set up Feishu / Lark?" choice [Scan QR code / Manual]
  - QR: runs `qr_register()`
  - Manual:
    - "  App ID" → `FEISHU_APP_ID`
    - "  App Secret" (password) → `FEISHU_APP_SECRET`
    - "  Domain" choice [feishu (China) / lark (International)] → `FEISHU_DOMAIN`
- (non-QR only) "  Connection mode" choice [WebSocket / Webhook] → `FEISHU_CONNECTION_MODE`
- "  How should direct messages be authorized?" choice [DM pairing / Allow all / Listed IDs]
  - listed → "  Allowed user IDs (comma-separated)" → `FEISHU_ALLOWED_USERS`
- "  How should group chats be handled?" choice [Mention-only / Disabled] → `FEISHU_GROUP_POLICY`
- "  Home chat ID (optional, for cron/notifications)" → `FEISHU_HOME_CHANNEL`

### Sub-flow: _setup_wecom (gateway.py line 3137)

Header: "💬 WeCom (Enterprise WeChat) Setup".

- (existing bot id + secret) "Reconfigure WeCom?" yes/no
- "How would you like to set up WeCom?" choice [QR scan / Manual]
  - QR: `qr_scan_for_bot_info()`
  - Manual: "  Bot ID" → `WECOM_BOT_ID`; "  Secret" (password) → `WECOM_SECRET`
- "  Allowed user IDs (comma-separated, or empty)" → `WECOM_ALLOWED_USERS`
  - If blank: "How should unauthorized users be handled?" choice [Open / DM pairing / Disable DMs / Skip] → `WECOM_DM_POLICY` ∈ {`open`, `pairing`, `disabled`} (+ `GATEWAY_ALLOW_ALL_USERS=true` on open)
- "  Home chat ID (optional, for cron/notifications)" → `WECOM_HOME_CHANNEL`

### Sub-flow: _setup_wecom_callback (delegates via `_setup_standard_platform({key: wecom_callback})`)

Header: "💬 WeCom Callback (Self-Built App) Setup".

- "  Corp ID" → `WECOM_CALLBACK_CORP_ID`
- "  Corp Secret" (password) → `WECOM_CALLBACK_CORP_SECRET`
- "  Agent ID" → `WECOM_CALLBACK_AGENT_ID`
- "  Callback Token" (password) → `WECOM_CALLBACK_TOKEN`
- "  Encoding AES Key" (password) → `WECOM_CALLBACK_ENCODING_AES_KEY`
- "  Callback server port (default: 8645)" → `WECOM_CALLBACK_PORT`
- "  Allowed user IDs (comma-separated, or empty)" → `WECOM_CALLBACK_ALLOWED_USERS`
  - blank → access-policy choice (as in `_setup_standard_platform`)

### Sub-flow: _setup_weixin (gateway.py line 3305)

Header: "💬 Weixin / WeChat Setup".

- (existing) "Reconfigure Weixin?" yes/no
- "Start QR login now?" yes/no → runs `qr_login()` → writes `WEIXIN_ACCOUNT_ID`, `WEIXIN_TOKEN`, optionally `WEIXIN_BASE_URL`, plus `WEIXIN_CDN_BASE_URL` default.
- "How should direct messages be authorized?" choice [DM pairing / Allow all / Listed IDs / Disable]
  - Listed: "  Allowed Weixin user IDs (comma-separated)" → `WEIXIN_ALLOWED_USERS`; sets `WEIXIN_DM_POLICY` ∈ {`pairing`, `open`, `allowlist`, `disabled`}
- "How should group chats be handled?" choice [Disabled / Open / Listed]
  - Listed: "  Allowed group chat IDs (comma-separated)" → `WEIXIN_GROUP_ALLOWED_USERS`; sets `WEIXIN_GROUP_POLICY`
- (if user_id known) "Use your Weixin user ID ({user_id}) as the home channel?" yes/no → `WEIXIN_HOME_CHANNEL`

### Sub-flow: _setup_bluebubbles (line 2802)

Header: "BlueBubbles (iMessage)".

- (existing) "Reconfigure BlueBubbles?" yes/no
- "BlueBubbles server URL (e.g. http://192.168.1.10:1234)" → `BLUEBUBBLES_SERVER_URL`
- "BlueBubbles server password" (password) → `BLUEBUBBLES_PASSWORD`
- "Allowed iMessage addresses (comma-separated, leave empty for open access)" → `BLUEBUBBLES_ALLOWED_USERS`
- "Home channel address (leave empty to set later)" → `BLUEBUBBLES_HOME_CHANNEL`
- "Configure webhook listener settings?" yes/no
  - "Webhook listener port (default: 8645)" → `BLUEBUBBLES_WEBHOOK_PORT`

### Sub-flow: _setup_qqbot (gateway.py line 3604)

Header: "🐧 QQ Bot Setup".

- (existing) "Reconfigure QQ Bot?" yes/no
- "How would you like to set up QQ Bot?" choice [QR scan / Manual]
  - Manual: "  App ID" → `QQ_APP_ID`; "  App Secret" (password) → `QQ_CLIENT_SECRET`
- "How should direct messages be authorized?" choice [DM pairing / Allow all / Listed IDs]
  - DM pairing + known openid: "Add yourself ({user_openid}) to the allow list?" yes/no → `QQ_ALLOWED_USERS`
  - Listed: "  Allowed user OpenIDs (comma-separated)" → `QQ_ALLOWED_USERS`
- (if user_openid) "Use your QQ user ID ({user_openid}) as the home channel?" yes/no → `QQBOT_HOME_CHANNEL`
- Else: "  Home channel OpenID (for cron/notifications, or empty)" → `QQBOT_HOME_CHANNEL`

### Sub-flow: _setup_webhooks (line 2873)

Header: "Webhooks".

- (existing `WEBHOOK_ENABLED`) "Reconfigure webhooks?" yes/no
- "Webhook port (default 8644)" → `WEBHOOK_PORT`
- "Global HMAC secret (shared across all routes)" (password) → `WEBHOOK_SECRET`
- Always sets `WEBHOOK_ENABLED=true`.

---

## Section: setup_tools (line 3145)

Delegates entirely to `tools_command(first_install, config)` in `cli/elevate_cli/tools_config.py`.

Header: "▲ Elevate Tool Configuration".

### first_install=True branch (line 1666)

Per enabled platform (CLI, gateway, etc.):

- `_prompt_toolset_checklist(platform_label, preselected)` — multi-select against `_get_effective_configurable_toolsets()` minus `_DEFAULT_OFF_TOOLSETS`. Writes to `config.platform_toolsets[<pkey>]`.
- For each newly enabled toolset that has `TOOL_CATEGORIES[<ts_key>]` or `TOOLSET_ENV_REQUIREMENTS[<ts_key>]`: calls `_configure_toolset(ts_key, config)` which iterates categories/providers and prompts for each provider's required env vars (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `BRAVE_API_KEY`, `FAL_KEY`, …). Provider picker:
  - "  {category_title}:" choice [provider 1 / provider 2 / …] → writes provider selection to `config.tools.<ts_key>.<category>` and then prompts for each required env var.
- Imagegen-specific: "Select image model:" choice with `_fal_model_catalog()` rows → `IMAGE_GEN_MODEL` / per-plugin keys.
- Vision (`_configure_simple_requirements` for vision toolset): "  Configure vision backend" choice [OpenRouter / OpenAI-compatible / Skip] → `OPENROUTER_API_KEY` or (`OPENAI_BASE_URL` config + `OPENAI_API_KEY` + `AUXILIARY_VISION_MODEL`)

### Returning-user branch (line 1725)

Looping menu:

- "Select an option:" choice — options vary per enabled platform:
  - `Configure {Platform}  (n/total enabled)` per platform → `_prompt_toolset_checklist` + `_configure_toolset` for new tools
  - `Configure all platforms (global)` (only when 2+ platforms)
  - `Reconfigure an existing tool's provider or API key` → `_reconfigure_tool(config)` ("  Which tool would you like to reconfigure?" choice → `_reconfigure_provider` prompts per env var "    {prompt} (Enter to keep current)")
  - `Configure MCP server tools` (only when `mcp_servers` exists) → `_configure_mcp_tools_interactive(config)`
  - `Done`

Toolset env-var prompts are sourced from `tools/tool_categories.py` (TOOL_CATEGORIES) and `tools/toolset_env_requirements.py` (TOOLSET_ENV_REQUIREMENTS); each provider declares its own `vars: [{name, prompt, password}]` list and the prompt asks them in order, writing to the named env var via `save_env_value`.
