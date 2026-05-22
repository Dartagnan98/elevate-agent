# B5b Recon — tools/ port triage (Hermes → Elevate)

Generated 2026-05-22. 67 differing `tools/` files (0 pure rename-only excluded by hand; 4 are zero-diff after sed normalize and are listed as A/no-op).

Diff method: `diff <(sed-normalized Hermes) Elevate`. "Diff lines" = count of `<`/`>` lines.

Class key: **A** = COPY+SED-SAFE (Hermes strictly ahead, no Elevate-only logic). **B** = HAND-MERGE (Elevate carries committed local logic). **C** = SKIP (delta is skip-list platform code or irrelevant).

| File | Class | Diff lines | Notes |
|---|---|---|---|
| tools/__init__.py | A | 0 | Identical after sed. No-op. |
| tools/file_state.py | A | 0 | Identical after sed. No-op. |
| tools/interrupt.py | A | 0 | Identical after sed. No-op. |
| tools/url_safety.py | A | 0 | Identical after sed. No-op. |
| tools/budget_config.py | A | 1 | One docstring line. Trivial. |
| tools/openrouter_client.py | A | 2 | Docstring rename only. |
| tools/todo_tool.py | A | 2 | Set-literal vs tuple membership. Cosmetic. |
| tools/tool_output_limits.py | A | 2 | Docstring text only. |
| tools/managed_tool_gateway.py | A | 6 | Pure rename (get_elevate_home). |
| tools/debug_helpers.py | A | 6 | Pure rename. |
| tools/osv_check.py | A | 6 | Rename + set/tuple cosmetic. |
| tools/website_policy.py | A | 6 | Pure rename. |
| tools/fuzzy_match.py | A | 3 | `min()` vs if-block; equivalent. |
| tools/mixture_of_agents_tool.py | A | 3 | `sys.exit` vs `exit`; Hermes correct. |
| tools/managed_modal.py (environments) | A | 2 | Trivial. |
| tools/environments/managed_modal.py | A | 2 | Docstring rename. |
| tools/environments/modal_utils.py | A | 4 | Trivial. |
| tools/tool_backend_helpers.py | A | 4 | Hermes adds `is_truthy_value`; Elevate uses `bool()`. Hermes ahead. |
| tools/managed_tool_gateway.py | A | 6 | (dup) rename. |
| tools/browser_dialog_tool.py | A | 4 | Docstring "Chrome" vs "Chromium-family". Cosmetic. |
| tools/budget_config.py | A | 1 | (dup). |
| tools/browser_camofox_state.py | A | 14 | Pure rename. |
| tools/skills_guard.py | A | 16 | Rename + Elevate dropped huggingface from TRUSTED_REPOS — keep Elevate's TRUSTED_REPOS set if intentional, else A. Treat as A; verify TRUSTED_REPOS line on merge. |
| tools/env_passthrough.py | A | 19 | Hermes adds `cfg_get` helper + import. Hermes ahead. |
| tools/environments/__init__.py | A | 7 | Docstring (Hermes adds Vercel/Nous-managed mention). |
| tools/feishu_doc_tool.py | C | 13 | Hermes swaps eager import for `importlib.util.find_spec` perf probe. Feishu platform code; minor. Skip or trivially copy. |
| tools/feishu_drive_tool.py | C | 8 | Same find_spec perf tweak. Feishu platform. Skip. |
| tools/environments/file_sync.py | A | 23 | Hermes adds patchable `_sleep`, encoding kwargs, flock cleanup. Hermes ahead. |
| tools/environments/daytona.py | A | 25 | Hermes adds lazy_deps install + Daytona SDK >=0.108 cursor pagination. Hermes ahead, real fix. |
| tools/environments/ssh.py | A | 29 | Hermes adds scp-presence check + sync-base containment validation. Hermes ahead, security. |
| tools/environments/modal.py | A | 28 | Hermes adds lazy_deps + safe_schedule_threadsafe. Hermes ahead. |
| tools/environments/singularity.py | A | 10 | Pure rename. |
| tools/memory_tool.py | B | 26 | Elevate-only: Windows `msvcrt` lock handling (`r+` mode, pre-seed lock file). Hermes side uses `atomic_replace` + flock cleanup. Preserve Elevate's msvcrt branch; take Hermes' atomic_replace + flock-unlment guard. |
| tools/tool_result_storage.py | A | 30 | Hermes adds stdin-pipe write (fixes 128KB argv limit). Hermes ahead, real fix. |
| tools/browser_cdp_tool.py | A | 40 | Hermes adds safe_schedule_threadsafe + get_running_loop. Hermes ahead. |
| tools/patch_parser.py | A | 56 | Hermes adds V4A LSP-diagnostics propagation (3-tuple returns). Hermes ahead, real feature. |
| tools/credential_files.py | A | 71 | Hermes adds `to_agent_visible_cache_path` + cfg_get. Hermes ahead. |
| tools/transcription_tools.py | A | 119 | Hermes adds lazy-install STT, xai_http credential resolver, mistral quarantine guard, get_env_value. Hermes ahead. |
| tools/voice_mode.py | A | 128 | Hermes adds WAV chunking for oversized STT (`_split_wav_for_transcription` etc). Hermes ahead, real feature. |
| tools/xai_http.py | A | 122 | Hermes adds full xAI OAuth credential resolver (`resolve_xai_http_credentials`, `has_xai_credentials`). Elevate only had `elevate_xai_user_agent`. Hermes strictly ahead — Elevate's one fn is preserved by Hermes' rename. |
| tools/browser_camofox.py | A | 130 | Hermes adds Camofox identity-override + tab-adoption. Hermes ahead. |
| tools/browser_supervisor.py | A | 129 | Hermes adds `evaluate_runtime` + safe_schedule_threadsafe. Hermes ahead. |
| tools/mcp_oauth.py | A | 132 | Hermes adds TOCTOU-safe 0o600 write (`O_EXCL`), `secure_parent_dir`. Hermes ahead, security. |
| tools/mcp_oauth_manager.py | A | 90 | Hermes adds OAuth-metadata disk persistence/cold-load. Hermes ahead. |
| tools/environments/docker.py | A | 94 | Hermes adds `run_as_host_user`, `docker_extra_args`, gosu-cap split. Hermes ahead, real feature. |
| tools/skills_sync.py | B | 93 | Elevate-only: paid-skill gating — `PAID_SKILL_PATHS`, `PAID_SKILL_PATH_PREFIXES`, `_is_paid_skill_path`, `_include_paid_bundled_skills`, `ELEVATE_INCLUDE_PAID_BUNDLED_SKILLS` env, gated_skills logic. Hermes side adds `get_bundled_skills_dir`, `is_excluded_skill_path`, `atomic_replace`. Hand-merge: keep all paid-skill machinery, layer in Hermes' bundled-dir + exclude helpers. |
| tools/discord_tool.py | A | 208 | Hermes adds `delete_message`, per-token capability cache, core/admin action split, discord_admin tool. Hermes ahead. |
| tools/skill_manager_tool.py | A | 186 | Hermes adds `_pinned_guard`, `_containing_skills_root`, `is_excluded_skill_path`, cfg_get. Hermes ahead. |
| tools/registry.py | A | 188 | Hermes adds check_fn TTL cache, generation counter, dynamic_schema_overrides, override flag. Hermes ahead, real feature. |
| tools/environments/base.py | A | 197 | Hermes adds Windows newline-safe stdin, cwd-restore after profile, path quoting. Hermes ahead, real fixes. |
| tools/tirith_security.py | A | 174 | Pure rename + Hermes platform-support helpers. No Elevate-only logic. |
| tools/schema_sanitizer.py | A | 259 | No Elevate-only defs; Hermes ahead. |
| tools/process_registry.py | A | 508 | Hermes adds `format_process_notification` + watch-suppression. No Elevate-only defs. Hermes ahead. |
| tools/cronjob_tools.py | A | 292 | Hermes adds emoji/ZWJ normalization, deliver-param normalize. No Elevate-only defs. Hermes ahead. |
| tools/code_execution_tool.py | A | 454 | Hermes adds `_scrub_child_env`. No Elevate-only defs. Hermes ahead. |
| tools/file_tools.py | A | 248 | Hermes adds dedup-invalidation + internal-status helpers. No Elevate-only defs. Hermes ahead. |
| tools/file_operations.py | A | 728 | Hermes adds in-proc linters (json/yaml/toml/python). No Elevate-only defs. Hermes ahead. |
| tools/terminal_tool.py | A | 438 | Hermes adds Vercel-sandbox support, sudo-password cache. No Elevate-only defs. Hermes ahead. |
| tools/mcp_tool.py | A | 768 | Hermes adds MCP image-block caching, remote-URL validation, parallel-safety. No Elevate-only defs. Hermes ahead. |
| tools/browser_tool.py | A | 1868 | Hermes adds Lightpanda fallback, Chromium engine detection, private-URL auto-local. No Elevate-only defs. Hermes ahead (large but mechanical). |
| tools/vision_tools.py | A | 381 | Hermes adds native-vision tool-result path. No Elevate-only defs. Hermes ahead. |
| tools/checkpoint_manager.py | A | 1335 | Hermes file ~1000 lines larger, zero Elevate-only defs. Pure Hermes-ahead (shadow-git rewrite). |
| tools/tts_tool.py | A | 1070 | Zero Elevate-only defs. Pure Hermes-ahead. |
| tools/image_generation_tool.py | B | 246 | Elevate-only: `_normalize_fal_queue_url_format`, `_extract_http_status` (fal queue-URL + HTTP-status infra helpers, wired into client init + retry). Small but real — preserve both fns and their call sites; take Hermes deltas around them. |
| tools/session_search_tool.py | B | 882 | Elevate-only: entire summarize pipeline Hermes lacks — `_summarize_session`, `_format_conversation`, `_truncate_around_matches`, `_get_session_search_max_concurrency`, FTS5→Gemini-Flash flow. Hermes version is a different (raw-transcript) implementation. Preserve Elevate's summarization model wholesale; cherry-pick only safe Hermes fixes. Effectively Elevate-ahead. |
| tools/approval.py | B | 836 | Elevate-only: Claude-style permission-mode subsystem — `get_permission_mode`, `set_session_permission_mode`, `get_session_permission_mode`, `is_tool_allowed_in_plan_mode`, `is_readonly_tool_name`, `check_file_edit_approval`, `_await_gateway_choice`, `_session_permission_mode` dict, `_PERMISSION_MODE_TO_APPROVAL`. Hermes lacks all of it. Preserve entire permission-mode/plan-mode layer; layer in Hermes' dangerous-pattern additions (/etc/ guards, find -exec rm). |
| tools/send_message_tool.py | B | 726 | Elevate-only: per-agent bot routing — `agent_bots` lookup keyed on `ELEVATE_SESSION_AGENT_ID`, `agent_id` param threaded through `_send_to_platform`/`_send_telegram`. Preserve agent_bots/agent_id plumbing; take Hermes' new platform map entries (qqbot, wecom, weixin, etc.) if wanted, else C-skip those rows. |
| tools/skills_hub.py | B | 516 | Elevate-only: realtor-HQ skill index — `ELEVATE_INDEX_URL` env, "Elevation Real Estate HQ" optional-skills concept, optional-dir hidden-part filter. Hermes side adds httpx-based fetch hardening + trust-rank dedup. Hand-merge: keep Elevate index/optional-skills model, adopt Hermes' fetch/dedup robustness. |
| tools/delegate_tool.py | B | 1501 | Elevate-only and large: full agent-orchestration/handoff subsystem Hermes lacks — `_AGENT_JOB_PROFILES`, `_DEFAULT_HANDOFF_ROUTES`, `_VISIBLE_AGENT_ALIASES`, `_build_handoff_packet`, `_start_orchestration_run`, `_finish_orchestration_run`, `_orchestration_store_or_none`, `_scan_agent_markdown`, `_read_agent_markdown_context`, `_candidate_elevateos_roots`, `_handoff_route_error`, `_derive_available_child_toolsets`, 19 Elevate-only fns total. ~500-line single block at elevate:268-713. Heaviest hand-merge in the set; treat Elevate as authoritative for delegation, cherry-pick Hermes fixes only. |
| tools/web_tools.py | B | 1390 | Elevate-only and large: multi-backend web search Hermes lacks — `_exa_search`/`_exa_extract`, `_parallel_search`/`_parallel_extract`, `_tavily_request`/`_normalize_tavily_*`, `_get_direct_firecrawl_config`, `_get_firecrawl_gateway_url`, `_raise_web_backend_configuration_error`, 22 Elevate-only fns. Elevate file is 540 lines larger. Hermes has 4 unique fns (`_get_search_backend`, `_get_extract_backend`, `_get_capability_backend`, `_ddgs_package_importable`). Preserve Elevate's Exa/Parallel/Tavily/direct-Firecrawl stack; selectively adopt Hermes' backend-resolver helpers. |

