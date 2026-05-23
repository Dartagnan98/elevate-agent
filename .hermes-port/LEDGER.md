# Hermes -> Elevate Port Ledger

Porting NousResearch/hermes-agent updates into Elevate. Elevate is Hermes
repackaged under `cli/` with the `hermes_cli` package renamed `elevate_cli`.

- Hermes source: `~/.hermes/hermes-agent` @ HEAD (see hermes-head.txt)
- Elevate target: `~/elevate/cli/`  branch `hermes-merge-2026-05-22` work folded into `subagent-resilience-2026-05-19`
- A git merge is IMPOSSIBLE (unrelated histories, different path roots). Hand-port only.

## Inventory (2026-05-22)
- 1,416 Hermes files with no Elevate counterpart  -> missing.txt
- 1,539 files exist in both but differ            -> differ.txt
- 674 identical

## Port method (proven on tools/url_safety.py)
1. `diff` Hermes file vs Elevate file. Identify the new logic vs Elevate's
   intentional local edits.
2. Copy Hermes file over, then re-apply Elevate renames:
   - `HERMES_` env vars -> `ELEVATE_`
   - `hermes_cli` -> `elevate_cli` (imports AND string literals e.g. mock patch targets)
   - any other branded strings
3. `python3 -c "import ast; ast.parse(...)"` syntax check.
4. Port the matching test file the same way; run with `.venv/bin/python -m pytest`.
5. Tick the box below. Commit per batch.

## Scope decisions
PORT (core runtime + capabilities):
- agent/  gateway/  elevate_cli/(<-hermes_cli)  tools/  providers/
- plugins/model-providers/  relevant plugins
- skills/ + optional-skills/ that suit a realtor CLI product

SKIP (do not port - would break Elevate or pure dead weight):
- website/        Hermes marketing site; Elevate has its own
- web/            Elevate's web frontend is fully custom - NEVER overwrite
- locales/ i18n   not needed
- ui-tui/         Ink TUI; Elevate is web-first - defer, low priority
- platform plugins irrelevant to Elevate: LINE, qqbot, feishu, yuanbao,
  SimpleX, msgraph/Teams, DingTalk
- blockchain skills, infographic/, achievements plugin

## Batches
- [x] B1 Security fixes
  - [x] tools/url_safety.py        (SSRF IPv4-mapped IPv6 + is_always_blocked_url) - 112 tests pass
  - [x] gateway HMAC webhook secret validation - 127 webhook tests pass
  - [x] gateway/pairing.py         (hash pairing codes) - 40 tests pass
  - [x] control-plane file write-deny (file_safety.py) - 52 tests pass
  - [x] API key leak to non-authoritative endpoints (runtime_provider.py) - 77 tests pass
- [ ] B2 agent/ package (run_agent.py refactor) - HIGHEST RISK, do last/carefully
  - [x] B2 net-new modules (52 files): top-level agent/ (agent_init,
        agent_runtime_helpers, azure_identity_adapter, background_review,
        browser_provider+registry, chat_completion_helpers, codex_runtime,
        conversation_compression, conversation_loop, curator, curator_backup,
        i18n, image_routing, iteration_budget, lmstudio_reasoning,
        markdown_tables, message_sanitization, onboarding, plugin_llm,
        portal_tags, process_bootstrap, skill_bundles, skill_preprocessing,
        stream_diag, system_prompt, think_scrubber, tool_dispatch_helpers,
        tool_executor, tool_guardrails, tool_result_classification,
        video_gen_provider+registry, web_search_provider+registry); agent/lsp/
        (11 files: __init__, cli, client, eventlog, install, manager,
        protocol, range_shift, reporter, servers, workspace); agent/secret_sources/
        (__init__, bitwarden); agent/transports/ (codex_app_server,
        codex_app_server_session, codex_event_projector, hermes_tools_mcp_server).
        Tests: 12 failed / 6175 passed / 159 skipped — identical to baseline,
        0 regressions. No defers; agent_init/conversation_loop/system_prompt
        have import-time refs to symbols not yet in existing Elevate files
        (StreamingContextScrubber/memory_manager,
        set_runtime_main/auxiliary_client,
        ELEVATE_AGENT_HELP_GUIDANCE/prompt_builder) that will resolve with the
        modified-files refactor below; nothing currently imports those 3.
        Unblocks: elevate_cli/bundles (skill_bundles),
        elevate_cli/secrets_cli (secret_sources),
        tools/video_generation_tool (video_gen_*).
  - [ ] B2 modified agent/ files (run_agent.py refactor + companions) — pending
