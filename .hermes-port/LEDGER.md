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

## Session 2026-05-22 continuation — B4b elevate_cli/ progress

Landed since last summary block (LOCAL ONLY, origin still frozen):
- B4b yuanbao+browser fix (commit 791e2a430)
- B4b voice + skills_hub (8cdf9a516)
- B4b register_browser_provider on PluginContext (d027ad00b)
- B4b small deltas batch (f05e80b70): hooks/model_normalize/curses_ui/dump/completion/webhook
- B4b Bitwarden + hardening (485851e0c): env_loader/memory_setup/mcp_config
- B4b status + debug redaction (5d9913ab8): status.py mask_secret, debug.py --no-redact full feature port + main.py wiring
- B4b goals subgoals + judge parse-failure auto-pause (dedb1bf42): goals.py 3-tuple judge return, /subgoal mid-loop criteria, DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES guard, max_tokens 200->4096
- B4b skin_engine hardening (0e9e13faa): selection_bg color, _mapping_or_empty defensive YAML parsing, prompt_symbol normalization

B4b SKIPPED / DEFERRED:
- banner.py: Elevate-specific ELEVATE/AGENT ASCII (intentional divergence)
- pty_bridge.py: Elevate ahead (better Windows TERM handling)
- tips.py: references curator/snapshot/kanban/footer/redraw not yet ported
- providers.py: 9 new providers (xAI OAuth, LM Studio, MiniMax OAuth, Novita,
  Tencent TokenHub, GMI Cloud, Ollama Cloud, Azure Foundry, AWS Bedrock) +
  aliases — paired with auth.py/models.py port
- status.py OAuth helpers (MiniMax, xAI, LM Studio probe, Vercel sandbox runtime)
  — paired with auth.py port
- auth_commands.py (173 lines diff): paired with auth.py port

B4b REMAINING priority queue:
- auth.py (7468 vs 4401 lines): the foundational port that unblocks providers.py,
  auth_commands.py, status.py-OAuth-rest, video_generation_tool, proxy/

Test net: 0 new regressions. 4065 passed in elevate_cli/+gateway/ sweep.

## Session 2026-05-22 continuation - B4b wholesale-port spree

After context summary, B4b continued with the rename-pipeline pattern. Each
file: backup -> grep+sed compound renames -> spot-check residual hermes refs ->
deploy -> run paired tests -> commit.

LANDED THIS SESSION (LOCAL ONLY, origin frozen):
- 8dac4200f auth.py + models.py wholesale (force_mint kwarg for 401-recovery,
  union_with_portal_free_recommendations, get_curated_nous_model_ids)
- d156b4786 providers + auth_commands + status (9 new providers, oauth helpers,
  manual:elevate_pkce source slug)
- 77840b30c __init__.py Windows UTF-8 stdout/stderr fix (_ensure_utf8 for
  cp1252 box-drawing crashes)
- 12988431f nous_subscription.py (searxng + Browserbase env detection)
- ec46f759f mcp_config + cron + hooks + kanban_db (cfg_get, resolve_job_ref +
  AmbiguousJobReference, tuple->set membership)
- f4fc60262 backup.py + claw.py + test_claw.py (added create_pre_migration_backup,
  create_pre_update_backup, _write_full_zip_backup; --no-backup flag in claw)
- 305f1f398 plugins.py (refreshed discovery/loader; preserves
  elevate_agent.plugins entry-point + elevate_plugins namespace package)
- e53ffe665 uninstall.py (Windows env-var cleanup, PATH marker detection,
  per-profile gateway tear-down)
- 038a95991 plugins_cmd.py (list/install/enable/disable refresh)
- 7a39702bc profiles.py (create/use/delete/show/alias/rename/export/import
  refresh; preserved Elevate-specific generate_bash_completion +
  generate_zsh_completion functions)
- fe167c416 commands.py (run_doctor, run_status, run_config, etc surface refresh)

DEFERRED IN THIS SESSION (Elevate ahead of Hermes, wholesale would erase
intentional divergence):
- model_switch.py: Elevate has endpoint-grouping logic
  (test_list_authenticated_providers_groups_same_endpoint and 3 siblings) that
  Hermes lacks. Reverted after wholesale port broke 4 tests.
- doctor.py: Elevate carries "Browser Use" cloud integration (BROWSER_USE_API_KEY,
  managed Browser Use prompts) - 10+ refs in Elevate, 0 in Hermes. Reverted
  after wholesale port broke 2 termux browser-detection tests. Surgical merge
  needed: take Hermes browser tier-down + termux gating only.

B4b REMAINING (high-risk, defer or surgical-merge only):
- config.py (+1047 risky): Elevate-only _gateway_env_values, agent-bot lane
  parsing
- gateway.py (+1112 risky): Elevate-only gateway lifecycle wrapping
- tools_config.py (+1104 risky): Elevate-only Browser Use / yuanbao gating
- runtime_provider.py: 19-test break on wholesale (reverted last session);
  needs surgical merge
- main.py, web_server.py, setup.py, memory_setup.py, banner.py, default_soul.py,
  timeouts.py, dump.py: confirmed Elevate divergent - SKIP per scope decision

Test net this session: 8 failed / 2561 passed in hermes_cli/ sweep =
matches baseline (no new regressions). Pre-existing failures isolated to
test_mcp_config + test_model_validation + test_setup_openclaw_migration +
test_runtime_provider_resolution + test_setup_model_provider.

