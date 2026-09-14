# EPIC — Self-updating property scorecards (harness-driven) + full-capability EA

> **Outcome:** Every property card's scorecard stays current as the agent works
> the deal, *without depending on the LLM remembering to call a tool*. The
> Executive Assistant can perform any specialist action itself and **chooses**
> to delegate. Skyleigh can review a live scorecard on the card before each task.
>
> **Principle:** LLM supplies judgment; the **harness** supplies the bookkeeping.
> Push every update we can from "model must remember to call `set_checklist`" →
> "harness applies it as a deterministic side-effect of work the model already did."

## Root cause (why "it keeps not updating")
1. **EA can't write deals.** EA toolset (`agent_hub.py:226`) has `deals_overview`
   (read) + `lead_status` (lead write) but **no `admin_deal`**. Deal writes are
   deliberately scoped to the Admin specialist (`tools_config.py:74-78`) and only
   reached via delegation — which is flaky. Leads update from chat; deals don't.
2. **In-session work auto-ticks nothing.** Deterministic auto-tick fires on
   *artifacts* (`_ARTIFACT_CHECKLIST_HINTS`, `deals.py:2098`) and *runs*
   (`record_run_result`, `deals.py:2190`). Chat work (drafting a counter,
   gathering a CMA price, confirming a date) produces neither → falls through to
   the LLM voluntarily calling `set_checklist`, which it skips.
3. **Cards don't show live progress.** Card `progress` is only on mock seed data
   (`admin-data.ts`); real API deals carry no computed progress
   (`admin-board.tsx:222`), so the scorecard is invisible until the modal opens.

## What the harness ALREADY does (build on this, don't rebuild)
- Tick a cell → stage auto-advances (`_maybe_advance_from_workflow_signal`,
  `deals.py:1257`; `_WORKFLOW_STAGE_COMPLETE_ADVANCES_TO`, `:96`).
- Gate clears → auto-advance (`_maybe_auto_advance_from_gate`, `:1346`).
- Attach a file → cell ticks itself (`_ARTIFACT_CHECKLIST_HINTS`).
- Run finishes → checklist + advance (`record_run_result`).
- Post-turn entity attribution stamps freshness (`turn_attribution.py`) — but does
  **not** tick cells. The board-sync nudge only *reminds* the model.

## Acceptance (epic-level)
- Skyleigh works a deal in main chat; the scorecard reflects it **without** her
  re-asking, whether or not the LLM called a write tool.
- The card shows live X/Y progress + gate status before the modal is opened.
- EA can do any specialist write directly; delegation is a preference, not a wall.
- No regression to the existing artifact/run/gate auto-advance paths.

---

# ISSUE 1 — EA full-capability toolset (union + delegation-by-choice)
**Goal:** EA can call everything any specialist can; delegation becomes a behavioral choice.
**Files:** `elevate_cli/agent_hub.py`, `elevate_cli/default_soul.py`, `elevate_cli/tools_config.py`
**Size:** S–M · **Depends on:** none (contained win, ship first)

- **1.1** Compute EA's toolset as the **union of all agents' toolsets** at seed/load
  (not a hand-maintained list) so it never drifts when a specialist gains a tool.
- **1.2** Verify the enlarged tool schema stays **cache-stable** (tool-schema drift
  busts the prompt cache — see harness-efficiency rule). Snapshot tools[] hash.
- **1.3** `default_soul.py`: reframe delegation as a **preference** — "you can do
  specialist work directly, especially quick single writes like ticking a
  scorecard cell; route heavy or parallel specialist work."
- **1.4** Confirm entitlement passthrough: `admin_deal` present in EA but returns a
  clean `requires_entitlement` on non-real-estate accounts (no crash, no upgrade-spam).
- **1.5** Tests: EA invokes `admin_deal` directly end-to-end; non-RE account gets
  `requires_entitlement`; tools[] hash unchanged across identical sessions.

# ISSUE 2 — Deterministic side-effect auto-tick (Layer 1, no LLM)
**Goal:** A successful mapped tool/skill ticks its checklist cell with zero model judgment.
**Files:** `elevate_cli/data/deals.py`, `agent/tool_executor.py`, run-result path
**Size:** M · **Depends on:** none (parallel to Issue 1)

- **2.1** Add a **tool/skill-completion → checklist-cell** map (the `_ARTIFACT_CHECKLIST_HINTS`
  idea, keyed on tool/skill id instead of artifact kind). e.g. marketing-render →
  `workflow_feature_sheet_uploaded`, mlc-send → `workflow_stage_2_complete`.
- **2.2** Hook the map at tool-success so it calls `set_deal_toggle(actor="agent:...")`.
  Reuse the existing toggle path so gate auto-advance fires for free.
- **2.3** **deal_id resolution for in-session tools** — pull the active deal from
  session/turn context so the tick lands on the right card (shared resolver w/ Issue 3).
- **2.4** Verify ticking through this path triggers `_maybe_auto_advance_from_gate`
  (no new advance logic).
