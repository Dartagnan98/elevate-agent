# Implementation Plan — Self-updating property scorecards (harness-driven)

> Full build plan for the epic in `admin-hub-scorecard-self-update-epic.md`.
> Issue IDs (I1–I7) map 1:1 to that doc. This doc is the **how**, with exact seams.

## The fix in one line
Stop depending on the LLM to call `set_checklist`. Make the **harness** reflect
scorecard progress as a deterministic side-effect of work the model already did,
fall back to a **constrained, always-runs** post-turn inference for chat-only
work, and only nudge the model for the genuine remainder. Give the EA the write
tools so it can act in the main chat instead of relying on flaky delegation. Make
the card show the live scorecard.

## Root cause recap
1. EA toolset (`agent_hub.py:226`) has read-only deal visibility, no `admin_deal`.
2. In-session chat work produces no artifact/run, so the deterministic auto-tick
   (`_ARTIFACT_CHECKLIST_HINTS` `deals.py:2098`, `record_run_result` `:2190`) never fires.
3. Card `progress` only exists on mock seed data; real `/api/admin/deals` rows have none.

---

## PHASE A — Contained wins (parallel, low risk, ship first)

### I1 — EA full-capability toolset (computed union)
**Seam:** `elevate_cli/agent_hub.py` — `DEFAULT_AGENTS` list (EA entry line 226).
Toolsets seed into the hub DB via `upsert_hub_agent` + `_merge_agent_list_field(raw,"toolsets",…)` (~`:1791`); the agent later reads `enabled_toolsets`.

**Change:**
1. After `DEFAULT_AGENTS` is defined, compute `EA_TOOLSET_UNION = sorted(set().union(*(a["toolsets"] for a in DEFAULT_AGENTS)) - DENY)` where `DENY` is a small, explicit denylist (start empty; candidate: raw `elevate_db` if base-chat token budget bites). Assign it to the EA entry so EA is always a superset and never drifts.
2. `default_soul.py` — reframe delegation as a **preference, not a wall**: "You can perform any specialist action directly — especially quick single writes like ticking a scorecard cell. Delegate when the work is heavy, parallel, or genuinely a specialist's deep craft."
3. Confirm `admin_deal` entitlement passthrough already returns clean `requires_entitlement` (it does — `admin_deal_tool.py:57`); no change, just a test.

**Acceptance:** EA invokes `admin_deal` directly end-to-end; tools[] schema hash stable across two identical EA sessions; non-RE account gets `requires_entitlement`, not a crash.

### I6 — Write ergonomics
**Seam:** `tools/admin_deal_tool.py` (`set_checklist` `:98`), `elevate_cli/data/deals.py` (`set_deal_fields` whitelist `_DEAL_DETAIL_FIELDS` `:1450`).

**Change:**
1. `set_checklist` accepts either `field`+`value` (today) **or** a `cells: {id: bool}` map → loop `set_deal_toggle` in one call. Kills "ticks one cell and stops."
2. Audit `_DEAL_DETAIL_FIELDS` vs the stages' required fields; add any scorecard field that a gate requires but `set_fields` can't currently write.

**Acceptance:** one `admin_deal set_checklist {cells:{…}}` call ticks N cells and fires gate auto-advance once.

### I5 — Property card UI: live scorecard
**Seam:** server `GET /api/admin/deals` (`web_server.py:7052`, `get_admin_deals` → `list_deals`); `AdminDeal` response model (`web_server.py:5566`); UI `web/src/pages/real-estate-hub/admin/{components/admin-board.tsx (DealCard ~185), admin-data.ts, use-admin-deals.ts, use-admin-events.ts, components/deal-modal.tsx}`.

**Change:**
1. In `get_admin_deals`, compute per-deal `progress` (X/Y satisfied cells for the
   current stage) + `gate` (canAdvance / missing[]) from `get_deal_context`, and
   add them to the `AdminDeal` model. (This is the field the card already wants —
   `admin-board.tsx:222` renders `deal.progress` but real rows never carry it.)
2. `DealCard` renders progress + gate state (blocked / can-advance / N missing)
   without opening the modal.
3. Card refreshes on toggle via `use-admin-events` board-sync, not just modal close.
4. `deal-modal` per-stage checklist already shows X/Y (`deal-modal.tsx:705`) — add a
   "what's missing to advance" line so it reads as the reviewable scorecard.
5. Delete the hardcoded `progress` seed values in `admin-data.ts` so real data shows.

**Acceptance:** a card shows live `3/5` + "1 to advance" before any click; flipping a cell updates the card without reopening it.

---