## Session 2026-05-23 — B2 modified agent/ files surgical-merge spree

Continued from prior context-summarized session. Three more unblocker
commits + 5 substantive ports landed. All LOCAL ONLY; origin still frozen
at validated 7-commit state.

LANDED THIS SESSION (LOCAL ONLY):
- 00592dc1b prompt_builder.py surgical: ELEVATE_AGENT_HELP_GUIDANCE +
  KANBAN_GUIDANCE constants. Third unblocker (after memory_manager
  StreamingContextScrubber and auxiliary_client set_runtime_main).
  Hermes->Elevate identifier swaps: ~/.hermes/kanban.db -> ~/.elevate/kanban.db,
  $HERMES_KANBAN_* -> $ELEVATE_KANBAN_*, hermes kanban verb -> elevate kanban verb.
- 3104b7ce6 context_engine.py docstring + credential_sources.py
  xai-oauth/minimax-oauth removal steps. Fixes silent removal-revert bug
  where `elevate auth remove xai-oauth <N>` left providers entries intact
  in auth.json and they re-seeded via _seed_from_singletons.
- 3c73cb7ef memory_provider.py on_session_switch hook + on_memory_write
  metadata kwarg. models_dev.py disk-cache stage-2 short-circuit
  (~500ms cold-start savings), suffix-aware fallback for :cloud/-cloud
  variants, refined vision-detection logic, new provider aliases
  (novita, kimi, moonshot, minimax-oauth, xai-oauth).
- e2ba0341e moonshot_schema.py rules 3-5 (enum null-stripping, $ref
  sibling stripping, tuple-items collapse) + expanded rule 2
  (anyOf null-branch collapse). Paired test port: 34->42 tests pass.
- 31d26dea6 skill_utils.py Termux/Android platform-tag gating.
  Linux-tagged skills now compatible inside Termux on Python 3.13+
  where sys.platform reports "android".

DEFERRED THIS SESSION (Elevate ahead of Hermes — wholesale port
would erase intentional divergence):
- skill_commands.py: Elevate has access-control hook
  (elevate_cli.access.evaluate_skill_access), [SYSTEM:] activation-note
  prefix expected by tests, argument-placement UX (treats user
  instruction as subject before skill body). Hermes uses different
  ordering + [IMPORTANT:] prefix + lacks access control.
- title_generator.py: Elevate adds FailureCallback / TitleCallback /
  main_runtime parameters + _backfill_worker async backfill mechanism.
  Hermes regressed all of these.
- display.py: Elevate adds rl_* tool display previews + multimodal
  result handling + file_mutation_result_landed classifier. RL training
  tools are Elevate-only feature.
- insights.py: Elevate-only generate_turn_usage() and turn_usage table
  analytics. Hermes lacks this surface entirely.
- prompt_builder.py wholesale: Elevate adds get_prompt_hidden_skill_names,
  build_memory_guidance factory, build_openai_model_execution_guidance
  scoped tool guidance, _tool_choice helper. TOOL_USE_ENFORCEMENT_MODELS
  extended with glm/qwen/deepseek. Only KANBAN_GUIDANCE +
  ELEVATE_AGENT_HELP_GUIDANCE constants were surgically added.
- google_code_assist.py (-1 line): Elevate ahead, trivial divergence.
- portal_tags.py: pure rename diff (already applied to Elevate version),
  no logic difference.

B2 REMAINING (high-risk surgical merges — defer further):
- codex_responses_adapter.py (E=813 H=1082, +269): Elevate has
  _chat_content_to_responses_parts + _chat_messages_to_responses_input
  helpers Hermes refactored differently.
- credential_pool.py (E=1453 H=1955, +502): large surface refresh.
- model_metadata.py (E=1417 H=1828, +411): metadata expansion.
- context_compressor.py (E=1331 H=1748, +417): compression refresh.
- anthropic_adapter.py (E=1719 H=2244, +525): largest adapter delta.
- auxiliary_client.py (E=3365 H=5289, +1924): only surgical
  set_runtime_main added this session; full divergence too large.

Test sweep at session end:
  tests/agent/ 1947 passed, 1 skipped, 3 pre-existing failures (none new)
    (test_auxiliary_named_custom_providers, test_prompt_builder
    empty_soul_md_adds_nothing, test_skill_commands disable_template_vars).
  Baseline at session start: 1798 passing. Net +149 tests from new ports
  and paired test pulls (memory, models_dev, moonshot, credentials).

## 2026-05-23 (continued) — auxiliary_client lands

a73e748d5 auxiliary_client wholesale port (+1924 lines) + paired tests.

All 6 heavy-hitter B2 carried files complete:
  - codex_responses_adapter (900c606bf)
  - context_compressor (5f9944907)
  - credential_pool (03af93aaf)
  - model_metadata (cde257835)
  - anthropic_adapter (0770d2b28)
  - auxiliary_client (a73e748d5) <-- this session

Elevate-only surgical re-adds in auxiliary_client:
  _CODEX_AUX_MODEL constant, _try_codex() helper, codex in
  _get_provider_chain (5 entries vs Hermes 4), codex auto-fallback
  in resolve_provider_client, _OR_HEADERS backwards-compat alias.

tests/agent/: 2018 passing, 1 skipped, 3 baseline failures.
Net +71 tests from this session.

NEXT: B2 modified files remaining are smaller / lower risk. Pick from
the B2 differ list or move to B4b elevate_cli/ files (task #11).
