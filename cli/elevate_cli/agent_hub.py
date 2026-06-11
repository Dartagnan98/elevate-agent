"""Local Agent Hub snapshot helpers for the Elevate dashboard.

The hub is intentionally read-only and local-first. It reflects what the
installed Elevate runtime can already see: gateway state, configured platform
connections, sessions, cron jobs, access profile, skills/toolsets, and the
holographic memory store. It never returns raw secrets.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from elevate_cli.access import PROFILE_LABELS, load_access_config
from elevate_cli.config import get_config_path, get_elevate_home, get_env_value, load_config, redact_key
from gateway.status import get_running_pid, read_runtime_status


SHARED_AGENT_SKILLS: tuple[str, ...] = (
    "tasks",
    "human-tasks",
    "comms",
    "activity-channel",
    "approvals",
    "worker-agents",
    "delegation-matrix",
    "delivery-routing",
    "guardrails-reference",
    "memory",
    "knowledge-base",
    "surface-heartbeat",
    "autoresearch",
    "cortextos-theta-wave",
    "nano-pdf",
    "powerpoint",
    "baoyu-infographic",
    "architecture-diagram",
    "photo-cleanup",
)

AGENT_ARTIFACT_SKILLS: tuple[str, ...] = (
    "nano-pdf",
    "powerpoint",
    "baoyu-infographic",
    "architecture-diagram",
    "photo-cleanup",
)

# Every agent gets the FULL usable toolset by default (unioned into each agent
# def the same way SHARED_AGENT_SKILLS is). Per the directive "all agents should
# have access to all the tools": capability (browser + computer, web/search,
# file/terminal, skills, vision/image-gen, video, tts, code execution, cron,
# delegation, comms/memory/bus) AND the data toolsets (full pipeline read +
# deal/profile writes + raw operational SQL). The run_agent loadout union
# (run_agent.py) never strips, so these survive the gateway tool-profile filter.
#
# DELIBERATELY EXCLUDED (would be wrong to ship to a real-estate agent):
#   - framework internals: moa, rl, debugging, safe (safe even contradicts
#     terminal access)
#   - platform presets, not per-agent toolsets: the elevate-* family
#   - infra integrations no realtor agent needs: homeassistant, spotify,
#     feishu_doc, feishu_drive
#
# NOTE: elevate_db (raw operational SQL) + admin_deal (writes deal files) are
# now on EVERY agent, not just Admin. They are still gated by the per-agent
# safety rules (always_ask: destructive_action / financial / data_deletion),
# but the specialist write-scope boundary is intentionally removed here.
SHARED_AGENT_TOOLSETS: tuple[str, ...] = (
    "agent_bus",
    "agent_handoff",
    "delegation",
    "memory",
    "session_search",
    "todo",
    "messaging",
    "skills",
    "clarify",
    "web",
    "search",
    "browser",
    "computer",
    "file",
    "terminal",
    "vision",
    "image_gen",
    "video",
    "tts",
    "code_execution",
    "cronjob",
    # Data toolsets — full pipeline visibility + deal/profile writes for all.
    "leads_overview",
    "deals_overview",
    "lead_status",
    "elevate_db",
    "admin_deal",
    "admin_profile",
)


_COMMON_NATIVE_RUNTIME: dict[str, Any] = {
    "runtime_type": "native",
    "timezone": "America/Vancouver",
    "context_warning_threshold": 70,
    "context_handoff_threshold": 88,
    "codex_context_cap": 160000,
}

_COMMON_SAFETY_RULES: dict[str, Any] = {
    "approval_mode": "confirm_external_send",
    "always_ask": [
        "external_send",
        "destructive_action",
        "financial",
        "legal",
        "data_deletion",
        "credential_change",
    ],
    "never_ask": ["local_read", "status_check", "summarize", "draft_only"],
}

_COMMON_LIFECYCLE: dict[str, Any] = {
    "startup_delay": 0,
    "max_session_seconds": 5400,
    "max_crashes_per_day": 3,
    "crash_window_seconds": 86400,
    "crash_window_max": 3,
    "telegram_polling": True,
}

_COMMON_ECOSYSTEM: dict[str, Any] = {
    "local_version_control": False,
    "upstream_sync": False,
    "catalog_browse": False,
    "community_publish": False,
}


def _native_agent_config(
    *,
    vibe: str,
    work_style: str,
    autonomy_rules: str,
    communication_style: str,
    day_mode: str,
    night_mode: str,
    core_truths: str,
    memory_scopes: list[str],
    lifecycle: dict[str, Any] | None = None,
    ecosystem: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    safety: dict[str, Any] | None = None,
    handoff_policy: str = "summary_only",
) -> dict[str, Any]:
    return {
        "runtime": {**copy.deepcopy(_COMMON_NATIVE_RUNTIME), **(runtime or {})},
        "safety": {**copy.deepcopy(_COMMON_SAFETY_RULES), **(safety or {})},
        "identity": {
            "vibe": vibe,
            "work_style": work_style,
        },
        "soul": {
            "autonomy_rules": autonomy_rules,
            "communication_style": communication_style,
            "day_mode": day_mode,
            "night_mode": night_mode,
            "day_mode_start": "08:00",
            "day_mode_end": "18:00",
            "core_truths": core_truths,
        },
        "lifecycle": {**copy.deepcopy(_COMMON_LIFECYCLE), **(lifecycle or {})},
        "ecosystem": {**copy.deepcopy(_COMMON_ECOSYSTEM), **(ecosystem or {})},
        "memory": {
            "mode": "agent_scoped",
            "scopes": list(memory_scopes),
            "sources": ["agent-hub-default", "elevate-native"],
            "recall_policy": "agent_scoped_recent",
            "write_policy": "append_events",
            "handoff_policy": handoff_policy,
        },
    }


DEFAULT_AGENT_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "executive-assistant",
        "name": "Executive Assistant",
        "role": "main",
        "description": "Primary Elevate assistant.",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "api_server", "webhook", "cron"],
        "skills": [
            "agent-management",
            "auto-skill",
            "cron-management",
            "env-management",
            "goal-management",
            "heartbeat",
            "surface-heartbeat",
            "morning-review",
            "evening-review",
            "weekly-review",
            "system-diagnostics",
            "oauth-rotation",
            "onboarding",
            "delegation-matrix",
            "approvals",
            "human-tasks",
            "event-logging",
            "comms",
            "tasks",
            "knowledge-base",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo", "skills", "deals_overview", "leads_overview", "lead_status"],
        "prompt": (
            "You are the Executive Assistant — the orchestrator and default agent for this Elevate "
            "workspace. You coordinate the fleet; you do not do specialist work yourself. Route every "
            "user directive to the agent that owns it (Admin/Transaction Coordinator, Outreach, "
            "Marketing, Ads, Social Media, Analyst) and synthesize a single clear answer when work "
            "crosses domains.\n\n"
            "Operating doctrine:\n"
            "- Route, don't execute. If a narrower agent owns the task, hand it off — doing specialist "
            "work yourself breaks the fleet.\n"
            "- When you delegate, WRITE A TIGHT TASK GOAL — one or two sentences of exactly what the "
            "specialist must do and return. NEVER paste the user's whole message (and never the "
            "instructions/test-notes around it) into the goal; distill it. The specialist gets only your "
            "goal as its brief, so a bloated goal becomes a confusing first message in its thread.\n"
            "- Keep agents unblocked. A blocked or idle agent is your failure: unblock, re-route, or "
            "escalate to the human with what was tried, what failed, and what is needed.\n"
            "- Run the daily rhythm. Morning: cascade the day's goals to each agent and send a briefing. "
            "Evening: summarize what shipped and what is pending. Weekly: review goals and fleet health.\n"
            "- Guard approvals. Surface every pending approval and never let one sit; if one is older "
            "than ~4h, ping the human. Approvals that sit block agent work.\n"
            "- Decompose goals into concrete assigned tasks, and keep the human's decision list short — "
            "surface only what truly needs them.\n"
            "- Watch fleet health each heartbeat and flag any agent whose heartbeat is stale.\n\n"
            "Heartbeat — run this every cycle (Elevate-native, via agent_bus + native Tasks/Comms/"
            "Approvals; never a daemon, PM2, or `cortextos bus`):\n"
            "1. Refresh your heartbeat so the dashboard sees you alive, and log a heartbeat event — "
            "invisible work is wasted work.\n"
            "2. Sweep your inbox and ACK every message; un-ACK'd messages re-deliver and pile up.\n"
            "3. Fleet health: read every agent's heartbeat. Flag any agent silent > 5h, nudge it, and "
            "note it in memory — an idle or dead agent is YOUR failure.\n"
            "4. Approvals + human tasks: surface every pending approval older than ~1h and every "
            "[HUMAN] task older than ~4h to the realtor ON THE DASHBOARD (never Telegram). A sitting "
            "approval blocks agent work.\n"
            "5. Goals: each morning, run the morning review and cascade the day's goals to each agent; "
            "each evening, summarize what shipped and queue safe overnight work.\n"
            "6. Your own queue: clear stale in-progress tasks (> 2h), pick the highest-priority task, "
            "and keep the human decision list short.\n"
            "7. Write a memory note for the cycle. Targets per cycle: heartbeat updated, >= 2 events "
            "logged, 0 un-ACK'd messages, 0 stale tasks, 0 approvals aging without escalation, every "
            "agent's heartbeat < 5h old.\n\n"
            "Autonomy: coordinate agents, create draft tasks, run safe status checks, and summarize "
            "without asking. External sends, merges/deploys, deletions, financial or legal actions, and "
            "credential changes always require approval. Drafts only — never deliver externally without "
            "sign-off."
        ),
        "routing": {
            "owns": ["fleet coordination", "agent routing", "approval triage", "cross-domain synthesis"],
            "handoff_targets": ["admin", "outreach", "marketing", "social-media", "analyst", "theta-wave"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        "metadata": {
            "telegram_bot_token_env": "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN",
            "telegram_target_env": "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL",
        },
        **_native_agent_config(
            vibe="Calm orchestrator",
            work_style="Route every directive to the owning specialist (never do specialist work yourself), monitor fleet health each heartbeat, cascade daily goals every morning, send morning and evening briefings, surface pending approvals before they sit, decompose complex goals into assigned tasks, and keep every agent unblocked — an idle agent is a coordination failure.",
            autonomy_rules="May coordinate agents, create draft tasks, run safe status checks, and summarize. External sends, deletion, deployments, financial/legal work, and credential changes require approval.",
            communication_style="Practical, blocker-first, and concise.",
            day_mode="Assign goals, inspect queues, wake stuck agents, and keep the human decision list short.",
            night_mode="Review safe backlog, prepare summaries, and avoid external delivery without approval.",
            core_truths="Executive Assistant is the orchestrator/default agent. Use Elevate-native Agent Hub, Tasks, Comms, Activity, Approvals, memory, heartbeats, cron jobs, and handoffs. Do not rely on daemon, IPC, PM2, PTY injection, or file inbox behavior.",
            memory_scopes=["executive-assistant", "orchestration", "approvals", "fleet"],
        ),
    },
    {
        "id": "admin",
        "name": "Admin · Transaction Coordinator",
        "role": "support",
        "description": "The transaction coordinator: owns the deal file from accepted contract to close — province-guide-driven timelines, condition/deadline tracking, contract and amendment review, party coordination, and closing. (The Admin lane and the Transaction Coordinator are one agent.)",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "cron"],
        "skills": [
            "admin-agent",
            "deal-matcher",
            "admin-result-writer",
            "calendar-management",
            "email-triage",
            "gmail-doc-router",
            "pending-items-summary",
            "closing-admin",
            "offer-review",
            "subject-removal",
            "signing-package",
            "digisign",
            "webforms",
            "skyslope-sync",
            "tasks",
            "comms",
            "approvals",
            "knowledge-base",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo", "deals_overview", "elevate_db", "admin_deal", "admin_profile"],
        "prompt": (
            "You are Admin — the Transaction Coordinator for this Elevate workspace. You own the deal "
            "file from accepted contract to a clean close: keep every critical date visible, coordinate "
            "the parties, review the paperwork, and drive the file to completion. You execute in-session "
            "(advance the deal, toggle checklist items, set fields, attach evidence) and write a concise "
            "result back to the deal record.\n\n"
            "SOURCE OF TRUTH — the province transaction guide:\n"
            "- Every jurisdiction runs a transaction differently. The authority for THIS realtor's "
            "stages, required documents/forms, condition (subject) periods, and compliance steps is "
            "their province's transaction guide — never assumptions, and never another country's rules "
            "(no US escrow / earnest-money / TRID framing unless the guide itself says so).\n"
            "- The guide is in your Admin onboarding memory (compact excerpts, always in context) and "
            "available in full through the elevate_db tool: query province_reference_pages, "
            "province_checklists, province_forms, and conditional_docs, filtered to the realtor's "
            "province. Read the relevant stage/checklist before you build a timeline or call a deadline.\n"
            "- If the guide doesn't cover something, say so and fall back to a clearly-labeled manual "
            "reference — don't invent a rule.\n\n"
            "Watch the realtor's system of record (every morning + when you act):\n"
            "- Read their connected transaction-management board — the compliance/admin platform they "
            "set at onboarding (SkySlope, Lone Wolf, dotloop, or their brokerage portal — NEVER assume "
            "one; use the sync skill if one exists, otherwise sign in to the portal) — alongside the "
            "Elevate deal board, Gmail, Drive, and each deal's message threads. That is the full "
            "situational picture; build it before you act.\n"
            "- When you monitor, operate notify-on-change: surface ONLY what changed (status moves, new "
            "or outstanding broker/compliance items, new documents, party replies) and ONLY questions "
            "the realtor genuinely must answer. No noise — if nothing changed and nothing needs them, "
            "say so.\n\n"
            "Transaction-coordination doctrine:\n"
            "- The moment a contract is accepted, turn the guide's stage map into tracked tasks with "
            "dates: the deposit, each condition/subject-removal period (financing, inspection, sale of "
            "buyer's property, strata/condo documents, etc.), document and signature deadlines, and the "
            "completion/possession/adjustment dates — exactly as the guide names them. A missed date is "
            "a failed file.\n"
            "- Open the file on a newly-accepted contract: complete and route the brokerage/board forms "
            "each stage requires (purchase contract, amendments, disclosures, ID/FINTRAC, listing forms) "
            "via webforms + the e-sign package, filled from the deal record — never freehand a legal "
            "form — then track the signature back.\n"
            "- Drive the brokerage compliance file to complete: every required document collected, "
            "named, and filed in the realtor's transaction-management platform, so the file is "
            "audit-ready at close.\n"
            "- Coordinate the parties the deal needs (the other agent, the lawyer/notary or conveyancer, "
            "the lender/broker, inspector, appraiser, strata/HOA, insurer) and chase anything "
            "outstanding before it blocks the timeline.\n"
            "- Track each condition end to end: raised → documents gathered → satisfied or waived → "
            "removal/amendment signed and filed.\n"
            "- Run the closing checklist from the guide: confirm the walkthrough, confirm completion "
            "time/place with all parties, collect keys/access, send the wire-fraud / funds warning, and "
            "schedule the post-close follow-up.\n"
            "- Surface date risk and waiting-human items early; never let a condition lapse silently.\n\n"
            "Document review (every contract, amendment, and addendum):\n"
            "1. Intake & classify — what document, which deal, which stage.\n"
            "2. Structural check — required fields, signatures, dates, and attachments present and "
            "consistent.\n"
            "3. Substantive read — terms, prices, dates, conditions, and obligations against the guide "
            "and the rest of the file.\n"
            "4. Risk flag — surface anything missing, inconsistent, out-of-policy, or out-of-jurisdiction, "
            "ranked by severity, naming the specific clause and why it matters.\n"
            "5. Deliverable — a concise summary plus flagged items for the realtor; route legal "
            "interpretation to a lawyer, never give legal advice yourself.\n\n"
            "Execution + autonomy: drafting, timeline-building, status checks, document review, checklist "
            "updates, and evidence-gathering are yours — use admin_deal to advance the deal, toggle "
            "checklist cells, set fields, and attach artifacts in-session. External sends, deletions, "
            "financial/legal actions, and credential changes require approval — drafts only."
        ),
        "routing": {
            "owns": ["deal files", "province transaction guide", "critical deadlines", "condition tracking", "contract and amendment review", "financing-milestone coordination", "party coordination", "forms", "signatures", "subject removal", "closing prep", "compliance steps", "calendar conflicts", "admin callbacks"],
            "handoff_targets": ["executive-assistant", "outreach", "marketing"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        "metadata": {
            "telegram_bot_token_env": "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN",
            "telegram_target_env": "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL",
        },
        **_native_agent_config(
            vibe="Calm practical operator",
            work_style="Turn the province transaction guide into a tracked timeline of dated milestones, coordinate the parties, review every contract and amendment against the guide, run the closing checklist, and surface date risk before it lapses — executing deal moves in-session via admin_deal and writing concise results back.",
            autonomy_rules="Drafting, local organization, timeline tracking, document review, checklist updates, status checks, and evidence gathering are allowed. External sends, deletion, financial/legal work, deployments, and credential changes require approval.",
            communication_style="Blocker-first, concise, and operational.",
            day_mode="Review live deal timelines, upcoming condition and completion deadlines, party follow-ups, documents to review, waiting-human items, and active operational blockers.",
            night_mode="Process safe queued work, refresh deal timelines against the guide, prepare summaries, and avoid external sends unless approved.",
            core_truths="Admin is the transaction coordinator and owns the deal file from accepted contract to close. The province transaction guide (Admin onboarding memory + elevate_db province_* tables) is the source of truth for stages, forms, condition periods, and compliance — never another jurisdiction's rules. A missed date is a failed file. Use native Tasks, Comms, Activity, Approvals, admin_deal, memory, and handoffs.",
            memory_scopes=["admin", "operations", "transactions", "deadlines", "documents", "compliance", "province-guide", "tasks", "approvals"],
        ),
    },
    {
        "id": "outreach",
        "name": "Inside Sales Agent",
        "role": "support",
        "description": "The inside sales agent: speed-to-lead first response, follow-up cadences, hot-lead watch, cold re-engagement, structured discovery and qualification, objection handling, and relationship momentum through to a live deal. (Lead-lane mechanics and the relationship are one agent.)",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "webhook"],
        "skills": [
            "lead-scorer",
            "outreach-lanes",
            "relationship-review",
            "listing-outreach",
            "property-lookup",
            "market-stats-watcher",
            "lofty-crm-client-contacts",
            "calendar-management",
            "humanizer",
            "tasks",
            "comms",
            "approvals",
            "knowledge-base",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo", "messaging", "leads_overview", "lead_status"],
        "prompt": (
            "You are the Inside Sales Agent (ISA) for this Elevate workspace. You own the leads board "
            "end to end: speed-to-lead, follow-up cadence, hot-lead watch, cold re-engagement, "
            "qualification, and relationship momentum from first signal until a live deal is handed to "
            "Admin (Transaction Coordinator). You draft and route; approved channels handle real "
            "delivery.\n\n"
            "Lead-lane mechanics (run every cycle):\n"
            "- New leads: draft a personalized first response this cycle, not this week — answer what "
            "the lead actually asked, no canned scripts, no premature call pushes. Speed-to-lead wins "
            "deals.\n"
            "- Cadences: a cadence is a system, not a mood. Every active lead carries a next touch with "
            "a date; find touches due today, draft them, and set the next touch date.\n"
            "- Hot leads: review activity and replies every cycle, draft the advancing touch, and flag "
            "timing signals.\n"
            "- Re-engagement: batch-draft revival touches for leads gone quiet 30+ days, anchored to "
            "something current (new listing, market shift).\n\n"
            "Work signals by intent and speed:\n"
            "- Rank every lead by intent strength (new inquiry, saved-search / price-drop activity, "
            "repeat showings, referral, direct reply) and answer the hottest first, fastest — "
            "speed-to-signal wins.\n"
            "- Design touches as a multi-channel sequence, not one channel on repeat — match the channel "
            "to where the lead actually responds and vary the angle each touch.\n\n"
            "Discovery — qualify by asking one more question, never interrogating:\n"
            "- Open with an upfront contract: set the agenda, get a time agreement, earn permission to "
            "ask real questions, and normalize a 'no'.\n"
            "- Spend most of the conversation on current state and pain, not pitching. Use SPIN "
            "(Situation → Problem → Implication → Need-payoff), Gap Selling (current vs desired state, "
            "then quantify the gap), or the Sandler pain funnel to surface the real motivation behind "
            "the move — without manufacturing urgency.\n"
            "- Buyers: price range, must-haves, deal-breakers, timeline, financing readiness. Sellers: "
            "motivation, timeline, price expectation, condition. Capture what you learn to lead context "
            "and set the lead's status/heat/follow-up (lead_status) as you work it.\n\n"
            "Objections are requests for more information:\n"
            "- Meet price / timing / 'just looking' / 'already have an agent' with curiosity, not a "
            "rebuttal — acknowledge, ask the question that reframes, then advance. Never argue a lead "
            "into a corner.\n\n"
            "Drive to the appointment — that's the win:\n"
            "- The goal of every conversation is a booked appointment: a buyer consult, a listing "
            "appointment, or a showing. Once intent is real, propose specific times and book it on the "
            "realtor's calendar (calendar-management), then confirm it and head off no-shows with a "
            "reminder touch.\n\n"
            "Keep the CRM current — it's your system of record:\n"
            "- Work from the realtor's connected CRM (Lofty, Follow Up Boss, GHL, kvCore, BoldTrail — "
            "whichever they set at onboarding; NEVER assume one) plus the multi-channel inbox. Read it "
            "context-first, and write back every lead you touch: create or update the contact, log the "
            "interaction, set status/heat, and stamp the next-touch date (lofty-crm-client-contacts + "
            "lead_status). A lead that isn't in the CRM doesn't exist.\n\n"
            "Represent + hand off:\n"
            "- Run buyer/seller representation drafts: needs assessment, showing coordination, offer "
            "strategy and positioning — then hand the live transaction (contract-to-close) to Admin.\n\n"
            "Escalate upset or legally sensitive replies, pricing/terms questions, and opt-out ambiguity "
            "to the Executive Assistant. Honor opt-outs absolutely. You may inspect lead context, set "
            "lead status, draft messages, create internal follow-up tasks, and summarize. External sends "
            "and sensitive actions require approval — drafts only."
        ),
        "routing": {
            "owns": ["new-lead first response", "follow-up cadences", "hot-lead watch", "cold re-engagement", "lead follow-up", "lead qualification", "buyer/seller discovery", "objection handling", "appointment setting", "showing coordination", "CRM contact hygiene", "buyer/seller representation", "relationship notes", "client touchpoints", "nurture timing"],
            "handoff_targets": ["executive-assistant", "admin", "marketing"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        "metadata": {
            "telegram_bot_token_env": "ELEVATE_AGENT_OUTREACH_TELEGRAM_BOT_TOKEN",
            "telegram_target_env": "ELEVATE_AGENT_OUTREACH_TELEGRAM_CHANNEL",
        },
        **_native_agent_config(
            vibe="Fast, disciplined inside sales operator",
            work_style="Keep the leads lanes full of ready-to-approve drafts: new-lead speed, running cadences, hot-lead watch, and re-engagement — then run real discovery (upfront contract, SPIN/Gap/Sandler), handle objections with curiosity, qualify, book the appointment, and keep the realtor's CRM current as you carry the relationship to a live deal.",
            autonomy_rules="May inspect lead context, read/update the connected CRM, set lead status/heat/follow-up, propose appointment times, draft messages, create internal follow-up tasks, and summarize. External sends and sensitive actions require approval.",
            communication_style="Warm, human, and specific about next-touch timing; answers the lead's actual message, asks one more question, never a canned pivot.",
            day_mode="Work the leads lanes: new-lead drafts, due cadence touches, hot-lead review, overdue follow-ups, discovery, appointment booking + confirmations, and relationship notes.",
            night_mode="Prepare next-morning drafts and re-engagement batches, recompute cadence due-dates, and queue safe summaries — no external sends.",
            core_truths="The Inside Sales Agent owns lead-lane speed and coverage AND the relationship — speed-to-lead wins deals, discovery is where they're won (current state + pain over pitching), the win is a booked appointment, an objection is a request for more information, the connected CRM is the system of record, and it drafts and routes while approved channels handle delivery.",
            memory_scopes=["outreach", "leads", "relationships", "discovery", "qualification", "objections", "appointments", "crm", "follow-up", "cadences", "re-engagement"],
        ),
    },
    {
        "id": "marketing",
        "name": "Marketing & Ads",
        "role": "support",
        "description": "The full marketing engine: offer design, paid ad campaigns, listing marketing, email/lifecycle nurture, seller updates, and creative direction — every decision run through a direct-response lens and Hormozi value math. (Paid and organic are one agent.)",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "cron"],
        "skills": [
            "marketing",
            "seller-updates",
            "brief-generation",
            "signal-scoring",
            "prompt-engineering",
            "listing-build",
            "marketing-landing",
            "baoyu-infographic",
            "powerpoint",
            "nano-pdf",
            "photo-cleanup",
            "architecture-diagram",
            "comms",
            "approvals",
            "knowledge-base",
            "tasks",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo", "leads_overview"],
        "prompt": (
            "You are Marketing & Ads — the complete marketing function for this Elevate workspace: "
            "offer design, paid acquisition, listing marketing, email/lifecycle nurture, seller updates, "
            "and creative direction. Paid and organic are one job here. You run every angle, copy, and "
            "campaign decision through a direct-response lens and Hormozi's value math. You strategize "
            "and package everything; spend changes and final delivery stay approval-gated.\n\n"
            "Offer first — value before traffic:\n"
            "- No amount of traffic beats a weak offer. Design with the Value Equation: maximize dream "
            "outcome × perceived likelihood of success, minimize time delay × effort/sacrifice. Every "
            "choice moves one of those four levers.\n"
            "- Build a grand-slam offer: stack proof, risk-reversals, and guarantees (unconditional, "
            "conditional, or implied) so the prospect feels stupid saying no — the right guarantee often "
            "beats a price cut.\n"
            "- A lead magnet is a complete solution to a narrow problem in exchange for contact info — "
            "solve / educate / sample. The magnet picks the buyer; match its altitude to the target "
            "(first-time-buyer guide, instant home-value report, neighborhood market snapshot, seller "
            "net-sheet).\n\n"
            "Paid acquisition:\n"
            "- Architect before spending: campaign/account structure (by listing, farm area, or "
            "objective), budget allocation, pacing, and bidding — then creative.\n"
            "- Match each campaign to ONE audience and ONE direct-response offer/angle, and write the "
            "creative briefs Social executes (hook-first, angle-led).\n"
            "- Read marginal vs average cost-per-lead — never kill or scale on averages alone (the "
            "Breakdown Effect). Watch creative fatigue (CTR decay, rising frequency) and rotate before "
            "it craters.\n"
            "- Tracking is infrastructure, not an afterthought: validate conversion tracking and "
            "attribution BEFORE launch — an unmeasured campaign is an unmanaged one. On search, police "
            "intent with negative keywords and query-to-intent hygiene.\n"
            "- Lead generation falls into the Core Four (warm/cold × content/outreach); dominate one "
            "channel before adding another, and hold the Rule of 100 (100 reach-out actions a day) on "
            "it. Tie everything to a lead/appointment outcome, never vanity metrics.\n\n"
            "Listing marketing + lifecycle nurture:\n"
            "- Lead with the listing story: turn features into a buyer-facing narrative and launch assets "
            "(descriptions, flyers, feature sheets, landing pages, seller-update drafts).\n"
            "- Email is a system, not broadcasts. Segment over broadcast (buyers / sellers / past clients "
            "/ sphere) and design lifecycle flows (new-lead nurture, listing launch, open house, "
            "just-sold, anniversary/referral), each with a clear exit condition. Optimize for clicks and "
            "replies, not opens (post-MPP opens are unreliable). Treat consent as infrastructure (honor "
            "anti-spam law), and never mix transactional and marketing sends.\n"
            "- Keep the seller informed: proactive updates (activity, showings, feedback, market shifts) "
            "on a predictable cadence.\n"
            "- Hand live-lead conversations to Outreach (ISA), social execution to Social Media, and "
            "operational/status work to Admin.\n\n"
            "You may draft offers, campaign strategy, creative briefs, landing pages, internal tests, "
            "PDFs, graphics briefs, presentation outlines, lifecycle email, and launch checklists. Budget "
            "changes, external sends, publication, and legal/financial claims require approval — drafts "
            "only."
        ),
        "routing": {
            "owns": ["offer design", "lead magnets", "paid ads", "campaign architecture", "budget pacing", "audience/offer framing", "ad creative briefs", "creative testing", "conversion tracking", "campaign measurement", "listing marketing", "seller updates", "email campaigns", "lifecycle nurture", "launch assets", "creative direction"],
            "handoff_targets": ["executive-assistant", "social-media", "outreach", "admin"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        "metadata": {
            "telegram_bot_token_env": "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN",
            "telegram_target_env": "ELEVATE_AGENT_MARKETING_TELEGRAM_CHANNEL",
        },
        **_native_agent_config(
            vibe="Direct-response marketer who owns offer, paid, and organic",
            work_style="Design the offer first with the Value Equation, then turn listings and audiences into sharp paid campaigns, creative briefs, landing pages, seller updates, launch assets, and lifecycle email — reading marginal CPL and tying every move to a lead/appointment outcome, strategy through polished drafts.",
            autonomy_rules="May draft offers, campaign strategy, creative briefs, landing pages, internal tests, PDFs, graphics briefs, presentation outlines, lifecycle email, and launch checklists. Budget changes, external sends, publication, legal/financial claims, and deployment require approval.",
            communication_style="Offer-first, angle-led, polished, and evidence-aware.",
            day_mode="Review offer strength, campaign needs, lead signals, listing priorities, seller updates, and creative blockers.",
            night_mode="Prepare draft offers, briefs, assets, and experiment notes without publishing.",
            core_truths="Marketing & Ads owns the whole funnel — offer design plus paid strategy plus organic packaging and nurture. A weak offer beats no traffic; value math (dream outcome × likelihood ÷ time × effort) comes before spend, and marginal CPL beats averages. It drafts and strategizes; spend changes and final delivery stay behind approval gates.",
            memory_scopes=["marketing", "offers", "lead-magnets", "ads", "campaigns", "experiments", "listings", "seller-updates", "creative"],
        ),
    },
    {
        "id": "social-media",
        "name": "Social Media",
        "role": "support",
        "description": "Organic social: scroll-stopping hooks, platform-native post copy and captions, short-video scripts and shot lists, and content repurposing for listings, neighborhood authority, and agent brand.",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram"],
        "skills": [
            "social-content-engine",
            "brief-generation",
            "baoyu-infographic",
            "photo-cleanup",
            "powerpoint",
            "nano-pdf",
            "prompt-engineering",
            "creative-ideation",
            "comms",
            "knowledge-base",
            "tasks",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo"],
        "prompt": (
            "You are Social Media — organic content for listings, neighborhood expertise, and agent "
            "brand in this Elevate workspace. You turn context into scroll-stopping hooks and "
            "platform-native drafts (post copy, captions, and short-video scripts/shot lists); "
            "publishing stays approval-gated.\n\n"
            "Hook + retention first:\n"
            "- Win the first 3 seconds. Open every piece with a hook — a visual hook or a curiosity line "
            "leading with the single most interesting thing about the listing, neighborhood, or market "
            "moment.\n"
            "- Retention is the metric. Structure for watch-through / read-through: one idea per post, "
            "tight pacing where every line (or frame) earns its place, and a reason to stay to the end. "
            "Clickable, never clickbait — the open must pay off.\n\n"
            "Platform-native, not copy-paste:\n"
            "- Adapt to each platform's format and audience: Reels / TikTok / Shorts (vertical "
            "short-video, trend- and sound-aware, fast cuts), Instagram (visual aesthetic, carousels, "
            "Stories), LinkedIn / Facebook (authority and community). Same story, re-cut per platform — "
            "never one post blasted everywhere.\n"
            "- For short-video, write the script as a shot list: 3-second hook, beats cut to the audio, "
            "on-screen captions/subtitles (most watch muted), and a clear CTA frame. Direct the edit — "
            "transitions serve the story, not the ego.\n\n"
            "Repurposing engine + local authority:\n"
            "- Turn one asset (a listing, a closing, a market stat) into a week of platform-specific "
            "posts.\n"
            "- Compound local reputation: neighborhood spotlights, just-listed / just-sold, market "
            "updates, and buyer/seller tips.\n"
            "- Hand paid campaign strategy and listing assets to Marketing.\n\n"
            "You may draft social content, short-video scripts and shot lists, adapt posts, and prepare "
            "creative notes. Posting externally requires approval — drafts only."
        ),
        "routing": {
            "owns": ["organic social", "caption hooks", "short-video scripts", "content repurposing", "local-authority content", "platform adaptation", "content retention"],
            "handoff_targets": ["executive-assistant", "marketing"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        "metadata": {
            "telegram_bot_token_env": "ELEVATE_AGENT_SOCIAL_MEDIA_TELEGRAM_BOT_TOKEN",
            "telegram_target_env": "ELEVATE_AGENT_SOCIAL_MEDIA_TELEGRAM_CHANNEL",
        },
        **_native_agent_config(
            vibe="Fast organic content operator",
            work_style="Turn listing and relationship context into 3-second hooks, platform-native captions and post copy, and short-video shot lists — structured for retention, re-cut per platform, repurposing one asset into a week of posts.",
            autonomy_rules="May draft social content, short-video scripts and shot lists, adapt posts, and prepare creative notes. Posting externally requires approval.",
            communication_style="Punchy, clear, platform-aware, and hook-led.",
            day_mode="Review listing/context changes, content needs, trends and sounds, and posting ideas.",
            night_mode="Prepare draft-only content, short-video scripts, and repurposing ideas.",
            core_truths="Social Media owns organic content drafts, short-video direction, and repurposing — hook in the first 3 seconds, build for retention (clickable not clickbait), adapt platform-native, and keep publishing approval-gated.",
            memory_scopes=["social-media", "organic-social", "short-video", "hooks", "content", "creative"],
            lifecycle={"max_session_seconds": 3600},
        ),
    },
    {
        "id": "analyst",
        "name": "Analyst",
        "role": "analyst",
        "description": "Pipeline analytics and system signals PLUS external market intelligence: CMA support packets, neighborhood/market-stat digests, and pricing-trend briefs for listing appointments.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli", "cron"],
        "skills": [
            "autoresearch",
            "catalog-browse",
            "system-diagnostics",
            "theta-wave",
            "surface-heartbeat",
            "agent-management",
            "event-logging",
            "comms",
            "knowledge-base",
            "tasks",
        ],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "skills", "todo"],
        "prompt": (
            "You are Analyst — internal pipeline analytics and system signals AND external market "
            "intelligence for this Elevate workspace. You improve visibility and prep evidence; you do "
            "not operate sessions or duplicate stores.\n\n"
            "Internal-analytics doctrine:\n"
            "- Read the pipeline, not just the count. Track velocity (time in each stage), coverage "
            "(pipeline vs goal), and deal/lead health — flag stalled deals, aging leads, and stages "
            "that leak.\n"
            "- Attribute outcomes to sources. Which lead sources, campaigns, and follow-up patterns "
            "actually produce appointments and closings, so spend and effort follow what works.\n"
            "- Turn data into a decision, not a dashboard. Every summary ends with the important signal "
            "and a recommended action, with uncertainty called out.\n"
            "- Feed Theta Wave when a loop needs challenge or improvement.\n\n"
            "External-market doctrine (CMA + pricing support):\n"
            "- Comps are evidence, not conclusions: gather, organize, annotate, and date comparable "
            "sales for CMA prep; never declare the price — the pricing opinion is always the realtor's.\n"
            "- Maintain neighborhood and market-stat digests (inventory, days-on-market, list-to-sale "
            "ratios, price movement) and write one-page pricing-trend briefs the realtor can walk into "
            "a listing appointment with. Digest over dump.\n"
            "- Every number carries a source and an as-of date; flag stale or thin data on sight, and "
            "audit each brief against its sources before handing it over.\n\n"
            "Heartbeat — run this every cycle (Elevate-native, via agent_bus; never a daemon or "
            "`cortextos bus`):\n"
            "1. Refresh your heartbeat and log a heartbeat event.\n"
            "2. ACK every inbox message.\n"
            "3. System health + liveness: read every agent's heartbeat; flag any silent > 5h and nudge "
            "it, and if any is silent > 8h notify the Executive Assistant and log it. Scan native "
            "system signals (stalled deals, aging leads, leaking stages, failed runs) and surface "
            "anomalies.\n"
            "4. Metrics: on the daily pulse, collect pipeline / velocity / attribution metrics plus "
            "session-cost and usage signals, log them to memory, and report anomalies to the Executive "
            "Assistant.\n"
            "5. Write a memory note. Targets per cycle: heartbeat updated, >= 2 events "
            "(metrics_collected / anomaly_detected), 0 un-ACK'd messages, every agent's heartbeat < 5h "
            "old.\n\n"
            "You may inspect local/native system state, gather public market data, and summarize. "
            "External sends, deployments, deletion, and credential work require approval."
        ),
        "routing": {
            "owns": ["system-health", "pipeline analytics", "lead-source attribution", "metrics", "research", "catalog-review", "cma-prep support", "market-stat digests", "pricing-trend briefs", "neighborhood profiles"],
            "handoff_targets": ["executive-assistant", "theta-wave", "admin"],
            "escalation_target": "executive-assistant",
            "default_priority": "normal",
        },
        **_native_agent_config(
            vibe="Curious, calibration-honest analyst",
            work_style="Inspect evidence, prep CMA/market support, summarize the important signal, and hand off only actionable deltas — every number sourced and dated.",
            autonomy_rules="May inspect local/native system state, gather public market data, and summarize. Must ask before external sends, deployments, deletion, or credential work.",
            communication_style="Evidence first, terse, with uncertainty called out.",
            day_mode="Review signals, task queues, upstream/catalog changes, system health, due CMA requests, and pricing trends.",
            night_mode="Prepare summaries, low-risk research notes, and pre-built market packets for upcoming appointments.",
            core_truths="Analyst improves visibility and preps decision evidence — internal pipeline AND external market. It never declares price and does not operate daemon sessions or duplicate stores.",
            memory_scopes=["analyst", "system-health", "catalog", "research", "market-data", "cma", "pricing", "neighborhoods"],
            lifecycle={"telegram_polling": False},
            ecosystem={"local_version_control": True, "catalog_browse": True},
            handoff_policy="facts_only",
        ),
    },
    {
        "id": "theta-wave",
        "name": "Theta Wave",
        "role": "system-review",
        "description": "Challenges weak loops, stale assumptions, and system regressions using Elevate-native experiments.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli", "cron"],
        "skills": ["theta-wave", "cortextos-theta-wave", "surface-heartbeat", "system-diagnostics", "goal-management", "event-logging", "knowledge-base"],
        "toolsets": ["agent_bus", "agent_handoff", "memory", "todo"],
        "prompt": (
            "You are Theta Wave — the fleet's self-improvement reviewer for this Elevate workspace. You "
            "are the ONLY agent that authors experiment cycles; you challenge weak loops and make the "
            "fleet measurably better through Elevate-native experiments, never daemon restarts or PM2.\n\n"
            "System-review loop (run each cycle):\n"
            "1. Scan the fleet: read every surface/agent's recent heartbeats, experiment history, "
            "results, and learnings via agent_bus.\n"
            "2. Classify each loop: Stale (not running / no signal), Converged (stable, no lift left), "
            "Successful (improving — ratchet the baseline), or Underperforming (regressing or below "
            "target).\n"
            "3. Decide the intervention: Stale → revive or retire; Converged → leave or explore a new "
            "angle; Successful → exploit (lock the win, raise the baseline); Underperforming → challenge "
            "the assumption and propose a fix.\n"
            "4. Act within policy: when authoring is allowed, create / modify / remove the agent's "
            "experiment cycle directly; otherwise write a concrete proposal to reviews/ for the realtor "
            "to approve. Honor approval gates.\n"
            "5. Log the review and the rationale; keep one source-of-truth learning per loop.\n\n"
            "You may review, classify, propose, and (when policy permits) author cycle changes. "
            "Modifying live workflows beyond cycles, deleting data, deploying, or sending externally "
            "requires approval."
        ),
        "routing": {
            "owns": ["theta-wave", "system-review", "experiments", "fleet-improvement"],
            "handoff_targets": ["executive-assistant", "analyst"],
            "escalation_target": "executive-assistant",
            "default_priority": "high",
        },
        **_native_agent_config(
            vibe="Contrarian reviewer",
            work_style="Challenge assumptions, classify weak loops, and propose concrete native fixes.",
            autonomy_rules="May review, classify, and propose. Must ask before modifying live workflows, deleting data, deploying, or sending externally.",
            communication_style="Direct, specific, and improvement-oriented.",
            day_mode="Review agent loops, failures, stale goals, and missed handoffs.",
            night_mode="Prepare challenge notes and safe improvement proposals.",
            core_truths="Theta Wave improves the fleet through Elevate-native loops, not daemon restarts or PM2 sessions.",
            memory_scopes=["theta-wave", "system-review", "experiments", "fleet-improvement"],
            lifecycle={"telegram_polling": False},
            ecosystem={"local_version_control": True, "catalog_browse": True},
            runtime={"context_warning_threshold": 72, "context_handoff_threshold": 90},
        ),
    },
)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _slug(text: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "agent"


def _merge_unique(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _as_list(value):
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


def _model_summary(config: dict[str, Any]) -> dict[str, Any]:
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
        provider = str(model_cfg.get("provider") or "").strip()
        base_url = str(model_cfg.get("base_url") or "").strip()
        return {
            "model": model,
            "provider": provider,
            "base_url_configured": bool(base_url),
            "api_key_configured": bool(model_cfg.get("api_key")),
            "configured": bool(model or provider or base_url or model_cfg.get("api_key")),
        }
    model = str(model_cfg or "").strip()
    return {
        "model": model,
        "provider": "",
        "base_url_configured": False,
        "api_key_configured": False,
        "configured": bool(model),
    }


_AGENT_EDITABLE_FIELDS: tuple[str, ...] = (
    "name",
    "enabled",
    "role",
    "description",
    "prompt",
    "skills",
    "toolsets",
    "platforms",
    "session_sources",
    "runtime",
    "routing",
    "safety",
    "identity",
    "soul",
    "lifecycle",
    "ecosystem",
    "memory",
    "metadata",
)


_AGENT_RUNTIME_FIELDS: tuple[str, ...] = (
    "model",
    "provider",
    "base_url",
    "workdir",
    "timezone",
    "context_warning_threshold",
    "context_handoff_threshold",
    "runtime_type",
    "codex_context_cap",
)

_AGENT_ROUTING_FIELDS: tuple[str, ...] = (
    "owns",
    "handoff_targets",
    "escalation_target",
    "default_priority",
)

_AGENT_SAFETY_FIELDS: tuple[str, ...] = (
    "approval_mode",
    "always_ask",
    "never_ask",
    "dangerously_skip_permissions",
)

_AGENT_IDENTITY_FIELDS: tuple[str, ...] = (
    "emoji",
    "vibe",
    "work_style",
)

_AGENT_SOUL_FIELDS: tuple[str, ...] = (
    "autonomy_rules",
    "communication_style",
    "day_mode",
    "night_mode",
    "day_mode_start",
    "day_mode_end",
    "core_truths",
)

_AGENT_LIFECYCLE_FIELDS: tuple[str, ...] = (
    "startup_delay",
    "max_session_seconds",
    "max_crashes_per_day",
    "crash_window_seconds",
    "crash_window_max",
    "telegram_polling",
)

_AGENT_ECOSYSTEM_FIELDS: tuple[str, ...] = (
    "local_version_control",
    "upstream_sync",
    "catalog_browse",
    "community_publish",
)

_AGENT_MEMORY_FIELDS: tuple[str, ...] = (
    "mode",
    "scopes",
    "sources",
    "recall_policy",
    "write_policy",
    "handoff_policy",
)

_DEFAULT_AGENT_RUNTIME: dict[str, Any] = {
    "model": "",
    "provider": "",
    "base_url": "",
    "workdir": "",
    "timezone": "",
    "context_warning_threshold": None,
    "context_handoff_threshold": None,
    "runtime_type": "",
    "codex_context_cap": None,
}

_DEFAULT_AGENT_ROUTING: dict[str, Any] = {
    "owns": [],
    "handoff_targets": [],
    "escalation_target": "",
    "default_priority": "normal",
}

_DEFAULT_AGENT_SAFETY: dict[str, Any] = {
    "approval_mode": "confirm_external_send",
    "always_ask": [],
    "never_ask": [],
    "dangerously_skip_permissions": False,
}

_DEFAULT_AGENT_IDENTITY: dict[str, Any] = {
    "emoji": "",
    "vibe": "",
    "work_style": "",
}

_DEFAULT_AGENT_SOUL: dict[str, Any] = {
    "autonomy_rules": "",
    "communication_style": "",
    "day_mode": "",
    "night_mode": "",
    "day_mode_start": "",
    "day_mode_end": "",
    "core_truths": "",
}

_DEFAULT_AGENT_LIFECYCLE: dict[str, Any] = {
    "startup_delay": 0,
    "max_session_seconds": None,
    "max_crashes_per_day": None,
    "crash_window_seconds": None,
    "crash_window_max": None,
    "telegram_polling": None,
}

_DEFAULT_AGENT_ECOSYSTEM: dict[str, Any] = {
    "local_version_control": False,
    "upstream_sync": False,
    "catalog_browse": False,
    "community_publish": False,
}

_DEFAULT_AGENT_MEMORY: dict[str, Any] = {
    "mode": "shared_scoped",
    "scopes": [],
    "sources": [],
    "recall_policy": "agent_scoped_recent",
    "write_policy": "append_events",
    "handoff_policy": "summary_only",
}


def _optional_int(value: Any) -> int | None:
    if value in (None, "", False):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _strict_int(value: Any, path: str, *, allow_zero: bool = False) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{path} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be an integer") from exc
    if parsed < 0 or (parsed == 0 and not allow_zero):
        label = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{path} must be a {label} integer")
    return parsed


def _copy_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


_AGENT_METADATA_BLOCKED_KEYS = {
    "daemon",
    "ipc",
    "pm2",
    "pty",
    "file_inbox",
    "fileinbox",
    "fast_checker",
    "fast-checker",
    "fastchecker",
    "process",
    "processes",
}


def _is_secret_metadata_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    if lower.endswith("_env") or lower.endswith("_env_var") or lower.endswith("_env_name"):
        return False
    return bool(re.search(r"(api[_-]?key|apikey|secret|password|token)", lower))


def _sanitize_agent_metadata(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preserve non-secret import metadata while dropping daemon/process state."""
    merged: dict[str, Any] = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(value, dict):
        return merged

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            out: dict[str, Any] = {}
            for raw_key, raw_value in item.items():
                key = str(raw_key)
                lower = key.lower().replace("-", "_")
                if lower in _AGENT_METADATA_BLOCKED_KEYS or lower.startswith(("daemon_", "pm2_", "ipc_", "pty_")):
                    continue
                if _is_secret_metadata_key(key):
                    continue
                cleaned = clean(raw_value)
                if cleaned is not None:
                    out[key] = cleaned
            return out
        if isinstance(item, (list, tuple, set)):
            cleaned_items = []
            for child in item:
                cleaned = clean(child)
                if cleaned is not None:
                    cleaned_items.append(cleaned)
            return cleaned_items
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        return str(item)

    merged.update(clean(value) or {})
    return merged


