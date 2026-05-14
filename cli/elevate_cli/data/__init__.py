"""Central data module for Elevate's operational store.

Lives at ``$ELEVATE_HOME/data/operational.db``. This package owns every
read and write against that database — call sites elsewhere in the CLI
import functions from here, never raw ``sqlite3.connect``.

Sprint 1B: paths + migration runner + initial schema (DONE).
Sprint 1C: per-table read/write helpers (this file's surface).
Sprint 1D: shadow-read parity tooling (parity.py + middleware).
Sprint 1E: backfill migration (``elevate migrate-data``).

See ``docs/central-data-model.md`` and
``docs/central-data-model-v1-plan.md`` for context.
"""

from elevate_cli.data.connection import connect, transaction
from elevate_cli.data.paths import (
    backups_root,
    data_root,
    operational_db_path,
    parity_root,
    payloads_root,
)

# ─── Per-table re-exports ──────────────────────────────────────────────

from elevate_cli.data.contacts import (
    add_contact_note,
    classify_contact,
    close_to_admin,
    find_contacts,
    get_contact,
    park_contact,
    set_pipeline_status,
    unpark_contact,
    update_contact_stage,
    update_flags,
    upsert_contact,
)
from elevate_cli.data.identities import (
    add_identity,
    list_open_conflicts,
    merge_contacts,
    record_identity_conflict,
    resolve_identity,
    resolve_identity_conflict,
)
from elevate_cli.data.conversations import (
    bump_conversation_counters,
    get_conversation,
    get_conversations_for_contact,
    get_or_create_conversation,
    set_heat,
    update_conversation_status,
)
from elevate_cli.data.events import (
    record_attribution_ambiguous,
    record_classification,
    record_draft,
    record_inbound,
    record_ingest_marker,
    record_lifecycle,
    record_outbound,
    record_pcs_activity,
    record_reply_attributed,
    record_send,
    record_template_event,
)
from elevate_cli.data.ingest import (
    get_ingest_run,
    record_ingest_run_completed,
    record_ingest_run_started,
    rollback_ingest_run,
    update_ingest_run_counters,
)
from elevate_cli.data.lead_signals import (
    detect_lead_signal_activity_change,
    get_lead_signal,
    graduate_lead_signal,
    list_open_signals,
    upsert_lead_signal,
    upsert_pcs_buyer,
)
from elevate_cli.data.parity import (
    parity_diff_count,
    parity_total_count,
    record_parity_snapshot,
    recent_diffs,
)
from elevate_cli.data.reads import (
    db_source_inbox_response,
    db_thread_context_response,
)
from elevate_cli.data.review import (
    SCORING_VERSION as REVIEW_SCORING_VERSION,
    review_all_contacts,
    score_contact,
)
from elevate_cli.data.shadow import (
    data_primary_is_db,
    shadow_read,
    shadow_read_enabled,
)
from elevate_cli.data.attribution import attribute_inbound_reply
from elevate_cli.data.notes import (
    list_notes_for_contact,
    list_pending_lofty_notes,
    mark_lofty_deleted,
    mark_lofty_failed,
    mark_lofty_synced,
    recent_ai_note,
    write_note,
)
from elevate_cli.data.gaps import analyze_template_gaps
from elevate_cli.data.picker import eligible_templates, pick_template
from elevate_cli.data.templates import (
    approve_template,
    edit_template,
    get_template,
    list_proposed_templates,
    list_templates,
    propose_template,
    record_template_reply,
    record_template_use,
    reject_template,
    retire_template,
    template_leaderboard,
    template_stats,
    template_stats_with_ambiguous,
)
from elevate_cli.data.deals import (
    add_deal_attachment,
    add_deal_contact,
    create_deal,
    DealPhaseGateBlocked,
    get_deal,
    get_deal_context,
    list_deal_action_runs,
    list_deal_attachments,
    list_deal_contacts,
    list_deal_events,
    list_deal_tasks,
    list_deals,
    move_deal_stage,
    promote_profile_to_admin_deal,
    record_run_result,
    set_deal_dates,
    set_deal_fields,
    set_deal_money,
    set_deal_toggle,
)
from elevate_cli.data.dispatch import (
    approve_action_run,
    create_action,
    delete_action,
    dispatch_action_run_to_cron,
    drain_queued_action_runs,
    ensure_default_admin_actions,
    evaluate as evaluate_dispatch,
    get_action,
    list_action_runs,
    list_actions,
    list_conditional_docs,
    mark_stale_action_runs,
    queue_action_run,
    record_date_trigger_firing,
    update_action,
    upsert_conditional_doc,
    verify_action_run_token,
)
from elevate_cli.data.agent_handoffs import (
    agent_handoff_summary,
    approve_agent_handoff,
    create_agent_handoff,
    dispatch_agent_handoff_to_cron,
    drain_queued_agent_handoffs,
    get_agent_handoff,
    list_agent_handoffs,
    mark_stale_agent_handoffs,
    record_agent_handoff_message,
    record_agent_handoff_result,
)
from elevate_cli.data.workflow_import import (
    import_listing_workflow_csv,
    parse_listing_workflow_csv,
)
from elevate_cli.data.province_guides import (
    condition_docs_for_conditions,
    import_exp_agent_centre,
    list_province_checklists,
    list_province_forms,
    list_province_reference_pages,
    province_agent_memory,
    province_coverage,
    province_guide_summary,
    province_stage_documents,
)
from elevate_cli.data.admin_setup import (
    admin_setup_memory_summary,
    admin_setup_ready,
    build_admin_province_playbook,
    complete_admin_setup,
    get_admin_setup,
    require_admin_setup_ready,
    sync_admin_province_playbook,
    sync_admin_setup_memory,
    sync_admin_setup_runtime,
    update_admin_setup,
)
from elevate_cli.data.pack_onboarding import (
    complete_pack_onboarding,
    get_pack_onboarding,
    pack_onboarding_memory_summary,
    pack_onboarding_ready,
    sync_pack_onboarding_memory,
    update_pack_onboarding,
)
from elevate_cli.data.leads_setup import (
    complete_leads_setup,
    get_leads_setup,
    reset_leads_setup,
    update_leads_setup,
)
from elevate_cli.data.agent_setup import (
    complete_agent_setup,
    get_agent_setup,
    reset_agent_setup,
    update_agent_setup,
)


