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
    find_contacts,
    get_contact,
    park_contact,
    unpark_contact,
    update_contact_stage,
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
from elevate_cli.data.shadow import (
    data_primary_is_db,
    shadow_read,
    shadow_read_enabled,
)
from elevate_cli.data.attribution import attribute_inbound_reply
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
    get_deal,
    get_deal_context,
    list_deal_action_runs,
    list_deal_attachments,
    list_deal_contacts,
    list_deal_events,
    list_deal_tasks,
    list_deals,
    move_deal_stage,
    record_run_result,
    set_deal_dates,
    set_deal_fields,
    set_deal_money,
    set_deal_toggle,
)
from elevate_cli.data.dispatch import (
    create_action,
    delete_action,
    evaluate as evaluate_dispatch,
    get_action,
    list_action_runs,
    list_actions,
    list_conditional_docs,
    queue_action_run,
    update_action,
    upsert_conditional_doc,
)


__all__ = [
    # connection / paths
    "connect", "transaction",
    "operational_db_path", "data_root", "payloads_root",
    "backups_root", "parity_root",
    # contacts
    "add_contact_note", "classify_contact", "find_contacts", "get_contact",
    "park_contact", "unpark_contact", "update_contact_stage", "upsert_contact",
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
    "get_deal", "get_deal_context", "list_deal_action_runs",
    "list_deal_attachments", "list_deal_contacts", "list_deal_events",
    "list_deal_tasks", "list_deals", "move_deal_stage", "record_run_result",
    "set_deal_dates", "set_deal_fields", "set_deal_money",
    "set_deal_toggle",
    # dispatch (admin action registry / runs / conditional docs)
    "create_action", "delete_action", "evaluate_dispatch", "get_action",
    "list_action_runs", "list_actions", "list_conditional_docs",
    "queue_action_run", "update_action", "upsert_conditional_doc",
    # picker / attribution / gaps
    "attribute_inbound_reply", "analyze_template_gaps",
    "eligible_templates", "pick_template",
]