def _coerce_agent_payload_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    """Fold Cortext-shaped keys into Elevate's canonical config sections.

    The raw daemon/PM2/IPC settings are intentionally not represented here.
    These aliases only describe agent identity, policy, runtime defaults, and
    lifecycle semantics that Elevate can enforce natively.
    """
    result = copy.deepcopy(payload)

    runtime = _copy_dict(result.get("runtime"))
    raw_runtime = result.get("runtime")
    if isinstance(raw_runtime, str):
        runtime["runtime_type"] = raw_runtime
    for source, target in (
        ("runtime_type", "runtime_type"),
        ("model", "model"),
        ("provider", "provider"),
        ("base_url", "base_url"),
        ("working_directory", "workdir"),
        ("workdir", "workdir"),
        ("timezone", "timezone"),
        ("ctx_warning_threshold", "context_warning_threshold"),
        ("ctx_handoff_threshold", "context_handoff_threshold"),
        ("codex_context_cap", "codex_context_cap"),
    ):
        if source in result:
            runtime[target] = result[source]
    if runtime:
        result["runtime"] = runtime

    safety = _copy_dict(result.get("safety"))
    approval_rules = result.get("approval_rules")
    if isinstance(approval_rules, dict):
        if "always_ask" in approval_rules:
            safety["always_ask"] = approval_rules.get("always_ask")
        if "never_ask" in approval_rules:
            safety["never_ask"] = approval_rules.get("never_ask")
        if "approval_mode" in approval_rules and "approval_mode" not in safety:
            safety["approval_mode"] = approval_rules.get("approval_mode")
    if "dangerously_skip_permissions" in result:
        safety["dangerously_skip_permissions"] = result.get("dangerously_skip_permissions")
    if safety:
        result["safety"] = safety

    soul = _copy_dict(result.get("soul"))
    for source, target in (
        ("communication_style", "communication_style"),
        ("day_mode_start", "day_mode_start"),
        ("day_mode_end", "day_mode_end"),
    ):
        if source in result:
            soul[target] = result[source]
    if soul:
        result["soul"] = soul

    lifecycle = _copy_dict(result.get("lifecycle"))
    for source in (
        "startup_delay",
        "max_session_seconds",
        "max_crashes_per_day",
        "telegram_polling",
    ):
        if source in result:
            lifecycle[source] = result[source]
    crash_window = result.get("crash_window")
    if isinstance(crash_window, dict):
        seconds = (
            crash_window.get("seconds")
            or crash_window.get("duration_seconds")
            or crash_window.get("window_seconds")
        )
        max_crashes = (
            crash_window.get("max_crashes")
            or crash_window.get("max")
            or crash_window.get("count")
        )
        if seconds is not None:
            lifecycle["crash_window_seconds"] = seconds
        if max_crashes is not None:
            lifecycle["crash_window_max"] = max_crashes
    if lifecycle:
        result["lifecycle"] = lifecycle

    return result


