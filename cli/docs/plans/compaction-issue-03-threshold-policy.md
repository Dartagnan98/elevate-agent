# Issue 3 - Threshold policy

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: detailed build plan, not implemented

## Problem

Compaction still looks random because several threshold concepts are visible in
different places:

- old config defaults and tips still mention 50 percent
- config migration bumps stale `0.50` values to `0.85`
- estimate-mode full compaction uses 85 percent
- real-count mode can raise the default full-compaction line to 90 percent
- critical overflow protection uses 95 percent
- prune-only maintenance can happen earlier than full compaction
- the UI displays context left, while backend thresholds are context used

The result is product confusion: a user sees "49 percent" or "29 percent" and
cannot tell whether that means context left, context used, prune-only cleanup,
legacy recovery, or full summary compaction.

## Current behavior

Verified source state:

- `cli/agent/context_compressor.py` constructs the compressor with
  `threshold_percent=0.85` and explains why 95 percent is too late for the
  normal trigger.
- `cli/agent/conversation_compression.py` defines
  `ESTIMATE_MODE_THRESHOLD = 0.85`, `REAL_COUNT_MODE_THRESHOLD = 0.90`, and
  `CRITICAL_THRESHOLD = 0.95`.
- `resolve_compression_pressure(...)` prefers real-count projection, then the
  post-compaction `-1` sentinel, then stored prompt tokens, then rough estimate.
- `effective_compression_trigger_tokens(...)` raises the untouched 0.85 default
  to 0.90 only in real-count mode and only when `threshold_pinned` is false.
- `cli/run_agent.py` currently marks `self._compression_threshold_pinned` true
  whenever `compression.threshold` exists in config.
- `cli/elevate_cli/config.py` still has the default template at
  `compression.threshold: 0.50`.
- `cli/elevate_cli/config.py` migration version 25 rewrites exact old
  `0.50` configs to `0.85`.
- `cli/elevate_cli/tips.py` still says the default threshold is 50 percent.
- `cli/elevate_cli/config.py` status output prints
  `compression.get('threshold', 0.50)`.
- `cli/gateway/run.py` now treats its 0.85 line as diagnostic only and only
  runs pre-agent hygiene for critical 95 percent overflow or raw legacy floods.

Important gotcha:

Because the default config writes a `compression.threshold` key, the agent can
treat the platform default as user-pinned. That prevents the real-count path
from rising from 85 percent to 90 percent, even when the user did not actually
choose 85 percent.

## Desired behavior

Use one documented threshold ladder:

| Stage | Effective context used | User-visible? | Owner |
| --- | ---: | --- | --- |
| soft prune | around 72 percent used, only when useful | no | `ContextCompressor` |
| estimate-mode full compaction | 85 percent used | quiet/pending only if blocking | `AIAgent` |
| real-count full compaction | 90 percent used | quiet/pending only if blocking | `AIAgent` |
| critical compaction | 95 percent used | visible only as delay/recovery if needed | `AIAgent`/gateway overflow |
| legacy raw-message recovery | raw transcript flood with no cursor | visible only if recovery fails or delays badly | gateway |
| manual `/compact` | user command | yes | TUI gateway |

Do not make normal full compaction wait for 95 percent. That line is an
emergency guard. Normal compaction needs headroom for:

- next-turn model output
- summary generation output
- tool schema/provider overhead variance
- rough-estimate error
- one more tool-heavy iteration before the next boundary check

## Files / seams

Primary:

- `cli/run_agent.py`
- `cli/agent/conversation_compression.py`
- `cli/agent/context_compressor.py`
- `cli/elevate_cli/config.py`
- `cli/elevate_cli/tips.py`
- `cli/gateway/run.py`

Tests:

- `cli/tests/agent/test_real_count_trigger.py`
- `cli/tests/run_agent/test_compaction_payload_seam.py`
- `cli/tests/gateway/test_session_hygiene.py`
- `cli/tests/gateway/test_hygiene_noop_guard.py`
- add or update a focused config migration/default test if one already exists

Frontend dependency:

- `cli/web/src/pages/ChatPage.tsx` is Issue 4, not this issue, except for
  labels that must match the policy.