## PHASE B — Core harness lift (the actual fix)

### I2 — Deterministic side-effect auto-tick (Layer 1, no LLM)
**Seam:** `agent/tool_executor.py` — `execute_tool_calls_concurrent` (`:74`) and
`execute_tool_calls_sequential` (`:481`), right after `function_result` is produced
and the result message is appended (~`:430–455`). The tool `name` + success state
are in hand there.

**Change:**
1. New map `TOOL_COMPLETION_CHECKLIST_HINTS` (sibling to `_ARTIFACT_CHECKLIST_HINTS`)
   keyed on tool/skill id → checklist cell. e.g. marketing-render →
   `workflow_feature_sheet_uploaded`, mlc-send → `workflow_stage_2_complete`.
2. Post-tool hook: on a mapped tool's **success**, resolve the active `deal_id`
   from session/turn context (shared resolver, below) and call
   `set_deal_toggle(actor="agent:tool:<name>")`. Reuse the existing toggle path so
   `_maybe_auto_advance_from_gate` (`deals.py:1346`) fires for free — no new advance logic.
3. **Shared deal_id resolver** (`agent/deal_context.py`, new): explicit deal_id in
   tool args → session-pinned deal → entity-index fuzzy match. Used by I2 and I3.

**Acceptance:** running a mapped skill ticks its cell; ticking the last required cell advances the stage; nothing ticks when no deal is in context.

### I3 — Constrained post-turn inference (Layer 2) — kills "it keeps not updating"
**Seam:** `agent/turn_attribution.py` (extend, next to `resolve_attributions` `:202`)
+ the post-turn hook in `run_agent.py` where attribution already runs off-thread.

**Change:**
1. `resolve_satisfied_cells(messages, deal_id)`: gather the deal's **currently-open
   cells for the current stage only** (from `get_deal_context`), then a single
   **schema-locked** aux call returns the subset of *those exact cells* now
   satisfied by the finished turn. Closed set → can't invent cells; high bar.
2. Run **off-thread** (reuse the micro-resolver plumbing) so it never delays the response.
3. Apply via `set_deal_toggle(actor="agent:inferred")`; **respect operator
   precedence** (never override a hand-set cell — same rule `lead_status` uses).
4. deal_id via the shared resolver from I2.
5. Config: `auto_scorecard_inference` flag + token-budget guard. Default **on** for
   entitled RE accounts.

**Acceptance:** a chat turn that nails the CMA price ticks the pre-cma cell with no
tool call; a research/ambiguous turn ticks nothing; runs every turn regardless of
whether the model "remembered."

### I4 — Nudge demoted to fallback (Layer 3)
**Seam:** `agent/turn_attribution.py` — the `n()` / `build_turn_nudge` (`:344`) path
wired into run_agent's pre-turn injection.

**Change:** fire the nudge only when the last turn worked a deal AND open cells
remain that L1+L2 did **not** resolve. Suppress double-prompting once L2 has acted.

**Acceptance:** nudge text is absent when L2 already ticked the cell; present only for the genuine remainder.

---

## PHASE C — Prove it carried

### I7 — Telemetry + e2e
**Seam:** `agent/turn_attribution.py`, the deal event log (`_insert_deal_event`).

**Change:**
1. Stamp every tick's **source** on the deal event: `deterministic` (L1) /
   `inferred` (L2) / `llm` (L3) / `human`.
2. Scorecard-freshness check: compare cells satisfied-by-reality vs ticked; surface drift.
3. Dogfood: work a deal in chat on a test account (and Skyleigh's box); confirm the
   scorecard advances with no re-asking.

---

## Sequencing
- **Phase A** (I1, I5, I6) — independent, ship in parallel.
- **Phase B** — I2 first (gives the shared deal_id resolver), then I3 (depends on it), then I4.
- **Phase C** — I7 after B lands.

## Risks & mitigations
- **Bigger EA tool schema → tokens + cache.** Mitigate with the I1 denylist knob and a tools[]-hash stability test.
- **L2 false-ticks.** Closed-set schema + high confidence bar + operator-precedence guard + L1 telemetry source-stamp so drift is visible.
- **Wrong-deal attribution.** Single shared resolver (I2) with the same ≥0.7 floor as entity attribution; never act on an unresolved deal.
- **Regression to existing auto-advance.** I2/I3 write through the *existing* `set_deal_toggle`/gate path; no parallel advance logic.

## Open decisions (Dartagnan)
1. L2 default **on** for entitled RE accounts vs opt-in? (Rec: on.)
2. EA union — full, or full-minus-`elevate_db`-writes to keep base chat tighter?