- **2.5** Tests: running mapped skill X ticks cell Y; ticking the last required cell advances the stage.

# ISSUE 3 — Constrained post-turn scorecard inference (Layer 2, cheap structured call)
**Goal:** Conversational work that maps to no tool still updates the scorecard — harness always runs it, model can't forget.
**Files:** `agent/turn_attribution.py` (extend), `run_agent.py` injection seam, `elevate_cli/data/deals.py`
**Size:** L · **Depends on:** Issue 2's deal_id resolver · **This is the one that actually kills "it keeps not updating."**

- **3.1** Post-turn resolver: input = finished turn + **this deal's currently-open
  cells for the current stage only**; output = **schema-locked subset** of those
  cells now satisfied (closed set, high confidence bar — can't invent progress).
- **3.2** Run **off-thread** so it never delays the response (reuse the micro-resolver
  plumbing already built for entity attribution).
- **3.3** Confidence gating + AI-stamp toggles; **respect operator precedence**
  (never override a hand-set cell — same rule as `lead_status`).
- **3.4** Reuse the attribution deal_id resolution (explicit id → entity-index fuzzy
  → session-sticky) so it targets the right deal.
- **3.5** Config flag + **token-budget guard**; decide default on/off (recommend
  on for entitled RE accounts).
- **3.6** Tests: a chat turn that nails the CMA price ticks the pre-cma cell; an
  ambiguous/research turn ticks nothing.

# ISSUE 4 — Board-sync nudge demoted to fallback (Layer 3)
**Goal:** The nudge only fires for the low-confidence remainder L1+L2 couldn't resolve.
**Files:** `agent/turn_attribution.py`
**Size:** S · **Depends on:** Issues 2 & 3

- **4.1** Fire the nudge only when the last turn worked a deal AND open cells remain
  that L1/L2 didn't auto-resolve.
- **4.2** Keep stateless re-derivation; suppress double-prompting once L2 has acted.
- **4.3** Tests: nudge suppressed when L2 already ticked the cell.

# ISSUE 5 — Property card UI: live scorecard ("fix the cards")
**Goal:** The card shows live X/Y progress + gate status before the modal opens.
**Files:** `web/src/pages/real-estate-hub/admin/{components/admin-board.tsx,admin-data.ts,use-admin-deals.ts,use-admin-events.ts,components/deal-modal.tsx}`, server deal API
**Size:** M · **Depends on:** none (parallel; UI lane)

- **5.1** Server computes **per-deal checklist progress** (X/Y for current stage) +
  gate status and returns it on `AdminDeal`. (Today the card's `progress` only
  exists on mock seed data — confirm + close the gap.)
- **5.2** `DealCard` renders live progress + gate state (can-advance / blocked /
  missing items) **without** opening the modal.
- **5.3** Real-time: card reflects toggle changes via `use-admin-events` board-sync,
  not just on modal close.
- **5.4** `deal-modal` scorecard-review view: per-stage checklist + "what's missing
  to advance" reads as the reviewable scorecard Skyleigh checks before each task.
- **5.5** Remove/replace stale hardcoded `progress` seed values so real cards show real data.

# ISSUE 6 — Scorecard write coverage / ergonomics
**Goal:** Close the gaps that make the agent tick one cell and stop.
**Files:** `tools/admin_deal_tool.py`, `elevate_cli/data/deals.py`
**Size:** S · **Depends on:** none

- **6.1** **Bulk `set_checklist`** — accept multiple cells in one `admin_deal` call
  (today it's one-per-call → a short loop ticks one and quits).
- **6.2** Audit the `set_fields` whitelist (`_DEAL_DETAIL_FIELDS`, `deals.py:1450`)
  for any scorecard field Skyleigh needs that isn't currently writable.
- **6.3** Tests.

# ISSUE 7 — Telemetry + end-to-end verification
**Goal:** Prove the harness actually carried the update, and surface drift.
**Files:** `agent/turn_attribution.py`, deal event log, a small report
**Size:** S–M · **Depends on:** Issues 2–4

- **7.1** Stamp each tick's **source**: deterministic (L1) / inferred (L2) / LLM (L3) / human.
- **7.2** "Scorecard freshness" check: cells satisfied-by-reality vs ticked → surface drift.
- **7.3** Dogfood end-to-end on a test deal (and Skyleigh's box) — work a deal in
  chat, confirm the scorecard advances without re-asking.

---

## Suggested sequencing
1. **Ship first (parallel, low risk):** Issue 1 (EA union), Issue 6 (bulk write), Issue 5 (UI cards).
2. **Core harness lift:** Issue 2 (L1 deterministic), then Issue 3 (L2 inference — the real fix).
3. **Then:** Issue 4 (nudge → fallback), Issue 7 (telemetry + dogfood).

## Open decisions (Dartagnan)
- L2 default **on** for entitled RE accounts, or opt-in? (Recommend on.)
- EA toolset union — full union, or union minus a small denylist (e.g. raw
  `elevate_db` writes) to keep the base chat tighter on tokens?