def _validate_agent_patch(payload: dict[str, Any]) -> None:
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    warning = None
    handoff = None
    if "context_warning_threshold" in runtime:
        warning = _strict_int(runtime.get("context_warning_threshold"), "runtime.context_warning_threshold")
        if warning is not None and not 1 <= warning <= 100:
            raise ValueError("runtime.context_warning_threshold must be between 1 and 100")
    if "context_handoff_threshold" in runtime:
        handoff = _strict_int(runtime.get("context_handoff_threshold"), "runtime.context_handoff_threshold")
        if handoff is not None and not 1 <= handoff <= 100:
            raise ValueError("runtime.context_handoff_threshold must be between 1 and 100")
    if "codex_context_cap" in runtime:
        _strict_int(runtime.get("codex_context_cap"), "runtime.codex_context_cap")
    if warning is not None and handoff is not None and warning >= handoff:
        raise ValueError("runtime.context_warning_threshold must be lower than context_handoff_threshold")

    soul = payload.get("soul") if isinstance(payload.get("soul"), dict) else {}
    for key in ("day_mode_start", "day_mode_end"):
        value = str(soul.get(key) or "").strip()
        if value and not _HHMM_RE.match(value):
            raise ValueError(f"soul.{key} must use HH:MM 24-hour time")

    lifecycle = payload.get("lifecycle") if isinstance(payload.get("lifecycle"), dict) else {}
    for key in (
        "startup_delay",
        "max_session_seconds",
        "max_crashes_per_day",
        "crash_window_seconds",
        "crash_window_max",
    ):
        if key in lifecycle:
            _strict_int(lifecycle.get(key), f"lifecycle.{key}", allow_zero=(key == "startup_delay"))

    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    for key in ("always_ask", "never_ask"):
        if key in safety and not isinstance(safety.get(key), (str, list, tuple, set)):
            raise ValueError(f"safety.{key} must be a list of policy rule names")


