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
  - [ ] B3d big platform adapters: telegram, discord, slack, api_server,
        matrix, signal, whatsapp, email, mattermost
  - [ ] B3e gateway/run.py (12.7k->18.2k lines, has Elevate-only divergence -
        hand-port hunk by hunk, B2-caliber risk)
- [ ] B4 elevate_cli/ deltas + new files
- [ ] B5 tools/ deltas + new files
- [ ] B6 providers/ + plugins/model-providers/
- [ ] B7 skills / optional-skills (filtered)
- [ ] B8 tests sweep

## Notes
- Elevate runs live for Skyleigh. Never push a batch that fails tests.
- `is_truthy_value` exists in `cli/utils.py` - dependency confirmed.
- PRE-EXISTING: 29 gateway-test failures on committed HEAD (baseline before
  any port). Root causes: `NameError: name 'event' is not defined` at
  gateway/run.py:11468, and an api_server.py toolset bug. NOT port
  regressions. The B3e run.py hand-port should resolve the run.py one.
- venv: use `cli/.venv/bin/python` (pytest 9.0.2). NOT `cli/venv/`.