## Implementation steps

1. Make the default config truthful.

   In `cli/elevate_cli/config.py`:

   - change the default template from `compression.threshold: 0.50` to `0.85`
   - update the comment to say estimate-mode default, not universal default
   - change status fallback from `0.50` to `0.85`
   - keep the version 25 migration for exact old `0.50` configs

2. Fix stale user-facing copy.

   In `cli/elevate_cli/tips.py`, replace the 50 percent tip with concise copy:

   ```text
   Auto-compaction starts around 85-90% context used; /compact runs it manually.
   ```

   Do not mention prune-only in random tips.

3. Stop treating the platform default as a user pin.

   Minimal rule:

   - missing threshold: unpinned
   - threshold exactly `0.85`: unpinned platform default
   - any other threshold: user-pinned

   This preserves custom values while allowing real-count mode to use the
   documented 90 percent default. It does mean a user cannot explicitly pin
   exactly 0.85 without choosing a nearby value; acceptable unless customer
   feedback proves otherwise.

   Keep this as a private helper near the existing compression config read in
   `cli/run_agent.py`; do not add a config schema or DB migration for a
   `threshold_pinned` flag unless tests prove the ambiguity matters.

4. Keep aux auto-lowering stronger than policy.

   The auxiliary summarizer feasibility code can lower a live session threshold
   when the summary model cannot fit the main threshold. That is a safety
   override, not normal policy. Tests must still show an auto-lowered threshold
   does not get bumped back to 90 percent.

5. Preserve gateway ownership boundaries.

   Gateway should keep logging the normal 85 percent line as diagnostic, but
   only pre-agent recover at critical 95 percent or legacy raw-message flood.
   Do not reintroduce ordinary 85 percent gateway compaction.

6. Document the policy in the epic and any release note.

   Use "context used" for thresholds and "context left" only for the UI ring
   if Issue 4 keeps that convention.

## Tests

Run or add focused tests:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/agent/test_real_count_trigger.py \
  cli/tests/run_agent/test_compaction_payload_seam.py \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py -q
```

Required assertions:

- default `compression.threshold: 0.85` is treated as unpinned
- real-count mode with default threshold triggers at 90 percent or reserve line
- estimate mode with default threshold triggers at 85 percent
- custom threshold values still pin and win
- auto-lowered aux threshold still wins
- gateway normal-pressure case logs/delegates, not pre-agent compacts
- critical 95 percent case still pre-agent recovers when needed
- stale 50 percent copy is gone from tips/status/default config

## Installed app verification

After source tests pass:

1. Patch the installed CLI files under:

   ```text
   /Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/
   ```

2. Restart the installed app and gateway.

3. In the real desktop app, run one short smoke to verify the app still answers.

4. In logs, verify a normal resumed compacted session below the effective
   trigger does not pre-agent compact in gateway hygiene.

5. If possible, run one provider-stubbed or temporary-home threshold smoke for:

   - estimate-mode near 85 percent
   - real-count near 90 percent
   - critical near 95 percent

Do not rely on localhost-only verification for release confidence.

## Acceptance criteria

- New/default configs no longer claim 50 percent compression.
- Tips and config status no longer claim 50 percent compression.
- The source policy is documented as 85 estimate, 90 real-count, 95 critical.
- Default `0.85` no longer accidentally disables the real-count 90 percent
  path by looking user-pinned.
- Custom non-default thresholds still pin and win.
- Gateway does not become a normal threshold owner again.
- A future report of "it compacted at 49%" can be interpreted as either
  "49 percent left / 51 percent used" or explained by event logs, not guessed.

## Risks / rollback

- Risk: treating exact `0.85` as unpinned changes behavior for a power user who
  explicitly chose 85 percent. Mitigation: any non-default value still pins; add
  a real `threshold_pinned` config only if that distinction becomes necessary.
- Risk: raising real-count default to 90 percent exposes more overflow on
  tool-heavy turns. Mitigation: output reserve and critical 95 percent path
  stay in place; estimate mode remains 85 percent.
- Risk: status/tips copy drifts again. Mitigation: add a small test or grep
  check for the stale 50 percent tip.