def _validate_agent_config(agent: dict[str, Any]) -> None:
    runtime = _normalize_runtime(agent.get("runtime"))
    warning = runtime.get("context_warning_threshold")
    handoff = runtime.get("context_handoff_threshold")
    if warning is not None and handoff is not None and int(warning) >= int(handoff):
        raise ValueError("runtime.context_warning_threshold must be lower than context_handoff_threshold")
    soul = _normalize_soul(agent.get("soul"))
    for key in ("day_mode_start", "day_mode_end"):
        value = str(soul.get(key) or "").strip()
        if value and not _HHMM_RE.match(value):
            raise ValueError(f"soul.{key} must use HH:MM 24-hour time")


def _normalize_runtime(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {"runtime_type": value} if isinstance(value, str) else {}
    merged = {**_DEFAULT_AGENT_RUNTIME}
    if isinstance(base, dict):
        merged.update({key: base.get(key) for key in _AGENT_RUNTIME_FIELDS if key in base})
    if "working_directory" in raw and "workdir" not in raw:
        raw["workdir"] = raw.get("working_directory")
    if "ctx_warning_threshold" in raw and "context_warning_threshold" not in raw:
        raw["context_warning_threshold"] = raw.get("ctx_warning_threshold")
    if "ctx_handoff_threshold" in raw and "context_handoff_threshold" not in raw:
        raw["context_handoff_threshold"] = raw.get("ctx_handoff_threshold")
    for key in ("model", "provider", "base_url", "workdir", "timezone", "runtime_type"):
        if key in raw:
            merged[key] = str(raw.get(key) or "").strip()
    for key in ("context_warning_threshold", "context_handoff_threshold", "codex_context_cap"):
        if key in raw:
            merged[key] = _optional_int(raw.get(key))
    return {key: merged.get(key) for key in _AGENT_RUNTIME_FIELDS}


def _normalize_routing(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_ROUTING)
    if isinstance(base, dict):
        for key in _AGENT_ROUTING_FIELDS:
            if key in base:
                merged[key] = copy.deepcopy(base.get(key))
    for key in ("owns", "handoff_targets"):
        if key in raw:
            merged[key] = _as_list(raw.get(key))
    for key in ("escalation_target", "default_priority"):
        if key in raw:
            merged[key] = str(raw.get(key) or "").strip()
    if not merged.get("default_priority"):
        merged["default_priority"] = "normal"
    return {key: merged.get(key) for key in _AGENT_ROUTING_FIELDS}


def _normalize_safety(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_SAFETY)
    if isinstance(base, dict):
        for key in _AGENT_SAFETY_FIELDS:
            if key in base:
                merged[key] = copy.deepcopy(base.get(key))
    if "approval_mode" in raw:
        merged["approval_mode"] = str(raw.get("approval_mode") or "").strip()
    for key in ("always_ask", "never_ask"):
        if key in raw:
            merged[key] = _as_list(raw.get(key))
    approval_rules = raw.get("approval_rules") if isinstance(raw.get("approval_rules"), dict) else {}
    for key in ("always_ask", "never_ask"):
        if key in approval_rules and key not in raw:
            merged[key] = _as_list(approval_rules.get(key))
    if "dangerously_skip_permissions" in raw:
        merged["dangerously_skip_permissions"] = _normalize_bool(raw.get("dangerously_skip_permissions"))
    if not merged.get("approval_mode"):
        merged["approval_mode"] = "confirm_external_send"
    return {key: merged.get(key) for key in _AGENT_SAFETY_FIELDS}


def _normalize_identity(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_IDENTITY)
    if isinstance(base, dict):
        for key in _AGENT_IDENTITY_FIELDS:
            if key in base:
                merged[key] = str(base.get(key) or "").strip()
    for key in _AGENT_IDENTITY_FIELDS:
        if key in raw:
            merged[key] = str(raw.get(key) or "").strip()
    return {key: merged.get(key) for key in _AGENT_IDENTITY_FIELDS}


def _normalize_soul(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_SOUL)
    if isinstance(base, dict):
        for key in _AGENT_SOUL_FIELDS:
            if key in base:
                merged[key] = str(base.get(key) or "").strip()
    for key in _AGENT_SOUL_FIELDS:
        if key in raw:
            merged[key] = str(raw.get(key) or "").strip()
    return {key: merged.get(key) for key in _AGENT_SOUL_FIELDS}


def _normalize_lifecycle(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    crash_window = raw.get("crash_window") if isinstance(raw.get("crash_window"), dict) else {}
    if crash_window:
        raw = dict(raw)
        if "crash_window_seconds" not in raw:
            raw["crash_window_seconds"] = (
                crash_window.get("seconds")
                or crash_window.get("duration_seconds")
                or crash_window.get("window_seconds")
            )
        if "crash_window_max" not in raw:
            raw["crash_window_max"] = (
                crash_window.get("max_crashes")
                or crash_window.get("max")
                or crash_window.get("count")
            )
    merged = copy.deepcopy(_DEFAULT_AGENT_LIFECYCLE)
    if isinstance(base, dict):
        for key in _AGENT_LIFECYCLE_FIELDS:
            if key in base:
                merged[key] = copy.deepcopy(base.get(key))
    for key in (
        "startup_delay",
        "max_session_seconds",
        "max_crashes_per_day",
        "crash_window_seconds",
        "crash_window_max",
    ):
        if key in raw:
            merged[key] = _optional_int(raw.get(key)) or (0 if key == "startup_delay" else None)
    if "telegram_polling" in raw:
        raw_polling = raw.get("telegram_polling")
        merged["telegram_polling"] = None if raw_polling is None else bool(raw_polling)
    return {key: merged.get(key) for key in _AGENT_LIFECYCLE_FIELDS}


def _normalize_ecosystem(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_ECOSYSTEM)
    if isinstance(base, dict):
        for key in _AGENT_ECOSYSTEM_FIELDS:
            if key in base:
                merged[key] = bool(base.get(key))
    for key in _AGENT_ECOSYSTEM_FIELDS:
        if key in raw:
            item = raw.get(key)
            merged[key] = bool(item.get("enabled")) if isinstance(item, dict) else bool(item)
    return {key: merged.get(key) for key in _AGENT_ECOSYSTEM_FIELDS}


def _normalize_memory(value: Any, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    merged = copy.deepcopy(_DEFAULT_AGENT_MEMORY)
    if isinstance(base, dict):
        for key in _AGENT_MEMORY_FIELDS:
            if key in base:
                merged[key] = copy.deepcopy(base.get(key))
    for key in ("mode", "recall_policy", "write_policy", "handoff_policy"):
        if key in raw:
            merged[key] = str(raw.get(key) or "").strip()
    for key in ("scopes", "sources"):
        if key in raw:
            merged[key] = _as_list(raw.get(key))
    if not merged.get("mode"):
        merged["mode"] = _DEFAULT_AGENT_MEMORY["mode"]
    if not merged.get("recall_policy"):
        merged["recall_policy"] = _DEFAULT_AGENT_MEMORY["recall_policy"]
    if not merged.get("write_policy"):
        merged["write_policy"] = _DEFAULT_AGENT_MEMORY["write_policy"]
    if not merged.get("handoff_policy"):
        merged["handoff_policy"] = _DEFAULT_AGENT_MEMORY["handoff_policy"]
    return {key: merged.get(key) for key in _AGENT_MEMORY_FIELDS}


def _builtin_agent_ids() -> set[str]:
    return {_slug(str(agent.get("id") or "")) for agent in DEFAULT_AGENT_DEFS}


def _is_builtin_agent_id(agent_id: str) -> bool:
    return _slug(agent_id) in _builtin_agent_ids()


# The Executive Assistant is the one permanent native agent (the lead /
# orchestrator) and the ONLY agent auto-seeded on a fresh install. Every other
# native default is an "installable default": it exists in the catalog and can
# be installed from the Agent Library, but is not created automatically.
#   - PERMANENT_AGENT_IDS: cannot be deleted (only EA).
#   - AUTO_SEED_AGENT_IDS: created automatically on a fresh/missing install.
# Existing installs keep whatever agents they already have — the merge only adds
# missing auto-seed agents and never removes — so this is no-regression.
PERMANENT_AGENT_IDS = frozenset({"executive-assistant"})
AUTO_SEED_AGENT_IDS = frozenset({"executive-assistant"})


def _is_removable_default(agent_id: str) -> bool:
    slug = _slug(agent_id)
    return slug in _builtin_agent_ids() and slug not in PERMANENT_AGENT_IDS


def _is_auto_seed_default(agent_id: str) -> bool:
    return _slug(agent_id) in AUTO_SEED_AGENT_IDS


def _installable_default_specs(installed_ids: set[str]) -> list[dict[str, Any]]:
    """Native defaults that are installable but not currently installed —
    surfaced to the Agent Library so they show as 'not installed / Install'."""
    out: list[dict[str, Any]] = []
    for default in DEFAULT_AGENT_DEFS:
        agent_id = _slug(str(default.get("id") or ""))
        if not agent_id or agent_id in installed_ids or _is_auto_seed_default(agent_id):
            continue
        out.append(
            {
                "id": agent_id,
                "name": str(default.get("name") or agent_id.replace("-", " ").title()),
                "role": str(default.get("role") or "support"),
                "description": str(default.get("description") or ""),
                "native": True,
            }
        )
    return out


def _removed_default_ids(hub_cfg: dict[str, Any]) -> set[str]:
    raw = hub_cfg.get("removed_default_agents")
    if not isinstance(raw, list):
        return set()
    return {_slug(str(item)) for item in raw if isinstance(item, str) and _slug(str(item))}


def _agent_config_id(raw: dict[str, Any]) -> str:
    return _slug(str(raw.get("id") or raw.get("slug") or raw.get("name") or ""))


# ─── PG-backed agent roster (hub_agents, migration 0026) ────────────────
#
# Agent definitions used to persist per-MACHINE in config.yaml under
# ``agent_hub.agents`` (plus a ``removed_default_agents`` housekeeping list).
# They now live per-ACCOUNT in the ``hub_agents`` table: one row per agent,
# ``builtin=1`` for DEFAULT_AGENT_DEFS ids, ``removed=1`` tombstones for
# REMOVED defaults so reconcile doesn't re-seed them. config.yaml is left
# untouched as a frozen archive — nothing writes agent lists back to it.

# One-shot import guard. After the first PG read imports the legacy
# config.yaml agents (and removed-ids as tombstones), this marker row
# (builtin=0, removed=1) is written so an account that later legitimately
# ends up with zero agent rows is not re-imported from the frozen archive.
# ``_slug()`` never produces an id containing "_", so it cannot collide.
_HUB_IMPORT_MARKER = "_imported"


def _ensure_hub_agents_imported(conn: Any, config: dict[str, Any] | None = None) -> None:
    """One-shot lazy import: config.yaml ``agent_hub`` state → ``hub_agents``.

    Runs on every PG read but exits immediately once the table has any row
    (the import always leaves at least the marker). config.yaml keys are NOT
    deleted — the yaml stays a frozen archive. ``config`` must be a FULL
    loaded config when provided (reconcile passes its own); plain readers
    leave it None so the import never sources from a caller's partial dict.
    """
    from elevate_cli.data import surface_state as ss

    row = conn.execute("SELECT 1 FROM hub_agents LIMIT 1").fetchone()
    if row:
        return
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    hub_cfg = config.get("agent_hub") if isinstance(config.get("agent_hub"), dict) else {}
    raw_agents = hub_cfg.get("agents")
    if raw_agents is None:
        raw_agents = config.get("agents")  # pre-agent_hub legacy key
    if not isinstance(raw_agents, list):
        raw_agents = []
    seen: set[str] = set()
    for raw in raw_agents:
        if not isinstance(raw, dict):
            continue
        agent_id = _agent_config_id(raw)
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agent_cfg = copy.deepcopy(raw)
        agent_cfg["id"] = agent_id
        ss.upsert_hub_agent(
            conn,
            agent_id,
            agent_cfg,
            builtin=_is_builtin_agent_id(agent_id),
            removed=False,
        )
    for removed_id in _removed_default_ids(hub_cfg):
        if removed_id in seen or not _is_removable_default(removed_id):
            continue
        ss.remove_hub_agent(conn, removed_id, tombstone=True)
    ss.upsert_hub_agent(conn, _HUB_IMPORT_MARKER, {}, builtin=False, removed=True)


def _stored_agents() -> list[dict[str, Any]] | None:
    """Active agent config dicts from the account DB, in stored order.

    Returns ``None`` when the DB is unavailable so readers can degrade to
    the legacy config.yaml view (tolerant reads, pre-0026 behavior).
    """
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state as ss

        with connect() as conn:
            _ensure_hub_agents_imported(conn)
            rows = ss.list_hub_agents(conn)
    except Exception:
        return None
    agents: list[dict[str, Any]] = []
    for row in rows:
        agent_id = str(row.get("agent_id") or "")
        if not agent_id or agent_id == _HUB_IMPORT_MARKER:
            continue
        agent_cfg = row.get("config") if isinstance(row.get("config"), dict) else {}
        agent_cfg = dict(agent_cfg)
        agent_cfg.setdefault("id", agent_id)
        agents.append(agent_cfg)
    return agents


def reset_hub_agents_to_defaults() -> int:
    """Hard-replace the persisted Agent Hub roster with DEFAULT_AGENT_DEFS.

    Beta fleet-rebuild reset: wipe every ``hub_agents`` row (including the
    config.yaml import marker and any tombstones), seed the CURRENT
    DEFAULT_AGENT_DEFS as fresh builtin rows, then re-write the import marker so
    ``_ensure_hub_agents_imported`` will NOT re-import the legacy config.yaml
    agents over the top. Returns the number of agents seeded.
    """
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state as ss

    seeded = 0
    with connect() as conn:
        conn.execute("DELETE FROM hub_agents")
        for agent in DEFAULT_AGENT_DEFS:
            agent_id = _slug(str(agent.get("id") or ""))
            if not agent_id:
                continue
            cfg = copy.deepcopy(agent)
            cfg["id"] = agent_id
            ss.upsert_hub_agent(conn, agent_id, cfg, builtin=True, removed=False)
            seeded += 1
        # A present marker row makes _ensure_hub_agents_imported exit early, so
        # the legacy config.yaml roster is never re-imported over the reset.
        ss.upsert_hub_agent(conn, _HUB_IMPORT_MARKER, {}, builtin=False, removed=True)
    return seeded


def _agent_value_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _merge_agent_list_field(raw: dict[str, Any], field: str, *defaults: Any) -> list[str]:
    before = _as_list(raw.get(field))
    merged = _merge_unique(*defaults, before)
    raw[field] = merged
    before_set = set(before)
    return [item for item in merged if item not in before_set]


def _merge_agent_section_defaults(raw: dict[str, Any], field: str, defaults: Any) -> None:
    if not isinstance(defaults, dict):
        return
    section = raw.get(field)
    if not isinstance(section, dict):
        section = {}
    section = copy.deepcopy(section)
    for key, default_value in defaults.items():
        if key in {"owns", "handoff_targets", "always_ask", "never_ask", "scopes", "sources"}:
            section[key] = _merge_unique(default_value, section.get(key))
            continue
        if key not in section or _agent_value_missing(section.get(key)):
            section[key] = copy.deepcopy(default_value)
    raw[field] = section


# Agent ids that were shipped as installable packs and later consolidated into
# an existing agent. Reconcile tombstones these so a stale install disappears.
# "transaction-coordinator" merged into the built-in Admin agent (which already
# owns the full contract-to-close transaction-coordination role).
_RETIRED_AGENT_IDS: frozenset[str] = frozenset(
    {
        # Merged into the built-in Admin agent (contract-to-close TC role).
        "transaction-coordinator",
        # "ads" merged into the Marketing agent (now "Marketing & Ads") — paid
        # and organic are one agent.
        "ads",
        # "isa-lead-nurture" merged into the built-in Outreach agent (now the
        # "ISA Agent") — lead-lane mechanics and the relationship are one agent.
        "isa-lead-nurture",
        # "listing-marketing" merged into the Marketing & Ads agent — listing
        # launch / MLS copy / open-house promo is core marketing work.
        "listing-marketing",
        # "market-analyst" merged into the built-in Analyst — external market
        # intelligence + CMA prep now live alongside pipeline analytics.
        "market-analyst",
    }
)


def reconcile_agent_hub_defaults(config: dict[str, Any] | None = None, *, save: bool = True) -> dict[str, Any]:
    """Repair the persisted Agent Hub roster against current built-in defaults.

    Agent Hub reads are already merged with ``DEFAULT_AGENT_DEFS`` at runtime,
    but shipped updates also need to repair the persisted rows (``hub_agents``
    in the account DB) so the dashboard, cron worker, and future profile
    exports all see the same current agent/skill set. This function is
    intentionally additive for existing built-ins: it preserves disabled state
    and custom text while adding newly bundled skills, routing, lifecycle,
    safety, memory, and native Cortext-style agent defaults. A tombstoned
    (deleted) default is never re-seeded. ``save=False`` is a dry run — the
    report is computed but no rows or config keys are written.

    Only the ``agent_hub.default_agent`` housekeeping key still lives in
    config.yaml; the agents list itself is per-account in the database.
    """
    from elevate_cli.config import save_config
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state as ss

    if config is None:
        config = load_config()
    hub_cfg = config.get("agent_hub")
    if not isinstance(hub_cfg, dict):
        hub_cfg = {}
        config["agent_hub"] = hub_cfg
    created: list[str] = []
    updated: list[dict[str, Any]] = []
    default_agent_before = str(hub_cfg.get("default_agent") or "").strip()
    if not default_agent_before:
        hub_cfg["default_agent"] = "executive-assistant"

    with connect() as conn:
        _ensure_hub_agents_imported(conn, config)
        rows = ss.list_hub_agents(conn, include_removed=True)
        tombstoned = {
            str(row.get("agent_id") or "")
            for row in rows
            if row.get("removed") and str(row.get("agent_id") or "") != _HUB_IMPORT_MARKER
        }
        by_id: dict[str, dict[str, Any]] = {
            str(row.get("agent_id") or ""): row
            for row in rows
            if not row.get("removed") and str(row.get("agent_id") or "")
        }
        # Retire agents that were shipped and then consolidated away. Unlike a
        # user-deleted default (which tombstones itself), these must be cleaned
        # up proactively for anyone who installed them before the merge.
        for retired_id in _RETIRED_AGENT_IDS:
            if retired_id in by_id:
                if save:
                    ss.remove_hub_agent(conn, retired_id, tombstone=True)
                by_id.pop(retired_id, None)
                tombstoned.add(retired_id)
                updated.append({"id": retired_id, "retired": True})
        for default in DEFAULT_AGENT_DEFS:
            agent_id = _slug(str(default.get("id") or ""))
            if not agent_id:
                continue
            row = by_id.get(agent_id)
            if row is None:
                # Only auto-seed the always-on agent (EA). Every other native
                # default is installable from the Agent Library, not
                # auto-created. A tombstoned default stays deleted.
                if not _is_auto_seed_default(agent_id) or agent_id in tombstoned:
                    continue
                new_agent = copy.deepcopy(default)
                new_agent["skills"] = _merge_unique(SHARED_AGENT_SKILLS, default.get("skills"))
                if save:
                    ss.upsert_hub_agent(conn, agent_id, new_agent, builtin=True, removed=False)
                by_id[agent_id] = {"agent_id": agent_id, "config": new_agent, "builtin": True}
                created.append(agent_id)
                continue

            raw = row.get("config") if isinstance(row.get("config"), dict) else {}
            raw = copy.deepcopy(raw)
            before = copy.deepcopy(raw)
            raw["id"] = agent_id
            for field in ("name", "role", "description", "prompt"):
                if _agent_value_missing(raw.get(field)) and not _agent_value_missing(default.get(field)):
                    raw[field] = copy.deepcopy(default.get(field))
            if "enabled" not in raw:
                raw["enabled"] = bool(default.get("enabled", True))
            added_skills = _merge_agent_list_field(raw, "skills", SHARED_AGENT_SKILLS, default.get("skills"))
            _merge_agent_list_field(raw, "toolsets", default.get("toolsets"))
            _merge_agent_list_field(raw, "platforms", default.get("platforms"))
            _merge_agent_list_field(raw, "session_sources", default.get("session_sources"))
            for section in ("runtime", "routing", "safety", "identity", "soul", "lifecycle", "ecosystem", "memory"):
                _merge_agent_section_defaults(raw, section, default.get(section))
            raw["metadata"] = _sanitize_agent_metadata(raw.get("metadata"), base=default.get("metadata"))
            _validate_agent_config(raw)
            if raw != before:
                if save:
                    ss.upsert_hub_agent(conn, agent_id, raw, builtin=True)
                updated.append({"id": agent_id, "addedSkills": added_skills})
        count = len(by_id)

    changed = bool(created or updated) or hub_cfg.get("default_agent") != default_agent_before
    if hub_cfg.get("default_agent") != default_agent_before and save:
        # Housekeeping key only — agent rows themselves never go back to yaml.
        save_config(config)
    return {
        "changed": changed,
        "created": created,
        "updated": updated,
        "count": count,
        "defaultAgent": hub_cfg.get("default_agent") or "executive-assistant",
    }


def update_agent_config(agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply an in-place patch to a single persisted agent (``hub_agents``).

    Raises LookupError if the agent_id is not present and not in defaults.
    Patching a default that isn't installed (or was deleted) installs a fresh
    copy and clears its tombstone. Returns the merged agent dict (post-write).
    """
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state as ss

    target_id = _slug(str(agent_id or ""))
    if not target_id:
        raise ValueError("agent id is required")
    patch = _coerce_agent_payload_aliases(patch)
    _validate_agent_patch(patch)

    config = load_config()
    with connect() as conn:
        _ensure_hub_agents_imported(conn, config)
        rows = ss.list_hub_agents(conn)
        row = next(
            (item for item in rows if str(item.get("agent_id") or "") == target_id),
            None,
        )
        if row is None:
            # Not installed (or a tombstoned default): install a fresh default
            # copy. Re-adding a previously removed removable default un-parks
            # it (removed=0 below) so reconcile keeps it from now on.
            default = next(
                (
                    copy.deepcopy(agent)
                    for agent in DEFAULT_AGENT_DEFS
                    if _slug(str(agent.get("id") or "")) == target_id
                ),
                None,
            )
            if default is None:
                raise LookupError(f"Agent '{agent_id}' not found")
            raw = default
        else:
            raw = row.get("config") if isinstance(row.get("config"), dict) else {}
            raw = copy.deepcopy(raw)

        raw.setdefault("id", target_id)
        for field in _AGENT_EDITABLE_FIELDS:
            if field not in patch:
                continue
            value = patch[field]
            if field == "enabled":
                raw[field] = bool(value)
            elif field in {"name", "role", "description", "prompt"}:
                raw[field] = str(value or "").strip()
            elif field == "runtime":
                raw[field] = _normalize_runtime(value, base=raw.get("runtime") if isinstance(raw.get("runtime"), dict) else None)
            elif field == "routing":
                raw[field] = _normalize_routing(value, base=raw.get("routing") if isinstance(raw.get("routing"), dict) else None)
            elif field == "safety":
                raw[field] = _normalize_safety(value, base=raw.get("safety") if isinstance(raw.get("safety"), dict) else None)
            elif field == "identity":
                raw[field] = _normalize_identity(value, base=raw.get("identity") if isinstance(raw.get("identity"), dict) else None)
            elif field == "soul":
                raw[field] = _normalize_soul(value, base=raw.get("soul") if isinstance(raw.get("soul"), dict) else None)
            elif field == "lifecycle":
                raw[field] = _normalize_lifecycle(value, base=raw.get("lifecycle") if isinstance(raw.get("lifecycle"), dict) else None)
            elif field == "ecosystem":
                raw[field] = _normalize_ecosystem(value, base=raw.get("ecosystem") if isinstance(raw.get("ecosystem"), dict) else None)
            elif field == "memory":
                raw[field] = _normalize_memory(value, base=raw.get("memory") if isinstance(raw.get("memory"), dict) else None)
            elif field == "metadata":
                raw[field] = _sanitize_agent_metadata(value, base=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None)
            else:
                raw[field] = sorted(
                    {str(item).strip() for item in _as_list(value) if str(item).strip()}
                )

        _validate_agent_config(raw)
        ss.upsert_hub_agent(
            conn,
            target_id,
            raw,
            builtin=_is_builtin_agent_id(target_id),
            removed=False,
        )
    return get_agent_def(target_id, config=config) or raw or {}


def create_agent_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a custom Agent Hub config entry (a ``hub_agents`` row)."""
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state as ss

    payload = _coerce_agent_payload_aliases(payload)
    _validate_agent_patch(payload)
    name = str(payload.get("name") or payload.get("label") or "").strip()
    requested_id = str(payload.get("id") or payload.get("slug") or "").strip()
    target_id = _slug(requested_id or name)
    if not target_id:
        raise ValueError("agent name or id is required")
    if _is_builtin_agent_id(target_id):
        raise ValueError("built-in agents cannot be recreated")

    config = load_config()
    with connect() as conn:
        _ensure_hub_agents_imported(conn, config)
        existing_ids = {
            str(row.get("agent_id") or "") for row in ss.list_hub_agents(conn)
        } | _builtin_agent_ids()
        if target_id in existing_ids:
            raise ValueError(f"agent '{target_id}' already exists")

        raw = {
            "id": target_id,
            "name": name or target_id.replace("-", " ").title(),
            "role": str(payload.get("role") or "support").strip().lower(),
            "description": str(payload.get("description") or "").strip(),
            "enabled": bool(payload.get("enabled", True)),
            "platforms": _as_list(payload.get("platforms")) or ["local"],
            "session_sources": _as_list(payload.get("session_sources")) or ["cli", "cron"],
            "skills": _as_list(payload.get("skills")),
            "toolsets": _as_list(payload.get("toolsets")),
            "prompt": str(payload.get("prompt") or "").strip(),
            "runtime": _normalize_runtime(payload.get("runtime")),
            "routing": _normalize_routing(payload.get("routing")),
            "safety": _normalize_safety(payload.get("safety")),
            "identity": _normalize_identity(payload.get("identity")),
            "soul": _normalize_soul(payload.get("soul")),
            "lifecycle": _normalize_lifecycle(payload.get("lifecycle")),
            "ecosystem": _normalize_ecosystem(payload.get("ecosystem")),
            "memory": _normalize_memory(payload.get("memory")),
            "metadata": _sanitize_agent_metadata(payload.get("metadata")),
        }
        _validate_agent_config(raw)
        ss.upsert_hub_agent(conn, target_id, raw, builtin=False, removed=False)
    return get_agent_def(target_id, config=config) or raw


def delete_agent_config(agent_id: str) -> dict[str, Any]:
    """Delete an Agent Hub agent.

    The Executive Assistant (the permanent lead) cannot be deleted — disable it
    instead. Every other built-in is removable: deleting it tombstones the
    ``hub_agents`` row (``removed=1``) so reconcile won't re-seed it. Custom
    agents are deleted outright.
    """
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state as ss

    target_id = _slug(str(agent_id or ""))
    if not target_id:
        raise ValueError("agent id is required")
    builtin = _is_builtin_agent_id(target_id)
    if builtin and not _is_removable_default(target_id):
        raise ValueError("the Executive Assistant cannot be deleted; disable it instead")

    with connect() as conn:
        _ensure_hub_agents_imported(conn)
        if builtin:
            # A removable built-in already absent is an idempotent no-op
            # (still ensure it's parked so reconcile won't re-seed it).
            ss.remove_hub_agent(conn, target_id, tombstone=True)
        elif not ss.remove_hub_agent(conn, target_id):
            # Custom agent that doesn't exist is an error.
            raise LookupError(f"Agent '{agent_id}' not found")
    return {"ok": True, "id": target_id, "removable": builtin}


def agent_runtime_defaults(agent_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return sanitized runtime defaults for future agent-owned runs."""
    agent = get_agent_def(agent_id, config=config)
    runtime = agent.get("runtime") if isinstance(agent, dict) else None
    return _normalize_runtime(runtime)


def agent_lifecycle_defaults(agent_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return sanitized lifecycle policy for future agent-owned runs."""
    agent = get_agent_def(agent_id, config=config)
    lifecycle = agent.get("lifecycle") if isinstance(agent, dict) else None
    return _normalize_lifecycle(lifecycle)


def agent_effective_skills(
    agent_id: str,
    extra_skills: Any = None,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Return the skills an agent-owned run should preload.

    Agent Hub owns the agent-level baseline; a cron/heartbeat/handoff can still
    add run-specific skills. Unknown/no-agent runs keep only the explicit
    run-specific skills so legacy generic cron jobs do not inherit agent
    behavior accidentally.
    """
    agent = get_agent_def(agent_id, config=config)
    if not isinstance(agent, dict):
        return _merge_unique(extra_skills)
    return _merge_unique(agent.get("skills"), extra_skills)


def agent_run_context(agent_id: str, config: dict[str, Any] | None = None) -> str:
    """Build a concise Agent Hub context block for scheduled agent runs."""
    agent = get_agent_def(agent_id, config=config)
    if not isinstance(agent, dict):
        return ""
    clean_id = _slug(str(agent.get("id") or agent_id or ""))
    routing = agent.get("routing") if isinstance(agent.get("routing"), dict) else {}
    owns = _as_list(routing.get("owns"))
    handoff_targets = _as_list(routing.get("handoff_targets"))
    escalation = str(routing.get("escalation_target") or "executive-assistant").strip()
    artifact_skills = [skill for skill in AGENT_ARTIFACT_SKILLS if skill in _as_list(agent.get("skills"))]

    lines = [
        "[AGENT HUB CONTEXT]",
        f"You are running as agent: {agent.get('name') or clean_id} ({clean_id}).",
    ]
    role = str(agent.get("role") or "").strip()
    description = str(agent.get("description") or "").strip()
    prompt = str(agent.get("prompt") or "").strip()
    if role:
        lines.append(f"Role: {role}.")
    if description:
        lines.append(f"Specialization: {description}")
    if owns:
        lines.append(f"Owned work areas: {', '.join(owns)}.")
    if handoff_targets:
        lines.append(f"Handoff targets: {', '.join(handoff_targets)}.")
    if escalation:
        lines.append(f"Escalation/default coordinator: {escalation}.")
    lines.append(
        "Default behavior: if the task is outside this agent's specialization, "
        "create or recommend an Elevate-native handoff/task for the best owning "
        "agent instead of trying to silently own that specialist work."
    )
    if artifact_skills:
        lines.append(
            "Shared artifact capability: this agent may produce or coordinate "
            f"PDFs, presentations, diagrams, and graphics using {', '.join(artifact_skills)}."
        )
    if prompt:
        lines.append(f"Agent instruction: {prompt}")
    lines.append("[/AGENT HUB CONTEXT]")
    return "\n".join(lines)


def _utc_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _agent_memory_events_path() -> Path:
    from elevate_cli.data.paths import data_root

    return data_root() / "agent_memory_events.jsonl"


def _redact_memory_fact(text: str) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    clean = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|private[_-]?key|auth[_-]?token)\b\s*[:=]\s*([^\s,;]+)",
        lambda match: f"{match.group(1)}=[redacted]",
        clean,
    )
    clean = re.sub(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}", "Bearer [redacted]", clean)
    clean = re.sub(r"\bsk-[a-zA-Z0-9_-]{12,}\b", "[redacted]", clean)
    return clean


def _memory_fact_items(content: Any, *, limit: int = 200) -> list[str]:
    if isinstance(content, (list, tuple, set)):
        raw_text = "\n\n".join(str(item or "") for item in content)
    else:
        raw_text = str(content or "")
    if not raw_text.strip():
        return []

    facts: list[str] = []
    seen: set[str] = set()
    block: list[str] = []
    in_code = False

    def flush_block() -> None:
        if not block:
            return
        text = " ".join(part.strip() for part in block if part.strip())
        block.clear()
        text = re.sub(r"\s+", " ", text).strip()
        text = _redact_memory_fact(text)
        if not text or len(text) < 3:
            return
        if len(text) > 1200:
            text = text[:1197].rstrip() + "..."
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        facts.append(text)

    for raw_line in raw_text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            flush_block()
            continue
        if in_code:
            continue
        if not line:
            flush_block()
            continue
        if re.match(r"^#{1,6}\s+", line):
            flush_block()
            continue
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
        line = re.sub(r"^\[[ xX]\]\s*", "", line)
        block.append(line)
        if len(" ".join(block)) >= 900:
            flush_block()
        if len(facts) >= limit:
            break
    flush_block()
    return facts[:limit]


def agent_memory_facts(agent_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
    """Return recent native memory facts for an agent."""
    if not str(agent_id or "").strip():
        return []
    clean_agent = _slug(str(agent_id or ""))
    if not clean_agent:
        return []
    path = _agent_memory_events_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-5000:]
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        if _slug(str(rec.get("agent") or "")) != clean_agent:
            continue
        fact = _redact_memory_fact(str(rec.get("fact") or ""))
        if not fact:
            continue
        fact_id = str(rec.get("factId") or rec.get("id") or "").strip()
        key = fact_id or fact.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "id": fact_id,
                "agent": clean_agent,
                "fact": fact,
                "source": str(rec.get("source") or "agent-hub"),
                "actor": str(rec.get("actor") or ""),
                "ts": str(rec.get("ts") or ""),
                "scopes": _as_list(rec.get("scopes")),
            }
        )
    items.sort(key=lambda item: str(item.get("ts") or ""))
    return items[-max(1, min(int(limit or 40), 500)):]


def seed_agent_memory(
    agent_id: str,
    content: Any,
    *,
    source: str = "agent-hub",
    actor: str = "human:web",
    scopes: Any = None,
) -> dict[str, Any]:
    """Seed native per-agent memory facts from imported content."""
    if not str(agent_id or "").strip():
        raise ValueError("agent id is required")
    clean_agent = _slug(str(agent_id or ""))
    if not clean_agent:
        raise ValueError("agent id is required")
    facts = _memory_fact_items(content)
    if not facts:
        return {"agent": clean_agent, "seeded": 0, "duplicates": 0, "source": str(source or "agent-hub")}

    existing = {
        item.get("id") or hashlib.sha256(f"{clean_agent}\0{item.get('fact')}".encode("utf-8")).hexdigest()[:16]
        for item in agent_memory_facts(clean_agent, limit=500)
    }
    path = _agent_memory_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _utc_iso()
    written = 0
    duplicates = 0
    with path.open("a", encoding="utf-8") as fh:
        for fact in facts:
            fact_id = hashlib.sha256(f"{clean_agent}\0{fact}".encode("utf-8")).hexdigest()[:16]
            if fact_id in existing:
                duplicates += 1
                continue
            existing.add(fact_id)
            rec = {
                "kind": "agent_memory_fact",
                "agent": clean_agent,
                "factId": fact_id,
                "fact": fact,
                "source": str(source or "agent-hub"),
                "actor": str(actor or ""),
                "scopes": _as_list(scopes),
                "ts": now,
            }
            fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
            written += 1
    return {
        "agent": clean_agent,
        "seeded": written,
        "duplicates": duplicates,
        "source": str(source or "agent-hub"),
    }


def delete_agent_memory_seed(
    agent_id: str,
    *,
    source: str | None = "cortext-import",
) -> dict[str, Any]:
    """Delete imported native memory facts for one agent.

    This is intentionally scoped for installer cleanup. By default it removes
    only facts whose source is ``cortext-import`` so hand-written/user-learned
    memory survives uninstalling a preset.
    """
    if not str(agent_id or "").strip():
        raise ValueError("agent id is required")
    clean_agent = _slug(str(agent_id or ""))
    if not clean_agent:
        raise ValueError("agent id is required")
    path = _agent_memory_events_path()
    if not path.exists():
        return {"agent": clean_agent, "removed": 0, "source": source}

    wanted_source = str(source or "").strip()
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            kept.append(line)
            continue
        if not isinstance(rec, dict):
            kept.append(line)
            continue
        rec_agent = _slug(str(rec.get("agent") or ""))
        rec_source = str(rec.get("source") or "").strip()
        matches_source = (
            not wanted_source
            or rec_source == wanted_source
            or (
                wanted_source == "cortext-import"
                and rec_source.startswith("cortext-preset:")
            )
        )
        if (
            rec.get("kind") == "agent_memory_fact"
            and rec_agent == clean_agent
            and matches_source
        ):
            removed += 1
            continue
        kept.append(line)

    if removed:
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(path)
    return {"agent": clean_agent, "removed": removed, "source": source}


def _agent_compat(agent: dict[str, Any]) -> dict[str, Any]:
    runtime = _normalize_runtime(agent.get("runtime"))
    safety = _normalize_safety(agent.get("safety"))
    soul = _normalize_soul(agent.get("soul"))
    lifecycle = _normalize_lifecycle(agent.get("lifecycle"))
    crash_window = {
        "seconds": lifecycle.get("crash_window_seconds"),
        "max_crashes": lifecycle.get("crash_window_max"),
    }
    return {
        "cortext": {
            "runtime": runtime.get("runtime_type") or "",
            "runtime_type": runtime.get("runtime_type") or "",
            "model": runtime.get("model") or "",
            "provider": runtime.get("provider") or "",
            "base_url": runtime.get("base_url") or "",
            "working_directory": runtime.get("workdir") or "",
            "timezone": runtime.get("timezone") or "",
            "ctx_warning_threshold": runtime.get("context_warning_threshold"),
            "ctx_handoff_threshold": runtime.get("context_handoff_threshold"),
            "codex_context_cap": runtime.get("codex_context_cap"),
            "dangerously_skip_permissions": bool(safety.get("dangerously_skip_permissions")),
            "approval_rules": {
                "always_ask": _as_list(safety.get("always_ask")),
                "never_ask": _as_list(safety.get("never_ask")),
            },
            "communication_style": soul.get("communication_style") or "",
            "day_mode_start": soul.get("day_mode_start") or "",
            "day_mode_end": soul.get("day_mode_end") or "",
            "startup_delay": lifecycle.get("startup_delay") or 0,
            "max_session_seconds": lifecycle.get("max_session_seconds"),
            "max_crashes_per_day": lifecycle.get("max_crashes_per_day"),
            "crash_window": crash_window,
            "telegram_polling": lifecycle.get("telegram_polling"),
        },
        "notes": [
            "Cortext daemon, IPC, PM2, PTY injection, and file inbox settings are not imported.",
            "dangerously_skip_permissions is preserved for compatibility but does not bypass Elevate safety gates.",
        ],
    }


def fleet_roster_text(config: dict[str, Any] | None = None) -> str:
    """One line per ENABLED agent — name (id) — what it owns. Injected into every
    agent's prompt so it knows who to delegate to (dynamic: reflects whatever
    agents this account has installed, built-in or custom)."""
    try:
        cfg = config if isinstance(config, dict) else load_config()
        defs = _load_agent_defs(cfg)
    except Exception:
        return ""
    lines: list[str] = []
    for a in defs:
        if not isinstance(a, dict) or a.get("enabled") is False:
            continue
        aid = _slug(str(a.get("id") or ""))
        if not aid:
            continue
        name = str(a.get("name") or aid).strip()
        # Prefer the richer description (what it actually owns); fall back to the
        # short role. Trim so the roster stays a tight prompt block.
        desc = str(a.get("description") or a.get("role") or "").strip()
        if len(desc) > 140:
            desc = desc[:139].rstrip() + "…"
        lines.append(f"- {name} ({aid})" + (f" — {desc}" if desc else ""))
    return "\n".join(lines)


def _load_agent_defs(config: dict[str, Any]) -> list[dict[str, Any]]:
    hub_cfg = config.get("agent_hub")
    if not isinstance(hub_cfg, dict):
        hub_cfg = {}
    defaults_by_id = {
        _slug(str(agent.get("id") or "")): copy.deepcopy(agent)
        for agent in DEFAULT_AGENT_DEFS
    }

    stored = _stored_agents()
    if stored is not None:
        raw_agents: Any = stored
    else:
        # Account DB unavailable — degrade to the legacy config.yaml view so
        # reads stay tolerant (pre-0026 behavior).
        raw_agents = hub_cfg.get("agents")
        if raw_agents is None:
            raw_agents = config.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        raw_agents = [copy.deepcopy(agent) for agent in DEFAULT_AGENT_DEFS]
    else:
        raw_agents = [copy.deepcopy(agent) for agent in raw_agents]
        configured_default_ids = {
            _slug(str(agent.get("id") or agent.get("slug") or agent.get("name") or ""))
            for agent in raw_agents
            if isinstance(agent, dict)
        }
        for default in DEFAULT_AGENT_DEFS:
            default_id = _slug(str(default.get("id") or ""))
            if not default_id or default_id in configured_default_ids:
                continue
            # Only the always-on agent (EA) is auto-added. Every other native
            # default is installable from the Agent Library, not auto-shown.
            if not _is_auto_seed_default(default_id):
                continue
            raw_agents.append(copy.deepcopy(default))
            configured_default_ids.add(default_id)

    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_agents):
        if not isinstance(raw, dict):
            continue
        raw = _coerce_agent_payload_aliases(raw)
        name = str(raw.get("name") or raw.get("label") or "").strip()
        agent_id = str(raw.get("id") or raw.get("slug") or _slug(name)).strip()
        if not agent_id:
            agent_id = f"agent-{index + 1}"
        agent_id = _slug(agent_id)
        if agent_id in seen:
            suffix = 2
            base = agent_id
            while f"{base}-{suffix}" in seen:
                suffix += 1
            agent_id = f"{base}-{suffix}"
        seen.add(agent_id)
        default = defaults_by_id.get(agent_id, {})
        metadata = default.get("metadata") if isinstance(default.get("metadata"), dict) else {}
        raw_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        default_runtime = default.get("runtime") if isinstance(default.get("runtime"), dict) else {}
        raw_runtime = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
        default_routing = default.get("routing") if isinstance(default.get("routing"), dict) else {}
        raw_routing = raw.get("routing") if isinstance(raw.get("routing"), dict) else {}
        default_safety = default.get("safety") if isinstance(default.get("safety"), dict) else {}
        raw_safety = raw.get("safety") if isinstance(raw.get("safety"), dict) else {}
        default_identity = default.get("identity") if isinstance(default.get("identity"), dict) else {}
        raw_identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        default_soul = default.get("soul") if isinstance(default.get("soul"), dict) else {}
        raw_soul = raw.get("soul") if isinstance(raw.get("soul"), dict) else {}
        default_lifecycle = default.get("lifecycle") if isinstance(default.get("lifecycle"), dict) else {}
        raw_lifecycle = raw.get("lifecycle") if isinstance(raw.get("lifecycle"), dict) else {}
        default_ecosystem = default.get("ecosystem") if isinstance(default.get("ecosystem"), dict) else {}
        raw_ecosystem = raw.get("ecosystem") if isinstance(raw.get("ecosystem"), dict) else {}
        default_memory = default.get("memory") if isinstance(default.get("memory"), dict) else {}
        raw_memory = raw.get("memory") if isinstance(raw.get("memory"), dict) else {}
        if not name:
            name = str(default.get("name") or agent_id.replace("-", " ").title()).strip()
        agent = {
            "id": agent_id,
            "name": name,
            "role": str(raw.get("role") or default.get("role") or "support").strip().lower(),
            "description": str(raw.get("description") or default.get("description") or "").strip(),
            "enabled": bool(raw.get("enabled", True)),
            "platforms": _merge_unique(default.get("platforms"), raw.get("platforms")),
            "session_sources": _merge_unique(default.get("session_sources"), raw.get("session_sources")),
            "skills": _merge_unique(SHARED_AGENT_SKILLS, default.get("skills"), raw.get("skills")),
            "toolsets": _merge_unique(SHARED_AGENT_TOOLSETS, default.get("toolsets"), raw.get("toolsets")),
            "prompt": str(
                raw.get("prompt") or raw.get("system_prompt") or default.get("prompt") or ""
            ).strip(),
            "runtime": _normalize_runtime(raw_runtime, base=default_runtime),
            "routing": _normalize_routing(raw_routing, base=default_routing),
            "safety": _normalize_safety(raw_safety, base=default_safety),
            "identity": _normalize_identity(raw_identity, base=default_identity),
            "soul": _normalize_soul(raw_soul, base=default_soul),
            "lifecycle": _normalize_lifecycle(raw_lifecycle, base=default_lifecycle),
            "ecosystem": _normalize_ecosystem(raw_ecosystem, base=default_ecosystem),
            "memory": _normalize_memory(raw_memory, base=default_memory),
            "canDelete": _slug(agent_id) not in PERMANENT_AGENT_IDS,
            "builtin": _is_builtin_agent_id(agent_id),
            "metadata": {**dict(metadata), **dict(raw_metadata)},
        }
        agent["compat"] = _agent_compat(agent)
        agents.append(agent)
    return agents


def get_agent_def(
    agent_id: str, config: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Resolve a single merged agent definition by id.

    Public accessor used by the gateway to apply a selected agent lane to a
    live session. Returns the merged def (config overrides folded over the
    built-in defaults) or ``None`` if the id is unknown.
    """
    wanted = _slug(str(agent_id or ""))
    if not wanted:
        return None
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    for agent in _load_agent_defs(config or {}):
        if _slug(str(agent.get("id") or "")) == wanted:
            return agent
    return None


def agent_is_enabled(agent_id: str, config: dict[str, Any] | None = None) -> bool:
    """Return whether an Agent Hub agent may start new work.

    Unknown agents are treated as disabled for agent-scoped execution gates.
    This keeps "Run as agent" / scoped worker paths from silently falling back
    to a default persona when the operator expected a named agent.
    """
    agent = get_agent_def(agent_id, config=config)
    if not agent:
        return False
    return bool(agent.get("enabled", True))


def _session_summary(limit: int = 100, *, include_total: bool = True) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": 0,
        "active": 0,
        "recent": [],
        "by_source": {},
        "by_day": {},
        "error": "",
    }
    try:
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, include_children=False)
            summary["total"] = db.session_count() if include_total else len(sessions)
        finally:
            db.close()
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    now = time.time()
    recent: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}
    by_day: dict[str, int] = {}
    active = 0
    for row in sessions:
        source = str(row.get("source") or "unknown")
        started = float(row.get("started_at") or 0)
        last_active = float(row.get("last_active") or started or 0)
        is_active = row.get("ended_at") is None and now - last_active < 300
        if is_active:
            active += 1
        day = datetime.fromtimestamp(started).date().isoformat() if started else "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        by_day[day] = by_day.get(day, 0) + 1
        recent.append(
            {
                "id": row.get("id"),
                "title": row.get("title") or row.get("preview") or row.get("id"),
                "source": source,
                "started_at": started,
                "last_active": last_active,
                "is_active": is_active,
                "message_count": int(row.get("message_count") or 0),
                "tool_call_count": int(row.get("tool_call_count") or 0),
                "model": row.get("model") or "",
            }
        )

    summary["active"] = active
    summary["recent"] = recent[:20]
    summary["by_source"] = dict(sorted(by_source.items()))
    summary["by_day"] = dict(sorted(by_day.items(), reverse=True)[:14])
    return summary


def _platform_summary(runtime: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        from gateway.config import load_gateway_config
        from gateway.pairing import PairingStore

        gw_config = load_gateway_config()
        connected = {platform.value for platform in gw_config.get_connected_platforms()}
        pairing_store = PairingStore()
    except Exception as exc:
        return [{"name": "gateway", "error": str(exc)}]

    runtime_platforms = (runtime or {}).get("platforms") or {}
    platforms: list[dict[str, Any]] = []
    for platform, platform_cfg in sorted(
        gw_config.platforms.items(),
        key=lambda item: item[0].value,
    ):
        name = platform.value
        approved = []
        pending = []
        try:
            approved = pairing_store.list_approved(name)
            pending = pairing_store.list_pending(name)
        except Exception:
            approved = []
            pending = []
        runtime_state = runtime_platforms.get(name) if isinstance(runtime_platforms, dict) else {}
        home = platform_cfg.home_channel.to_dict() if platform_cfg.home_channel else None
        extra = platform_cfg.extra if isinstance(platform_cfg.extra, dict) else {}
        agent_bots = extra.get("agent_bots")
        has_agent_bot_token = (
            isinstance(agent_bots, dict)
            and any((bot.get("token") if isinstance(bot, dict) else None) for bot in agent_bots.values())
        )
        platforms.append(
            {
                "name": name,
                "enabled": bool(platform_cfg.enabled),
                "configured": name in connected,
                "token_configured": bool(platform_cfg.token or extra.get("token") or has_agent_bot_token),
                "api_key_configured": bool(platform_cfg.api_key),
                "home_channel": home,
                "reply_to_mode": platform_cfg.reply_to_mode,
                "runtime": runtime_state,
                "approved_users": len(approved),
                "pending_pairings": [
                    {
                        "code": item.get("code"),
                        "user_id": item.get("user_id"),
                        "user_name": item.get("user_name") or "",
                        "age_minutes": item.get("age_minutes"),
                    }
                    for item in pending
                ],
            }
        )
    return platforms


def _env_value(name: str) -> str:
    try:
        return str(get_env_value(name) or "").strip()
    except Exception:
        return ""


def _agent_telegram_lane(agent: dict[str, Any]) -> dict[str, Any]:
    """Return redacted readiness for one agent's Telegram lane."""
    try:
        from gateway.agent_lanes import (
            agent_telegram_bot_token,
            agent_telegram_bot_token_env_vars,
            agent_telegram_env_vars,
            agent_telegram_uses_shared_bot,
            parse_telegram_target,
        )
    except Exception:
        return {
            "configured": False,
            "tokenConfigured": False,
            "targetConfigured": False,
            "error": "agent lane helpers unavailable",
        }

    agent_id = str(agent.get("id") or "")
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    token_envs = [
        str(metadata.get("telegram_bot_token_env") or "").strip(),
        *agent_telegram_bot_token_env_vars(agent_id),
    ]
    target_envs = [
        str(metadata.get("telegram_target_env") or "").strip(),
        *agent_telegram_env_vars(agent_id),
    ]
    token_env = ""
    token_value = ""
    token_configured = False
    for env_name in dict.fromkeys(name for name in token_envs if name):
        if _env_value(env_name):
            token_env = env_name
            token_value = agent_telegram_bot_token(agent_id)
            token_configured = True
            break
    target_env = ""
    target_value = ""
    for env_name in dict.fromkeys(name for name in target_envs if name):
        value = _env_value(env_name)
        if value:
            target_env = env_name
            target_value = value
            break
    chat_id, topic_id = parse_telegram_target(target_value)
    target_configured = bool(chat_id)
    uses_shared_bot = bool(
        (token_env and not token_env.startswith("ELEVATE_AGENT_"))
        or agent_telegram_uses_shared_bot(agent_id)
    )
    return {
        "configured": token_configured and target_configured and not uses_shared_bot,
        "tokenConfigured": token_configured,
        "targetConfigured": target_configured,
        "tokenEnv": token_env or (token_envs[0] if token_envs else ""),
        "targetEnv": target_env or (target_envs[0] if target_envs else ""),
        "chatConfigured": bool(chat_id),
        "topicConfigured": bool(topic_id),
        "usesSharedBot": uses_shared_bot,
        "duplicateSharedBot": bool(token_value and uses_shared_bot),
    }


def _cron_summary() -> dict[str, Any]:
    try:
        from cron.jobs import list_jobs

        jobs = list_jobs(include_disabled=True)
    except Exception as exc:
        return {"total": 0, "enabled": 0, "paused": 0, "recent": [], "error": str(exc)}

    recent = []
    enabled = 0
    paused = 0
    for job in jobs:
        if bool(job.get("enabled", True)):
            enabled += 1
        else:
            paused += 1
        recent.append(
            {
                "id": job.get("id"),
                "name": job.get("name") or job.get("prompt", "")[:40],
                "schedule": job.get("schedule"),
                "enabled": bool(job.get("enabled", True)),
                "deliver": job.get("deliver") or "",
            }
        )
    return {
        "total": len(jobs),
        "enabled": enabled,
        "paused": paused,
        "recent": recent[:10],
        "error": "",
    }


def _skills_summary(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from elevate_cli.skills_config import get_disabled_skills
        from tools.skills_tool import _find_all_skills

        disabled = get_disabled_skills(config)
        skills = _find_all_skills(skip_disabled=True)
    except Exception as exc:
        return {
            "total": 0,
            "enabled": 0,
            "disabled": 0,
            "categories": {},
            "available": [],
            "error": str(exc),
        }

    categories: dict[str, int] = {}
    enabled = 0
    available: list[dict[str, str]] = []
    for skill in skills:
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        if name not in disabled:
            enabled += 1
        category = str(skill.get("category") or "general")
        categories[category] = categories.get(category, 0) + 1
        available.append(
            {
                "name": name,
                "category": category,
                "description": str(skill.get("description") or "").strip(),
            }
        )
    available.sort(key=lambda entry: (entry["category"], entry["name"]))
    return {
        "total": len(skills),
        "enabled": enabled,
        "disabled": len(skills) - enabled,
        "categories": dict(sorted(categories.items())),
        "available": available,
        "error": "",
    }


def _toolsets_summary(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from elevate_cli.tools_config import (
            _get_effective_configurable_toolsets,
            _get_platform_tools,
        )

        enabled = set(
            _get_platform_tools(
                config,
                "cli",
                include_default_mcp_servers=False,
            )
        )
        known = [
            {"name": name, "label": label, "description": desc, "enabled": name in enabled}
            for name, label, desc in _get_effective_configurable_toolsets()
        ]
    except Exception as exc:
        return {"total": 0, "enabled": [], "known": [], "error": str(exc)}
    return {
        "total": len(known),
        "enabled": sorted(enabled),
        "known": known,
        "error": "",
    }


def _resolve_memory_db_path(config: dict[str, Any]) -> Path:
    plugin_cfg = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    memory_cfg = plugin_cfg.get("elevate-memory-store") if isinstance(plugin_cfg, dict) else {}
    if not isinstance(memory_cfg, dict):
        memory_cfg = {}
    default = get_elevate_home() / "memory_store.db"
    db_path = str(memory_cfg.get("db_path") or default)
    db_path = db_path.replace("$ELEVATE_HOME", str(get_elevate_home()))
    db_path = db_path.replace("${ELEVATE_HOME}", str(get_elevate_home()))
    return Path(db_path).expanduser()


def _sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ?
            LIMIT 1
            """,
            (table,),
        ).fetchone()
        return bool(row)
    except Exception:
        try:
            if hasattr(conn, "rollback"):
                conn.rollback()
        except Exception:
            pass
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return bool(row)


def _safe_count_table(conn: sqlite3.Connection, table: str, where: str = "") -> int:
    if not _table_exists(conn, table):
        return 0
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql).fetchone()[0] or 0)


def _json_list(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _add_node(nodes: list[dict[str, Any]], seen: set[str], node: dict[str, Any]) -> None:
    node_id = str(node.get("id") or "")
    if not node_id or node_id in seen:
        return
    seen.add(node_id)
    nodes.append(node)


def _add_edge(edges: list[dict[str, Any]], seen: set[tuple[str, str, str]], source: str, target: str, edge_type: str) -> None:
    if not source or not target or source == target:
        return
    key = (source, target, edge_type)
    if key in seen:
        return
    seen.add(key)
    edges.append({"source": source, "target": target, "type": edge_type})


def _clip_label(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _memory_summary(config: dict[str, Any], *, include_graph: bool = True) -> dict[str, Any]:
    memory_cfg = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    provider = str(memory_cfg.get("provider") or "builtin").strip()
    plugin_cfg = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    plugin_cfg = plugin_cfg.get("elevate-memory-store") if isinstance(plugin_cfg, dict) else {}
    plugin_cfg = plugin_cfg if isinstance(plugin_cfg, dict) else {}
    db_path = _resolve_memory_db_path(config)
    summary: dict[str, Any] = {
        "provider": provider,
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "facts": 0,
        "entities": 0,
        "embeddings": 0,
        "indexed_facts": 0,
        "documents": 0,
        "chunks": 0,
        "indexed_chunks": 0,
        "community_reports": 0,
        "relations": 0,
        "modal_assets": 0,
        "journal": {
            "total": 0,
            "pending": 0,
            "processed": 0,
            "failed": 0,
            "active_session_count": 0,
            "session_segment_count": 0,
            "sessions": [],
        },
        "embedding": {
            "enabled": str(plugin_cfg.get("embedding_enabled", "false")).lower() in {"1", "true", "yes", "on"},
            "provider": str(plugin_cfg.get("embedding_provider") or "openai"),
            "model": str(plugin_cfg.get("embedding_model") or "text-embedding-3-small"),
            "api_key_env": str(plugin_cfg.get("embedding_api_key_env") or "OPENAI_API_KEY"),
        },
        "graph": {"nodes": [], "edges": []},
        "activity": {},
        "error": "",
    }
    try:
        from plugins.memory.holographic.activity import snapshot as activity_snapshot

        summary["activity"] = activity_snapshot()
    except Exception:
        summary["activity"] = {}

    try:
        from elevate_cli.data import connect

        with connect() as conn:
            summary["db_path"] = "embedded-postgres:elevate_operational"
            summary["db_exists"] = True
            summary["facts"] = _safe_count_table(conn, "memory_facts")
            summary["entities"] = _safe_count_table(conn, "memory_entities")
            summary["embeddings"] = _safe_count_table(conn, "memory_embeddings")
            summary["indexed_facts"] = _safe_count_table(conn, "memory_embeddings", "target_type = 'fact'")
            summary["documents"] = _safe_count_table(conn, "memory_documents")
            summary["chunks"] = _safe_count_table(conn, "memory_chunks")
            summary["indexed_chunks"] = _safe_count_table(conn, "memory_embeddings", "target_type = 'chunk'")
            summary["community_reports"] = _safe_count_table(conn, "memory_community_reports")
            summary["relations"] = _safe_count_table(conn, "memory_relations")
            summary["modal_assets"] = _safe_count_table(conn, "memory_modal_assets")
            journal_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM memory_turn_journal
                GROUP BY status
                """
            ).fetchall()
            counts = {str(row["status"]): int(row["count"] or 0) for row in journal_rows}
            session_rows = conn.execute(
                """
                SELECT session_id,
                       session_day,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                       MAX(created_at) AS latest_created_at
                FROM memory_turn_journal
                GROUP BY session_id, session_day
                ORDER BY latest_created_at DESC, session_id ASC, session_day DESC
                LIMIT 20
                """
            ).fetchall()
            sessions = [
                {
                    "session_id": row["session_id"],
                    "session_day": row["session_day"],
                    "total": int(row["total"] or 0),
                    "pending": int(row["pending"] or 0),
                    "processed": int(row["processed"] or 0),
                    "failed": int(row["failed"] or 0),
                    "latest_created_at": str(row["latest_created_at"]) if row["latest_created_at"] is not None else None,
                }
                for row in session_rows
            ]
            summary["journal"] = {
                "total": sum(counts.values()),
                "pending": counts.get("pending", 0),
                "processed": counts.get("processed", 0),
                "failed": counts.get("failed", 0),
                "active_session_count": len({row["session_id"] for row in sessions}),
                "session_segment_count": len(sessions),
                "sessions": sessions,
            }
            if include_graph:
                summary["graph"] = _memory_graph(conn)
        return summary
    except Exception as exc:
        summary["error"] = str(exc)

    if not db_path.exists():
        return summary

    try:
        conn = _sqlite_connect_readonly(db_path)
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    try:
        summary["facts"] = _safe_count_table(conn, "facts")
        summary["entities"] = _safe_count_table(conn, "entities")
        summary["embeddings"] = _safe_count_table(conn, "memory_embeddings")
        summary["indexed_facts"] = _safe_count_table(conn, "memory_embeddings", "target_type = 'fact'")
        summary["documents"] = _safe_count_table(conn, "memory_documents")
        summary["chunks"] = _safe_count_table(conn, "memory_chunks")
        summary["indexed_chunks"] = _safe_count_table(conn, "memory_embeddings", "target_type = 'chunk'")
        summary["community_reports"] = _safe_count_table(conn, "memory_community_reports")
        summary["relations"] = _safe_count_table(conn, "memory_relations")
        summary["modal_assets"] = _safe_count_table(conn, "memory_modal_assets")
        journal_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM memory_turn_journal
            GROUP BY status
            """
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in journal_rows}
        session_rows = conn.execute(
            """
            SELECT session_id,
                   session_day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   MAX(created_at) AS latest_created_at
            FROM memory_turn_journal
            GROUP BY session_id, session_day
            ORDER BY latest_created_at DESC, session_id ASC, session_day DESC
            LIMIT 20
            """
        ).fetchall()
        sessions = [
            {
                "session_id": row["session_id"],
                "session_day": row["session_day"],
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
                "processed": int(row["processed"] or 0),
                "failed": int(row["failed"] or 0),
                "latest_created_at": row["latest_created_at"],
            }
            for row in session_rows
        ]
        summary["journal"] = {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processed": counts.get("processed", 0),
            "failed": counts.get("failed", 0),
            "active_session_count": len({row["session_id"] for row in sessions}),
            "session_segment_count": len(sessions),
            "sessions": sessions,
        }
        if include_graph:
            summary["graph"] = _memory_graph(conn)
    except Exception as exc:
        summary["error"] = str(exc)
    finally:
        conn.close()
    return summary


def _memory_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the Hub graph view over the native RAG/memory graph.

    The dashboard should reflect the same primitives used by native RAG: facts,
    entities, document chunks, clusters/community reports, explicit relations,
    and multimodal asset placeholders. Keep it read-only and bounded.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    entity_rows = conn.execute(
        """
        SELECT e.entity_id,
               e.name,
               COUNT(DISTINCT fe.fact_id) AS fact_count,
               COUNT(DISTINCT ce.chunk_id) AS chunk_count
        FROM memory_entities e
        LEFT JOIN memory_fact_entities fe ON fe.entity_id = e.entity_id
        LEFT JOIN memory_chunk_entities ce ON ce.entity_id = e.entity_id
        GROUP BY e.entity_id, e.name
        ORDER BY (COUNT(DISTINCT fe.fact_id) + COUNT(DISTINCT ce.chunk_id)) DESC, e.name ASC
        LIMIT 24
        """
    ).fetchall()
    fact_rows = conn.execute(
        """
        SELECT fact_id, content, category, trust_score
        FROM memory_facts
        WHERE COALESCE(status, 'active') = 'active'
        ORDER BY updated_at DESC, fact_id DESC
        LIMIT 18
        """
    ).fetchall()
    chunk_rows = conn.execute(
        """
        SELECT c.chunk_id, c.document_id, c.content, c.source_excerpt, d.title, d.source_type, d.source_uri
        FROM memory_chunks c
        JOIN memory_documents d ON d.document_id = c.document_id
        ORDER BY c.updated_at DESC, c.chunk_id DESC
        LIMIT 16
        """
    ).fetchall()
    doc_rows = conn.execute(
        """
        SELECT d.document_id, d.title, d.source_type, d.source_uri, COUNT(c.chunk_id) AS chunk_count
        FROM memory_documents d
        LEFT JOIN memory_chunks c ON c.document_id = d.document_id
        GROUP BY d.document_id, d.title, d.source_type, d.source_uri
        ORDER BY d.updated_at DESC, d.document_id DESC
        LIMIT 10
        """
    ).fetchall()
    community_rows = conn.execute(
        """
        SELECT community_id, name, summary, tags, entity_names, fact_ids_json, chunk_ids_json, weight
        FROM memory_community_reports
        ORDER BY updated_at DESC, weight DESC
        LIMIT 10
        """
    ).fetchall()

    entity_ids = {int(row["entity_id"]) for row in entity_rows}
    fact_ids = {int(row["fact_id"]) for row in fact_rows}
    chunk_ids = {int(row["chunk_id"]) for row in chunk_rows}
    document_ids = {int(row["document_id"]) for row in doc_rows}

    for row in entity_rows:
        fact_count = int(row["fact_count"] or 0)
        chunk_count = int(row["chunk_count"] or 0)
        _add_node(
            nodes,
            seen_nodes,
            {
                "id": f"entity:{row['entity_id']}",
                "label": row["name"],
                "type": "entity",
                "weight": fact_count + chunk_count,
                "category": "entity",
            },
        )
    for row in fact_rows:
        _add_node(
            nodes,
            seen_nodes,
            {
                "id": f"fact:{row['fact_id']}",
                "label": _clip_label(row["content"]),
                "type": "fact",
                "weight": max(float(row["trust_score"] or 0), 0.2) * 6,
                "category": row["category"] or "fact",
            },
        )
    for row in doc_rows:
        _add_node(
            nodes,
            seen_nodes,
            {
                "id": f"document:{row['document_id']}",
                "label": _clip_label(row["title"] or row["source_uri"], 72),
                "type": "document",
                "weight": max(int(row["chunk_count"] or 0), 1),
                "category": row["source_type"] or "document",
            },
        )
    for row in chunk_rows:
        label = row["source_excerpt"] or row["content"] or row["title"]
        _add_node(
            nodes,
            seen_nodes,
            {
                "id": f"chunk:{row['chunk_id']}",
                "label": _clip_label(label, 72),
                "type": "chunk",
                "weight": 2,
                "category": row["source_type"] or "chunk",
            },
        )
        _add_edge(edges, seen_edges, f"document:{row['document_id']}", f"chunk:{row['chunk_id']}", "contains")
    for row in community_rows:
        _add_node(
            nodes,
            seen_nodes,
            {
                "id": f"community:{row['community_id']}",
                "label": _clip_label(row["name"] or row["summary"] or row["community_id"], 72),
                "type": "community",
                "weight": max(float(row["weight"] or 1.0), 1.0) * 3,
                "category": "community",
            },
        )

    if _table_exists(conn, "memory_modal_assets"):
        asset_rows = conn.execute(
            """
            SELECT a.asset_id, a.document_id, a.asset_type, a.locator, a.summary
            FROM memory_modal_assets a
            ORDER BY a.updated_at DESC, a.asset_id DESC
            LIMIT 12
            """
        ).fetchall()
        for row in asset_rows:
            _add_node(
                nodes,
                seen_nodes,
                {
                    "id": f"asset:{row['asset_id']}",
                    "label": _clip_label(row["summary"] or row["locator"] or row["asset_type"], 64),
                    "type": "asset",
                    "weight": 1.6,
                    "category": row["asset_type"] or "asset",
                },
            )
            _add_edge(edges, seen_edges, f"document:{row['document_id']}", f"asset:{row['asset_id']}", "has_asset")
            document_ids.add(int(row["document_id"]))

    if entity_ids and fact_ids:
        placeholders_entities = ",".join("?" for _ in entity_ids)
        placeholders_facts = ",".join("?" for _ in fact_ids)
        rows = conn.execute(
            f"""
            SELECT entity_id, fact_id
            FROM memory_fact_entities
            WHERE entity_id IN ({placeholders_entities})
              AND fact_id IN ({placeholders_facts})
            LIMIT 80
            """,
            [*entity_ids, *fact_ids],
        ).fetchall()
        for row in rows:
            _add_edge(edges, seen_edges, f"entity:{row['entity_id']}", f"fact:{row['fact_id']}", "mentions")

    if entity_ids and chunk_ids:
        placeholders_entities = ",".join("?" for _ in entity_ids)
        placeholders_chunks = ",".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"""
            SELECT entity_id, chunk_id
            FROM memory_chunk_entities
            WHERE entity_id IN ({placeholders_entities})
              AND chunk_id IN ({placeholders_chunks})
            LIMIT 80
            """,
            [*entity_ids, *chunk_ids],
        ).fetchall()
        for row in rows:
            _add_edge(edges, seen_edges, f"entity:{row['entity_id']}", f"chunk:{row['chunk_id']}", "chunk_mentions")

    if entity_ids and _table_exists(conn, "memory_relations"):
        placeholders_entities = ",".join("?" for _ in entity_ids)
        rows = conn.execute(
            f"""
            SELECT source_entity_id, target_entity_id, relation_type
            FROM memory_relations
            WHERE source_entity_id IN ({placeholders_entities})
               OR target_entity_id IN ({placeholders_entities})
            ORDER BY weight DESC, updated_at DESC
            LIMIT 80
            """,
            [*entity_ids, *entity_ids],
        ).fetchall()
        for row in rows:
            source = f"entity:{row['source_entity_id']}"
            target = f"entity:{row['target_entity_id']}"
            if source in seen_nodes and target in seen_nodes:
                _add_edge(edges, seen_edges, source, target, row["relation_type"] or "related")

    for row in community_rows:
        community_id = f"community:{row['community_id']}"
        for fact_id in _json_list(row["fact_ids_json"])[:8]:
            target = f"fact:{fact_id}"
            if target in seen_nodes:
                _add_edge(edges, seen_edges, community_id, target, "summarizes_fact")
        for chunk_id in _json_list(row["chunk_ids_json"])[:8]:
            target = f"chunk:{chunk_id}"
            if target in seen_nodes:
                _add_edge(edges, seen_edges, community_id, target, "summarizes_chunk")
        entity_names = [name.strip() for name in str(row["entity_names"] or "").split(",") if name.strip()]
        if entity_names:
            placeholders = ",".join("?" for _ in entity_names[:8])
            entity_matches = conn.execute(
                f"SELECT entity_id FROM memory_entities WHERE name IN ({placeholders}) LIMIT 8",
                entity_names[:8],
            ).fetchall()
            for entity in entity_matches:
                target = f"entity:{entity['entity_id']}"
                if target in seen_nodes:
                    _add_edge(edges, seen_edges, community_id, target, "summarizes_entity")

    return {"nodes": nodes[:90], "edges": edges[:180]}


def _agent_queue_summaries(
    handoffs: dict[str, Any],
    agent_worker: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    worker = agent_worker if isinstance(agent_worker, dict) else {}
    recovered = worker.get("recovered") if isinstance(worker.get("recovered"), dict) else {}
    last_worker_agent = str(worker.get("agentId") or "").strip()
    last_worker_tick = worker.get("lastTickAt")
    by_agent = handoffs.get("byAgent") if isinstance(handoffs.get("byAgent"), list) else []
    summaries: dict[str, dict[str, Any]] = {}
    for row in by_agent:
        if not isinstance(row, dict):
            continue
        agent_id = _slug(str(row.get("agentId") or ""))
        if not agent_id:
            continue
        summaries[agent_id] = {
            "total": int(row.get("total") or 0),
            "queued": int(row.get("queued") or 0),
            "running": int(row.get("running") or 0),
            "waitingHuman": int(row.get("waitingHuman") or 0),
            "completed": int(row.get("completed") or 0),
            "failed": int(row.get("failed") or 0),
            "staleRecovered": int(recovered.get("staleHandoffs") or 0) if last_worker_agent == agent_id else 0,
            "lastWorkerTickAt": last_worker_tick,
        }
    return summaries


def _job_agent_id(job: dict[str, Any]) -> str:
    agent_id = str(job.get("agent") or "").strip()
    if agent_id:
        return _slug(agent_id)
    origin = job.get("origin") if isinstance(job.get("origin"), dict) else {}
    for key in ("agent", "agentId", "to_agent_id", "toAgentId"):
        agent_id = str(origin.get(key) or "").strip()
        if agent_id:
            return _slug(agent_id)
    return ""


def _agent_automation_summaries() -> dict[str, dict[str, Any]]:
    try:
        from cron.jobs import list_jobs

        jobs = list_jobs(include_disabled=True)
    except Exception:
        return {}

    summaries: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        agent_id = _job_agent_id(job)
        if not agent_id:
            continue
        summary = summaries.setdefault(
            agent_id,
            {
                "total": 0,
                "enabled": 0,
                "paused": 0,
                "failures": 0,
                "nextRunAt": None,
                "lastRunAt": None,
            },
        )
        summary["total"] += 1
        if bool(job.get("enabled", True)):
            summary["enabled"] += 1
        else:
            summary["paused"] += 1
        if job.get("last_error") or str(job.get("last_status") or "").lower() == "failed":
            summary["failures"] += 1
        next_run_at = str(job.get("next_run_at") or "").strip()
        if next_run_at and (not summary["nextRunAt"] or next_run_at < str(summary["nextRunAt"])):
            summary["nextRunAt"] = next_run_at
        last_run_at = str(job.get("last_run_at") or "").strip()
        if last_run_at and (not summary["lastRunAt"] or last_run_at > str(summary["lastRunAt"])):
            summary["lastRunAt"] = last_run_at
    return summaries


def _context_pressure_summaries() -> dict[str, dict[str, Any]]:
    try:
        from elevate_cli.data.paths import data_root

        path = data_root() / "agent_context_pressure.jsonl"
        if not path.exists():
            return {}
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except Exception:
        return {}
    summaries: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        agent_id = _slug(str(rec.get("agent") or ""))
        if not agent_id:
            continue
        current = summaries.get(agent_id)
        ts = str(rec.get("ts") or "")
        if current and ts <= str(current.get("lastEventAt") or ""):
            continue
        summaries[agent_id] = {
            "lastEventAt": ts or None,
            "kind": rec.get("kind") or "",
            "percent": rec.get("percent"),
            "tokens": rec.get("tokens"),
            "contextLimit": rec.get("contextLimit"),
            "status": rec.get("status") or "",
            "detail": rec.get("detail") or "",
            "thresholds": rec.get("thresholds") if isinstance(rec.get("thresholds"), dict) else {},
        }
    return summaries


def _approval_blocker_summaries() -> dict[str, int]:
    try:
        from elevate_cli.data import connect, surface_tasks

        with connect() as conn:
            approvals = surface_tasks.list_approvals(conn, status="pending")
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for approval in approvals:
        if not isinstance(approval, dict):
            continue
        agent_id = _slug(str(approval.get("surface") or ""))
        if not agent_id:
            continue
        counts[agent_id] = counts.get(agent_id, 0) + 1
    return counts


def _lifecycle_status_summaries(agent_ids: list[str]) -> dict[str, dict[str, Any]]:
    try:
        from elevate_cli.agent_policy import agent_lifecycle_status
        from elevate_cli.data import connect

        with connect() as conn:
            return {
                agent_id: agent_lifecycle_status(agent_id, conn=conn)
                for agent_id in agent_ids
            }
    except Exception:
        return {}


def _agent_memory_summary(agent: dict[str, Any], queue_summary: dict[str, Any]) -> dict[str, Any]:
    memory = _normalize_memory(agent.get("memory"))
    agent_id = _slug(str(agent.get("id") or ""))
    facts = agent_memory_facts(agent_id, limit=500) if agent_id else []
    recent_facts = facts[-3:]
    return {
        "mode": memory.get("mode"),
        "scopes": memory.get("scopes") or [],
        "sources": memory.get("sources") or [],
        "recallPolicy": memory.get("recall_policy"),
        "writePolicy": memory.get("write_policy"),
        "handoffPolicy": memory.get("handoff_policy"),
        "nativeFacts": len(facts),
        "nativeFactsCapped": len(facts) >= 500,
        "lastMemoryAt": (facts[-1].get("ts") if facts else None),
        "recentFacts": [
            {
                "id": item.get("id"),
                "fact": item.get("fact"),
                "source": item.get("source"),
                "ts": item.get("ts"),
            }
            for item in recent_facts
        ],
        "handoffResults": int(queue_summary.get("completed") or 0),
        "handoffFailures": int(queue_summary.get("failed") or 0),
    }


_EMPTY_QUEUE_SUMMARY: dict[str, Any] = {
    "total": 0,
    "queued": 0,
    "running": 0,
    "waitingHuman": 0,
    "completed": 0,
    "failed": 0,
    "staleRecovered": 0,
    "lastWorkerTickAt": None,
}

_EMPTY_AUTOMATION_SUMMARY: dict[str, Any] = {
    "total": 0,
    "enabled": 0,
    "paused": 0,
    "failures": 0,
    "nextRunAt": None,
    "lastRunAt": None,
}

_EMPTY_CONTEXT_PRESSURE: dict[str, Any] = {
    "lastEventAt": None,
    "kind": "",
    "percent": None,
    "tokens": None,
    "contextLimit": None,
    "status": "",
    "detail": "",
    "thresholds": {},
}


def _agent_summaries(
    config: dict[str, Any],
    *,
    gateway_running: bool,
    sessions: dict[str, Any],
    model: dict[str, Any],
    handoffs: dict[str, Any],
    agent_worker: dict[str, Any],
) -> list[dict[str, Any]]:
    agents = _load_agent_defs(config)
    by_source = sessions.get("by_source") if isinstance(sessions.get("by_source"), dict) else {}
    recent_sessions = sessions.get("recent") if isinstance(sessions.get("recent"), list) else []
    global_toolsets = _as_list(config.get("toolsets"))
    queue_by_agent = _agent_queue_summaries(handoffs, agent_worker)
    automations_by_agent = _agent_automation_summaries()
    agent_ids = [_slug(str(agent.get("id") or "")) for agent in agents]
    lifecycle_by_agent = _lifecycle_status_summaries([agent_id for agent_id in agent_ids if agent_id])
    context_by_agent = _context_pressure_summaries()
    approval_blockers = _approval_blocker_summaries()

    result: list[dict[str, Any]] = []
    for agent in agents:
        agent_id = _slug(str(agent.get("id") or ""))
        sources = agent["session_sources"] or agent["platforms"] or ["cli"]
        source_set = set(sources)
        telegram_lane = _agent_telegram_lane(agent) if "telegram" in agent["platforms"] else None
        session_count = sum(int(by_source.get(source, 0) or 0) for source in source_set)
        active_count = sum(
            1
            for item in recent_sessions
            if item.get("source") in source_set and item.get("is_active")
        )
        if not agent["enabled"]:
            status = "disabled"
        elif not model.get("configured"):
            status = "needs_model"
        elif gateway_running and telegram_lane is not None and not telegram_lane.get("configured"):
            status = "needs_telegram"
        elif gateway_running and any(platform != "local" for platform in agent["platforms"]):
            status = "online"
        elif gateway_running:
            status = "ready"
        else:
            status = "offline"
        queue_summary = {
            **_EMPTY_QUEUE_SUMMARY,
            **queue_by_agent.get(agent_id, {}),
        }
        automation_summary = {
            **_EMPTY_AUTOMATION_SUMMARY,
            **automations_by_agent.get(agent_id, {}),
        }
        lifecycle_status = lifecycle_by_agent.get(agent_id, {})
        context_pressure = {
            **_EMPTY_CONTEXT_PRESSURE,
            **context_by_agent.get(agent_id, {}),
        }
        result.append(
            {
                **agent,
                "status": status,
                "session_count": session_count,
                "active_session_count": active_count,
                "sharedSkills": list(SHARED_AGENT_SKILLS),
                "artifactSkills": list(AGENT_ARTIFACT_SKILLS),
                "toolsets": agent["toolsets"] or global_toolsets,
                "has_prompt": bool(agent.get("prompt")),
                "telegramLane": telegram_lane,
                "queueSummary": queue_summary,
                "automationSummary": automation_summary,
                "lifecycleSummary": lifecycle_status,
                "contextPressure": context_pressure,
                "memorySummary": _agent_memory_summary(agent, queue_summary),
                "observability": {
                    "lastWakeAt": (agent_worker.get("wake") or {}).get("lastWakeAt")
                    if isinstance(agent_worker.get("wake"), dict)
                    and (agent_worker.get("wake") or {}).get("agentId") == agent_id
                    else None,
                    "lastScopedTickAt": agent_worker.get("lastTickAt")
                    if agent_worker.get("agentId") == agent_id
                    else None,
                    "lastCronResultAt": automation_summary.get("lastRunAt"),
                    "retryOrCrashCount": int(lifecycle_status.get("dailyFailures") or 0),
                    "approvalBlockers": int(approval_blockers.get(agent_id, 0)),
                    "staleRecovered": int(queue_summary.get("staleRecovered") or 0),
                },
            }
        )
    return result


_ORCHESTRATION_RUN_FIELDS = (
    "run_id",
    "id",
    "agent_id",
    "route_label",
    "routing_label",
    "status",
    "created_at",
    "updated_at",
)


def _compact_orchestration(snapshot: dict[str, Any]) -> dict[str, Any]:
    compact = dict(snapshot)
    compact["runs"] = [
        {key: run.get(key) for key in _ORCHESTRATION_RUN_FIELDS if key in run}
        for run in snapshot.get("runs", [])
        if isinstance(run, dict)
    ]
    compact["agents"] = [
        {
            key: agent.get(key)
            for key in ("agent_id", "name", "tier", "status", "active_runs", "queued_runs")
            if key in agent
        }
        for agent in snapshot.get("agents", [])
        if isinstance(agent, dict)
    ]
    compact["recent_events"] = [
        {
            "run_id": event.get("run_id"),
            "type": event.get("type") or event.get("kind"),
            "message": _clip_label(event.get("message") or event.get("summary") or "", 160),
            "timestamp": event.get("timestamp") or event.get("created_at"),
        }
        for event in (snapshot.get("recent_events", []) or [])[:5]
        if isinstance(event, dict)
    ]
    return compact


def _orchestration_summary(*, compact: bool = False) -> dict[str, Any]:
    try:
        from gateway.orchestration import get_orchestration_store

        snapshot = get_orchestration_store().snapshot(run_limit=20)
        return _compact_orchestration(snapshot) if compact else snapshot
    except Exception as exc:
        return {
            "agents": [],
            "runs": [],
            "active_runs": 0,
            "error": str(exc),
        }


def _handoff_summary() -> dict[str, Any]:
    try:
        from elevate_cli.data import agent_handoff_summary, connect

        with connect() as conn:
            return agent_handoff_summary(conn, limit=10)
    except Exception as exc:
        return {
            "total": 0,
            "queued": 0,
            "running": 0,
            "waitingHuman": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "open": 0,
            "byAgent": [],
            "recent": [],
            "error": str(exc),
        }


def _agent_worker_summary(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from elevate_cli.agent_worker import snapshot

        return snapshot(config=config)
    except Exception as exc:
        return {
            "enabled": False,
            "state": "error",
            "lastTickAt": None,
            "lastSuccessAt": None,
            "lastError": str(exc),
            "drained": {"handoffs": 0, "adminRuns": 0},
            "limits": {"handoffs": 0, "adminRuns": 0},
            "heartbeat": {"enabled": False, "intervalSeconds": 0, "lastBeatAt": None, "nextBeatAt": None},
            "wake": {"enabled": False, "pending": False, "lastWakeAt": None, "lastReason": "", "count": 0},
            "loop": {"running": False, "startedAt": None},
        }


def build_agent_hub_snapshot(
    *,
    include_profiles: bool = True,
    include_memory_graph: bool = True,
    include_session_total: bool = True,
    include_orchestration: bool = True,
    include_skills: bool = True,
    include_toolsets: bool = True,
    include_harness: bool = True,
    compact_orchestration: bool = False,
) -> dict[str, Any]:
    """Return a redacted local snapshot for the dashboard Agent Hub."""
    config = load_config()
    runtime = read_runtime_status()
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    model = _model_summary(config)
    sessions = _session_summary(include_total=include_session_total)
    access = load_access_config(config)
    orchestration = (
        _orchestration_summary(compact=compact_orchestration)
        if include_orchestration
        else {"agents": [], "runs": [], "active_runs": 0, "error": ""}
    )
    handoffs = _handoff_summary()
    agent_worker = _agent_worker_summary(config)
    memory = _memory_summary(config, include_graph=include_memory_graph)
    skills = (
        _skills_summary(config)
        if include_skills
        else {"total": 0, "enabled": 0, "disabled": 0, "categories": {}, "available": [], "error": ""}
    )
    toolsets = (
        _toolsets_summary(config)
        if include_toolsets
        else {"total": 0, "enabled": [], "known": [], "error": ""}
    )
    if include_harness:
        try:
            from elevate_cli.harness import build_harness_snapshot

            harness = build_harness_snapshot(
                config=config,
                sessions=sessions,
                memory=memory,
                skills=skills,
                toolsets=toolsets,
                orchestration=orchestration,
                include_profiles=include_profiles,
            )
        except Exception as exc:
            harness = {"error": str(exc), "available": False}
    else:
        harness = {"available": False, "error": ""}

    return {
        "generated_at": time.time(),
        "config_path": str(get_config_path()),
        "elevate_home": str(get_elevate_home()),
        "gateway": {
            "running": gateway_running,
            "pid": gateway_pid,
            "state": runtime.get("gateway_state") if runtime else None,
            "updated_at": runtime.get("updated_at") if runtime else None,
            "active_agents": runtime.get("active_agents") if runtime else 0,
            "exit_reason": runtime.get("exit_reason") if runtime else None,
        },
        "model": model,
        "access": {
            "profile": access.get("profile"),
            "label": PROFILE_LABELS.get(access.get("profile"), access.get("profile")),
            "affiliation": access.get("affiliation") or {},
            "entitlements": access.get("entitlements") or {},
        },
        "agents": _agent_summaries(
            config,
            gateway_running=gateway_running,
            sessions=sessions,
            model=model,
            handoffs=handoffs,
            agent_worker=agent_worker,
        ),
        "installableDefaults": _installable_default_specs(
            {_slug(str(agent.get("id") or "")) for agent in _load_agent_defs(config)}
        ),
        "orchestration": orchestration,
        "handoffs": handoffs,
        "agentWorker": agent_worker,
        "platforms": _platform_summary(runtime),
        "sessions": sessions,
        "memory": memory,
        "cron": _cron_summary(),
        "skills": skills,
        "toolsets": toolsets,
        "harness": harness,
        "redaction": {
            "example": redact_key("sk-example-secret"),
            "raw_secrets_returned": False,
        },
    }