__all__ = [
    # connection / paths
    "connect", "transaction",
    "operational_db_path", "data_root", "payloads_root",
    "backups_root", "parity_root",
    # contacts
    "add_contact_note", "classify_contact", "close_to_admin", "find_contacts",
    "get_contact", "park_contact", "set_pipeline_status", "unpark_contact",
    "update_contact_stage", "update_flags", "upsert_contact",
    # identities
    "add_identity", "list_open_conflicts", "merge_contacts",
    "record_identity_conflict", "resolve_identity",
    "resolve_identity_conflict",
    # conversations
    "bump_conversation_counters", "get_conversation",
    "get_conversations_for_contact", "get_or_create_conversation",
    "set_heat", "update_conversation_status",
    # events
    "record_attribution_ambiguous", "record_classification", "record_draft",
    "record_inbound", "record_ingest_marker", "record_lifecycle",
    "record_outbound", "record_pcs_activity", "record_reply_attributed",
    "record_send", "record_template_event",
    # ingest
    "get_ingest_run", "record_ingest_run_completed",
    "record_ingest_run_started", "rollback_ingest_run",
    "update_ingest_run_counters",
    # lead signals
    "detect_lead_signal_activity_change", "get_lead_signal",
    "graduate_lead_signal", "list_open_signals", "upsert_lead_signal",
    "upsert_pcs_buyer",
    # parity
    "parity_diff_count", "parity_total_count", "record_parity_snapshot",
    "recent_diffs",
    # reads
    "db_source_inbox_response", "db_thread_context_response",
    # ai review / heat scoring
    "REVIEW_SCORING_VERSION", "review_all_contacts", "score_contact",
    # shadow read
    "data_primary_is_db", "shadow_read", "shadow_read_enabled",
    # templates
    "approve_template", "edit_template", "get_template",
    "list_proposed_templates", "list_templates", "propose_template",
    "record_template_reply", "record_template_use", "reject_template",
    "retire_template", "template_leaderboard", "template_stats",
    "template_stats_with_ambiguous",
    # deals
    "add_deal_attachment", "add_deal_contact", "create_deal",
    "DealPhaseGateBlocked",
    "get_deal", "get_deal_context", "list_deal_action_runs",
    "list_deal_attachments", "list_deal_contacts", "list_deal_events",
    "list_deal_tasks", "list_deals", "move_deal_stage", "record_run_result",
    "promote_profile_to_admin_deal", "set_deal_dates",
    "set_deal_fields", "set_deal_money", "set_deal_toggle",
    # dispatch (admin action registry / runs / conditional docs)
    "approve_action_run", "create_action", "delete_action",
    "dispatch_action_run_to_cron", "drain_queued_action_runs",
    "ensure_default_admin_actions", "evaluate_dispatch",
    "get_action", "list_action_runs", "list_actions",
    "list_conditional_docs", "mark_stale_action_runs",
    "queue_action_run", "record_date_trigger_firing",
    "update_action", "upsert_conditional_doc", "verify_action_run_token",
    # visible agent handoff bus
    "agent_handoff_summary", "approve_agent_handoff", "create_agent_handoff",
    "dispatch_agent_handoff_to_cron", "drain_queued_agent_handoffs",
    "get_agent_handoff", "list_agent_handoffs", "mark_stale_agent_handoffs",
    "record_agent_handoff_message", "record_agent_handoff_result",
    # workflow bootstrap import
    "import_listing_workflow_csv", "parse_listing_workflow_csv",
    # province guide reference store
    "condition_docs_for_conditions", "import_exp_agent_centre",
    "list_province_checklists", "list_province_forms",
    "list_province_reference_pages", "province_agent_memory", "province_coverage",
    "province_guide_summary", "province_stage_documents",
    # Admin setup readiness gate
    "admin_setup_memory_summary", "admin_setup_ready",
    "build_admin_province_playbook", "complete_admin_setup",
    "get_admin_setup", "require_admin_setup_ready",
    "sync_admin_province_playbook", "sync_admin_setup_memory",
    "sync_admin_setup_runtime", "update_admin_setup",
    # paid pack onboarding
    "complete_pack_onboarding", "get_pack_onboarding",
    "pack_onboarding_memory_summary", "pack_onboarding_ready",
    "sync_pack_onboarding_memory", "update_pack_onboarding",
    # picker / attribution / gaps
    "attribute_inbound_reply", "analyze_template_gaps",
    "eligible_templates", "pick_template",
    # Agent (top-level) setup readiness gate
    "complete_agent_setup", "get_agent_setup",
    "reset_agent_setup", "update_agent_setup",
]