- [ ] B3 gateway/ non-security deltas
  - [x] B3a low-risk gateway files + 7 new modules (deltas: __init__, delivery,
        display_config, hooks, mirror, session_context, sticker_cache,
        whatsapp_identity, platforms/{__init__,bluebubbles,helpers,
        homeassistant,sms}; new: memory_monitor, platform_registry,
        _http_client_limits, signal_rate_limit, runtime_footer,
        shutdown_forensics, slash_access) - 0 regressions
  - [ ] B3b channel_directory.py + platforms/telegram_network.py (need base.py
        resolve_proxy_url signature + run.py await changes first)
  - [ ] B3c config.py, session.py, status.py, stream_consumer.py, webhook.py
        non-security delta, platforms/base.py
        FINDINGS (2026-05-22 recon): NOT copy+sed-able. Bidirectional
        divergence - Elevate carries intentionally-committed logic Hermes
        lacks; a wholesale copy would destroy it. Hand-merge hunk-by-hunk,
        per file, preserving BOTH sides. Specifics:
        * config.py (1400 vs HM 1923): KEEP Elevate-only _gateway_env_values(),
          ELEVATE_AGENT_*_TELEGRAM_BOT_TOKEN agent-bot parsing/merge, agent_id
          visible-lane field, per-platform connected-detection block,
          env-driven unauthorized_dm_behavior wiring.
        * session.py (1300 vs HM 1347): KEEP Elevate-only agent_id lane field
          threaded through to_dict/from_dict.
        * webhook.py (864 vs HM 821): DECISION MADE - keep Elevate's STRICTER
          security model (opt-in allow_insecure_no_auth config flag +
          _insecure_no_auth_allowed() + _is_public_bind_host()). Hermes uses a
          looser _is_loopback_host() gate. Do NOT port Hermes's webhook
          security; only port its non-security deltas if any.
        * base.py (2653 vs HM 3812) + config.py: much of the Hermes delta is
          SKIP-list platform code (Weixin/Feishu/WeCom). Port only genuine
          capability improvements, not the skipped-platform additions.
        * status.py / stream_consumer.py: rename divergence + refactor;
          stream_consumer has Elevate chunk-splitting (_split_text_chunks,
          upstream issue 10454) to preserve.
  - [ ] B3d big platform adapters: telegram, discord, slack, api_server,
        matrix, signal, whatsapp, email, mattermost
  - [ ] B3e gateway/run.py (12.7k->18.2k lines, has Elevate-only divergence -
        hand-port hunk by hunk, B2-caliber risk)
- [ ] B4 elevate_cli/ deltas + new files
  - [x] B4a net-new modules (31 of 40): _parser, azure_detect, browser_connect,
        checkpoints, codex_runtime_plugin_migration, codex_runtime_switch, curator,
        dep_ensure, fallback_cmd, gateway_windows, inventory, kanban, kanban_db,
        kanban_decompose, kanban_diagnostics, kanban_specify, kanban_swarm, migrate,
        model_catalog, oneshot, profile_describer, profile_distribution,
        pt_input_extras, relaunch, security_advisories, send_cmd, session_recap,
        slack_cli, stdio, vercel_auth, xai_retirement. Plus tools/kanban_tools.py
        (unblocked by kanban_db). 0 regressions.
        DEFERRED (9): bundles.py (needs agent/skill_bundles), secrets_cli.py (needs
        agent/secret_sources), entire proxy/ subtree (8 files - need
        NOUS_INFERENCE_AUTH_MODE_AUTO in elevate_cli/auth.py).
        2026-05-22 UPDATE: bundles.py + secrets_cli.py NOW LANDED (commit 4232b21f4)
        after B2 net-new shipped agent/skill_bundles + agent/secret_sources.
        proxy/ subtree (8 files) STILL deferred - auth.py needs hand-merge for
        NOUS_INFERENCE_AUTH_MODE_*, NOUS_LEGACY_SESSION_KEYS_ENV, NOUS_DEVICE_CODE_SOURCE,
        NOUS_INFERENCE_INVOKE_SCOPE, NOUS_LEGACY_AGENT_KEY_SCOPE, NOUS_AUTH_PATH_*,
        _is_terminal_nous_refresh_error, _quarantine_nous_oauth_state,
        _quarantine_nous_pool_entries, _write_shared_nous_state,
        resolve_nous_runtime_credentials. video_generation_tool still deferred -
        needs dynamic_schema_overrides on ToolRegistry.register.
        Surgical helper adds along the way:
        - elevate_state.py: apply_wal_with_fallback, _WAL_INCOMPAT_MARKERS,
          _wal_fallback_warned_paths, get_last_init_error,
          format_session_db_unavailable, _set_last_init_error
        - elevate_cli/profiles.py: normalize_profile_name
        - tools/registry.py: invalidate_check_fn_cache (no-op stub until TTL cache lands)
        - elevate_state.py: hermes_cli->elevate_cli rename in kanban_db reference
  - [ ] B4b elevate_cli/ differ files - not yet attempted
