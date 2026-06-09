# Agent Consolidation Plan (2026-06-09)

Goal: one native agent (**Executive Assistant**), everything else **installable**, all of it
**bundled so it ships to customers**, and the existing agents **beefed up** with cherry-picked
material from `msitarzewski/agency-agents` (MIT) — consolidating into what we already have, not
sprawling into dozens of new agents.

## Current state (two parallel agent systems)

1. **Native agents** — defined *in code*, `cli/elevate_cli/agent_hub.py` `_native_agent_config()`,
   always-on, what customers see under "Access". Eight of them:
   `executive-assistant` (the lead — already holds `orchestration`/`approvals`/`fleet` scopes and is
   every other agent's escalation target), `admin`, `outreach`, `ads`, `marketing`, `social-media`,
   `analyst`, `theta-wave`.
2. **Installable packs** — *file-based*, `~/cortextos/community/agents/<id>/` (orchestrator, analyst,
   security, agentic-crm-assistant, research-agent, worker). Rich: 9 files each (IDENTITY, SOUL,
   GUARDRAILS, HEARTBEAT, ONBOARDING, TOOLS, AGENTS, CLAUDE, config.json); orchestrator ≈ 1,700 lines.

### THE blocker (why nothing installs on customer boxes)
`_cortext_root()` (`agent_hub.py:161`) only resolves packs from `CORTEXTOS_ROOT`, `~/cortextos`, or a
**hardcoded `/Users/dartagnanpatricio/cortextos`**. None exist on a customer box → root `None` →
"CortextOS presets were not found." The pack *content was never bundled into the app.* Until fixed,
no installable agent and no theta-wave can reach any customer, regardless of anything else here.

## Target model

- **Executive Assistant** = the sole native, always-on agent. It already is the orchestrator (lead).
  Enrich it with the file-based `orchestrator` pack's depth. "Orchestrator" name retired → EA.
- **Everything else installable**: admin, outreach, ads, marketing, social-media, analyst (+ the
  generic packs: crm, research, security, worker). Seeded opt-in/off; user installs what they want.
- **theta-wave** stays a system-level reviewer tied to EA (not a user-facing installable persona).
- All pack content **bundled into the app** (`cli/`), so `_cortext_root()` finds a shipped presets
  dir first and the hardcoded dev path is removed.

## Workstreams

### A. Ship fix (the unblocker — required no matter what)
- Bundle the pack source (the `community/agents/*` + `community/skills/theta-wave` content the packs
  read) into the app under `cli/` (e.g. `cli/elevate_cli/agent_presets/`).
- `_cortext_root()`: resolve the bundled dir first; keep env override; **drop the hardcoded
  `/Users/dartagnanpatricio/cortextos`**.
- Verify on a clean home (no `~/cortextos`) that packs list + install.

### B. Executive Assistant (merge + keep lean)
- Confirm EA carries the full orchestrator capability (fleet-coordination, approvals, goals,
  morning/evening/weekly review loops, handoff routing). Fold the `orchestrator` pack's
  IDENTITY/SOUL/HEARTBEAT/GUARDRAILS depth into the native EA definition.
- Retire the standalone "orchestrator" as a separate installable (it = EA).

### C. Native → installable conversion
- Convert the code-defined native agents (admin, outreach, ads, marketing, social-media, analyst)
  into the file-based pack format so they live in the same installable system. EA stays native.
- **Decision to confirm:** keep them ALSO seeded-on by default for existing installs (no regression),
  but presented as installable/removable — vs. ship them off-by-default and let users add. Recommend:
  seed EA on; seed the current real-estate set on for the `real_estate_*` entitlements (no regression),
  everything else opt-in.

### D. Enrichment (the "beef up what we have" pass — cherry-pick + consolidate)
Fold material from the staged repo agents (`docs/agent-source-material/`) into EXISTING agents.
Do NOT add them as new agents. Per-agent map:

| Existing agent | Folds in (from agency-agents, MIT) | Adds |
|---|---|---|
| **Executive Assistant** | product-trend-researcher | prioritization / signal-reading depth |
| **Marketing** | marketing-content-creator, marketing-email-strategist | content + email playbooks |
| **Ads** | paid-media-ppc-strategist, paid-media-paid-social-strategist | structured paid-media process |
| **Outreach** | sales-outbound-strategist, sales-discovery-coach, sales-deal-strategist | outbound + discovery + negotiation |
| **Social Media** | marketing-content-creator | content engine |
| **Admin** (= Transaction Coordinator) | real-estate-buyer-seller (TC half), support-analytics-reporter | transaction coordination, contingency/key-date tracking, vendor coordination, closing support, reporting |
| **Analyst** | sales-pipeline-analyst, support-analytics-reporter | pipeline + reporting analytics |

### E. The repo real-estate agent (split, not standalone)
`specialized/real-estate-buyer-seller.md` (596 lines, RE-specific). Split by function:
- **Transaction-lifecycle half → Admin** (Admin *is* the Transaction Coordinator): contract/contingency
  tracking, key dates, vendor coordination, final walkthrough, closing prep, post-closing follow-up.
- **Representation half → Outreach + EA realtor context**: buyer/seller needs assessment, showing
  coordination, CMA/pricing, offer strategy and negotiation, multiple-offer scenarios.
Not stood up as its own agent.

## Phasing
1. **A — ship fix** first (unblocks customers; pure infra; safe).
2. **B — EA merge** (keystone native agent).
3. **C — native→installable conversion**.
4. **D/E — enrichment** from staged material, agent by agent.

## Staged source material
`docs/agent-source-material/` (11 files pulled from agency-agents): real-estate-buyer-seller,
marketing-content-creator, marketing-email-strategist, paid-media-{ppc,paid-social}-strategist,
sales-{deal,outbound,discovery,pipeline}-*, support-analytics-reporter, product-trend-researcher.

## Open confirmations
1. Native→installable default seeding (C decision above).
2. ~~Real-estate agent placement~~ — RESOLVED: Admin = Transaction Coordinator; split per E.
