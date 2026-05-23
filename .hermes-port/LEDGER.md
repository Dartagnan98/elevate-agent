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
    - [ ] B5b-phase2 BLOCKED until helpers ported. ~23 Class A tool files revert because
          Hermes versions import symbols missing in Elevate: cfg_get (elevate_cli.config),
          AmbiguousJobReference (cron.jobs), _subprocess_compat (elevate_cli),
          secure_parent_dir (elevate_constants), atomic_replace (utils),
          safe_schedule_threadsafe (agent.async_utils). PORT ORDER REVISION: do B4 elevate_cli
          + agent-layer helpers FIRST, then re-attempt these tools. Also ~9 files have
          behavior-changes the recon under-classified (Hermes-strict but breaks Elevate
          callers): discord_tool (entrypoint rename), code_execution_tool (psutil hard dep),
          file_operations (fence regex narrowing), file_tools (redact_sensitive_text kwarg),
          environments/{file_sync,modal,daytona,base,ssh}, patch_parser (3-tuple return),
          transcription_tools, tool_result_storage, checkpoint_manager, vision_tools, tts_tool,
          mcp_oauth_manager, registry (TTL cache leak). Real Class B - need hand-merge.
- [ ] B6 providers/ + plugins/model-providers/
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
- [ ] B8 tests sweep

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