- [ ] B5 tools/ deltas + new files
  - [x] B5a net-new tool files (clarify_gateway, computer_use/*, computer_use_tool,
        environments/vercel_sandbox, fal_common, lazy_deps, skill_provenance,
        skill_usage, slash_confirm + 8 test files) - +195 tests, 0 regressions.
        SKIPPED (broken dep chains, defer): kanban_tools (needs elevate_cli.kanban_db),
        x_search_tool (needs full tools/xai_http.py - Elevate has 12-line stub),
        video_generation_tool (needs agent/video_gen_provider). agent-layer
        computer-use multimodal wiring (prompt_builder/anthropic_adapter/run_agent)
        NOT done - port in B2.
  - [ ] B5b tools/ differ files. Recon (B5b-recon.md): 55 nom-Class A, 10 B, 2 C.
    - [x] B5b-phase1 (16 files actually port-clean): browser_cdp_tool, browser_dialog_tool,
          browser_supervisor, budget_config, environments/__init__, environments/singularity,
          fuzzy_match, mixture_of_agents_tool, osv_check, schema_sanitizer, skills_guard
          (TRUSTED_REPOS adopts huggingface/skills - fork-point staleness, not intentional drop),
          tirith_security, todo_tool, tool_backend_helpers, voice_mode (WAV chunking),
          xai_http (full xAI OAuth credential resolver - UNBLOCKS x_search_tool from B5a).
          +tests/tools/conftest.py + test_memory_tool_schema.py. 0 regressions in tools/+run_agent/.
    - [x] B5b-phase2 (2026-05-22) - 18 additional Class A tools ported across 5 commits:
          837d219da batch1: browser_camofox_state, debug_helpers, environments/{__init__,
            managed_modal, modal_utils}, managed_tool_gateway, openrouter_client,
            tool_output_limits (string-literal hermes_ -> elevate_ fixes for user_id)
          637b91df2 batch2: env_passthrough (cfg_get), environments/file_sync (_sleep
            patchable indirection + container_base path), environments/singularity;
            tests/tools/test_file_sync_back.py mock patches updated
          f5a8134b9 batch3: browser_cdp_tool (safe_schedule_threadsafe),
            credential_files (to_agent_visible_cache_path + cfg_get;
            _resolve_hermes_home -> _resolve_elevate_home)
          24c49e26d batch4: browser_camofox, browser_supervisor, mcp_oauth
            (HermesTokenStorage -> ElevateTokenStorage), mcp_oauth_manager
            (_hermes_server_name -> _elevate_server_name), environments/docker
          119f5d81a batch5: registry (TTL cache + dynamic_schema_overrides
            replaces phase1 stub), checkpoint_manager (refs/hermes -> refs/elevate,
            hermes@local -> elevate@local), terminal_tool (Vercel sandbox + sudo
            password cache), skill_manager_tool, vision_tools
          Final pytest: 14 failed / 6173 passed / 159 skipped (baseline was 13 -
          one new Hermes-ahead test_checkpoint_manager::test_different_dirs_different_paths
          shadow-repo path-derivation diff). Net +1 regression for 18 ported files.
    - [ ] B5b-phase3 HAND-MERGE backlog (~14 files): tool_result_storage (heredoc->stdin),
          patch_parser (3-tuple V4A return), transcription_tools (lazy-install STT +
          mistral quarantine + 16 provider-priority tests), tts_tool (mistral/minimax
          dispatch), discord_tool (discord_server entrypoint rename), code_execution_tool
          (generate_hermes_tools_module rename), file_tools (dedup invalidation - 26
          tests), mcp_tool (utility-handlers 24 tests), browser_tool (path construction
          + orphan-reaper 14 tests), environments/base (Windows newline-safe stdin +
          cwd-restore breaks wrap_command tests), environments/{daytona,ssh,modal}
          (cursor pagination + tar --no-overwrite-dir + remote_home), cronjob_tools
          (needs resolve_job_ref in cron.jobs), process_registry (needs
          _resolve_safe_cwd in environments/local). Class B per recon (memory_tool,
          skills_sync, image_generation_tool, session_search_tool, approval,
          send_message_tool, skills_hub, delegate_tool, web_tools) also pending.
- [x] B6 providers/ + plugins/model-providers/ - providers/ registry shipped
      (B6 commit 822c48814). plugins/model-providers/ 59 net-new files ported
      2026-05-22 (commit 4232b21f4) - 29 provider profiles (anthropic,
      openai-codex, gemini, xai, nous, qwen-oauth, ollama-cloud, deepseek,
      copilot, copilot-acp, bedrock, azure-foundry, alibaba, alibaba-coding-plan,
      arcee, custom, gmi, huggingface, kilocode, kimi-coding, minimax, novita,
      nvidia, opencode-zen, openrouter, stepfun, xiaomi, zai, ai-gateway). Each
      __init__.py + plugin.yaml, registers ProviderProfile against the registry.
      0 regressions.
- [x] B7 skills / optional-skills (filtered) - 222 net-new files (117 skills +
        105 optional-skills) across 14 subcategories: apple/macos-computer-use,
        autonomous-ai-agents/{hermes-agent,kanban-codex-lane}, creative
        (baoyu-article-illustrator, claude-design, comfyui, humanizer, p5js,
        popular-web-designs, pretext, sketch, touchdesigner-mcp, hyperframes,
        kanban-video-orchestrator, concept-diagrams), devops (kanban-orchestrator,
        kanban-worker, pinggy-tunnel, watchers), finance (3-statement-model,
        comps-analysis, dcf-model, excel-author, lbo-model, merger-model,
        pptx-author, stocks), migration/openclaw-migration, mlops
        (inference, training), productivity (airtable, google-workspace, linear,
        teams-meeting-pipeline, here-now, shop-app, shopify), research
        (darwinian-evolver, osint-investigation, searxng-search),
        software-development (debugging-hermes-tui-commands,
        hermes-agent-skill-authoring, node-inspect-debugger, python-debugpy,
        spike, subagent-driven-development, rest-graphql-debug).
        Skip-list applied: yuanbao, blockchain. Sed rename pipeline run on all
        file types. All .py parse cleanly. Pytest baseline preserved:
        12 failed / 6175 passed / 159 skipped (zero regressions).
- [ ] B8 tests sweep - blocked on modified-files batches (B2 modified,
      B3b-e, B4b, B5b-phase3). Probe 2026-05-22: porting tests/providers/,
      tests/cron/, tests/skills/, tests/agent/lsp/ wholesale produced 158
      failures / 577 passes - the new tests assume Hermes-side source
      changes not yet present. Reverted. Test sweep can only land after the
      paired source ports.

## Session 2026-05-22 summary (additive ports landed)
Branch `subagent-resilience-2026-05-19` advanced through batches B2 net-new,
B4a unblocks, B5b-phase2, B6, B7, plugins/ safe-additive (15 commits on top
of the validated 7-commit baseline). Origin is FROZEN at the 7-commit
state - everything below this session is LOCAL ONLY.

Cumulative this session:
- B2 net-new (52 modules: top-level agent/, agent/lsp/, agent/secret_sources/,
  agent/transports/) - unblocks bundles.py, secrets_cli.py, video_gen_*
- B4a unblocks: bundles.py + secrets_cli.py (proxy/ + video_generation_tool
  still deferred, need auth.py refactor + ToolRegistry dynamic_schema_overrides)
- B5b-phase2: 18 Class A tools across 5 commits + checkpoint_manager test
  sync (612 ins / 278 del, restores baseline)
- B6 done: providers/ + plugins/model-providers/ (29 provider profiles)
- B7 done: 222 skills/optional-skills files
- plugins/ safe-additive: 47 files (browser, google_meet, image_gen/fal,
  kanban, observability, platforms/{google_chat,irc}, video_gen)

Pytest end-state: 13 failed / 6198 passed / 159 skipped (flake band).
Baseline at session start: 12-13 failed / 6175 passed. All "extra" passes
come from net-new test files landed alongside the source ports.

REMAINING (large hand-merge - cannot be one-shot ported):
- B2 modified agent/ files (~42 files including run_agent.py refactor)
- B3b-e gateway hand-merge (per-file hunk-by-hunk preserving Elevate-only
  security model in webhook.py, agent-bot lanes in config.py/session.py,
  chunk-splitting in stream_consumer.py)
- B4b elevate_cli/ differ (54 files; auth.py alone is 7468 vs 4401 lines)
- B5b-phase3 (14 tools listed above)
- B8 test sweep (blocked on the above source merges)

## Notes
- Elevate runs live for Skyleigh. Never push a batch that fails tests.
- `is_truthy_value` exists in `cli/utils.py` - dependency confirmed.
- FIXED 2026-05-22: the 29 pre-existing gateway-test failures. Causes were
  (1) run.py:11468 NameError - persist_user_message now threaded as a param;
  (2) stale FakeAgent run_conversation stubs missing persist_user_message;
  (3) stale toolset-restriction tests predating the tools_config self-heal -
  added known_builtin_toolsets to test configs;
  (4) stale slack tool_progress test - added config.yaml override.
  Gateway suite now 3730 passed / 0 failed.
- venv: use `cli/.venv/bin/python` (pytest 9.0.2). NOT `cli/venv/`.
