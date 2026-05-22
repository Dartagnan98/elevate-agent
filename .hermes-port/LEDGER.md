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
- [ ] B1 Security fixes
  - [x] tools/url_safety.py        (SSRF IPv4-mapped IPv6 + is_always_blocked_url) - 112 tests pass
  - [ ] gateway HMAC webhook secret validation
  - [ ] gateway/pairing.py         (hash pairing codes)
  - [ ] control-plane file write-deny
  - [ ] API key leak to non-authoritative endpoints
- [ ] B2 agent/ package (run_agent.py refactor) - HIGHEST RISK, do last/carefully
- [ ] B3 gateway/ non-security deltas
- [ ] B4 elevate_cli/ deltas + new files
- [ ] B5 tools/ deltas + new files
- [ ] B6 providers/ + plugins/model-providers/
- [ ] B7 skills / optional-skills (filtered)
- [ ] B8 tests sweep

## Notes
- Elevate runs live for Skyleigh. Never push a batch that fails tests.
- `is_truthy_value` exists in `cli/utils.py` - dependency confirmed.