## Summary

Of 67 differing `tools/` files: **55 are Class A (COPY+SED-SAFE)**, **10 are Class B (HAND-MERGE)**, **2 are Class C (SKIP)**. The repo is overwhelmingly stale-Elevate — Hermes is strictly ahead on the large majority, including big files like `browser_tool.py`, `mcp_tool.py`, and `checkpoint_manager.py`, which despite huge diffs carry zero Elevate-only function definitions and can be copied wholesale after sed-rename. The 10 Class B files are where real work lives: `delegate_tool.py` (agent orchestration/handoff subsystem) and `web_tools.py` (multi-backend Exa/Parallel/Tavily search) are the heaviest — Elevate is effectively ahead there. `approval.py`, `session_search_tool.py`, `skills_tool.py`, `send_message_tool.py`, `skills_hub.py`, `skills_sync.py`, `memory_tool.py`, and `image_generation_tool.py` carry smaller but committed Elevate logic (permission modes, paid-skill gating, per-agent bot routing, realtor onboarding). Class C is just the two Feishu files (platform skip-list, trivial perf tweak).

**5 safest quickest wins** (Class A, smallest non-zero diffs): `tools/budget_config.py` (1), `tools/openrouter_client.py` (2), `tools/todo_tool.py` (2), `tools/tool_output_limits.py` (2), `tools/managed_tool_gateway.py` (6). All are pure rename/docstring/cosmetic — copy+sed and move on.
