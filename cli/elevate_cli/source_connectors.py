"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
)
from elevate_cli.source_connector_modules.prompts import (
    _local_counts_command,
    _local_python_prefix,
    _local_sync_command,
    _render_apple_messages_agent_prompt,
    _render_buyer_brief_agent_prompt,
    _render_crm_prompt,
    _render_social_agent_prompt,
    _render_xposure_pcs_agent_prompt,
    _render_xposure_pcs_views_agent_prompt,
    _source_file_count_commands,
    source_prompt_for,
)
from elevate_cli.source_connector_modules.runtime_helpers import (
    now_iso as _now_impl,
    walk_jsonl_into_pg as _walk_jsonl_into_pg_impl,
)


JsonRecord = dict[str, Any]

from elevate_cli.source_connector_modules.source_catalog import (
    AGENT_SESSION_SOURCE_IDS,
    COMPOSIO_SOCIAL_CONTRACT,
    CONNECTION_CONTRACT,
    JSONL_FILES,
    OWNER_BY_SOURCE,
    SERVER_INLINE_SOURCE_IDS,
    SOURCE_CATEGORIES,
    SOURCE_CONNECTION_BLUEPRINTS,
    SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
    SOURCE_PROMPT_CATEGORIES,
    UI_BY_SOURCE,
    WIRED_SOURCE_IDS,
)


def _now() -> str:
    return _now_impl()


from elevate_cli.source_connector_modules.source_io import (
    PROFILE_STATUS_VALUES,
    _JSONL_COUNT_CACHE,
    _JSONL_RECORD_CACHE,
    _count_jsonl,
    _find_jsonl_record_by_id,
    _profile_state_path,
    _read_json,
    _read_jsonl_records,
    _read_profile_state,
    _read_source_ui_state,
    _record_timestamp,
    _replace_jsonl,
    _parse_record_dt,
    _safe_int,
    _snapshot_reader_lock,
    _snapshot_writer_lock,
    _source_dir,
    _source_ui_state_path,
    _stream_jsonl_records_by_id,
    _tag_text,
    _write_json,
    _write_profile_state,
    _write_source_ui_state,
)


from elevate_cli.source_connector_modules.thread_helpers import (
    _AUTOMATED_DOMAIN_HINTS,
    _AUTOMATED_LOCALPARTS,
    _channel_label,
    _extract_email,
    _heat_score_for_record,
    _is_automated_email,
    _is_automated_sender_record,
    _latest_text,
    _record_person_name,
    _thread_from_record,
    _thread_key,
)

from elevate_cli.source_connector_modules.record_snapshots import (
    _LIST_RECORD_FIELDS,
    _compact_list_text,
    _list_record_snapshot,
)

from elevate_cli.source_connector_modules.draft_helpers import (
    _TEMPLATE_TOKEN_RE,
    _draft_from_task,
    _draft_from_thread,
    _draft_recipient,
    _draft_text_for_task,
    _fallback_draft_for_thread,
    _first_name_from_person,
    _is_message_draft_task,
    _outreach_lane_for_thread,
    _record_field,
    _render_outreach_template,
    _select_thread_template,
    _task_key,
    _template_channel_for_thread,
    _template_values_for_thread,
    _templated_draft_for_thread,
)

from elevate_cli.source_connector_modules.profile_helpers import (
    SOCIAL_INTENT_WORDS,
    SOCIAL_SOURCE_IDS,
    _email_key,
    _is_social_intent,
    _merge_profile,
    _merge_profile_verifiers,
    _name_key,
    _phone_key,
    _profile_contact_values,
    _profile_label,
    _profile_match_keys,
    _profile_verifiers,
    _profiles_from_threads,
    _source_has_inbox_records,
    _source_record_counts,
    _string_values,
)


from elevate_cli.source_connector_modules.apple_messages import (
    APPLE_EPOCH,
    _apple_dt,
    _apple_messages_chat_db_path,
    _apple_messages_source_dir,
    _init_apple_index_db,
    _load_chat_participants,
    _looks_like_fda_denied,
    _sqlite_uri,
    _update_span,
    _write_blocked_apple_messages_source,
    _write_paused_apple_messages_source,
    get_apple_messages_directions,
    initialize_apple_messages_source,
    set_apple_messages_directions,
)


from elevate_cli.source_connector_modules.connector_state import (
    _blueprint,
    _connector_recovery,
    _mutable_source_exists,
    _state_from_status,
)




from elevate_cli.source_connector_modules.connector_views import (
    _candidate_records_for_source,
    _composio_connector_view,
    _discover_composio_views,
    _initialize_behavior,
    build_source_connectors_response,
    build_source_records_response,
    connector_view,
)


from elevate_cli.source_connector_modules.source_inbox import (
    _collect_drafts_for_db_inbox,
    build_source_inbox_response,
)


from elevate_cli.source_connector_modules.private_search import (
    _PCS_BUYER_TAGS,
    _is_pcs_tag,
    _norm_email,
    _norm_phone,
    _pcs_tagged_crm_buyers,
    _read_private_search_buyers,
)


from elevate_cli.source_connector_modules.thread_context import (
    _message_for_thread,
    _resolve_source_view,
    build_thread_context_response,
)


from elevate_cli.source_connector_modules.source_actions import (
    _approve_atomic,
    _channel_for_source,
    _fire_approve_tick,
    _source_view_for_state,
    _thread_draft_template_state,
    update_profile_favorite,
    update_profile_state,
    update_source_task_state,
    update_source_thread_state,
)


from elevate_cli.source_connector_modules.source_scaffold import (
    scaffold_composio_social_source,
    scaffold_source,
)


from elevate_cli.source_connector_modules.crm_actions import (
    _brivity_headers,
    _brivity_write,
    _resolve_crm_context,
    _sierra_get,
    _sierra_headers,
    _sierra_write,
    crm_add_note,
    crm_create_lead,
    crm_find_lead,
    crm_update_stage,
    sync_pending_notes_to_lofty,
)


from elevate_cli.source_connector_modules.crm_sync import sync_generic_crm_source


from elevate_cli.source_connector_modules.lofty_sync import (
    _LOFTY_ENRICHMENT_CHECKPOINT_EVERY,
    _LOFTY_ENRICHMENT_TIMEOUT_S,
    _LOFTY_ENRICHMENT_WORKERS,
    _lofty_enrich_one_lead,
    _lofty_load_enrichment_progress,
    _lofty_save_enrichment_progress,
    sync_lofty_crm_source,
)




from elevate_cli.source_connector_modules.crm_helpers import (
    _LOFTY_LIST_KEYS,
    _basic_auth_header,
    _build_crm_auth,
    _extract_lead_records,
    _generic_crm_get,
    _generic_crm_write,
    _list_text,
    _lofty_epoch_ms_to_iso,
    _lofty_extract_list,
    _lofty_get,
    _lofty_get_activities,
    _lofty_get_first_ok,
    _lofty_get_notes,
    _lofty_get_tasks,
    _lofty_headers,
    _lofty_lead_name,
    _lofty_listing_address,
    _lofty_normalize_activity,
    _lofty_normalize_note,
    _lofty_normalize_task,
    _lofty_timestamp,
    _lofty_write,
    _provider_label,
    _stable_hash_id,
    _tag_names,
)






def _walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    return _walk_jsonl_into_pg_impl(source_dir)




from elevate_cli.source_connector_modules.integration_settings import (
    DEFAULT_CRM,
    _CRM_PROVIDER_ALIASES,
    _CRM_PROVIDER_ENV_DEFAULTS,
    _as_dict,
    _candidate_tools_root,
    _canonical_crm_provider,
    _combined_env,
    _configured_composio_server,
    _crm_to_ui,
    _expand_path,
    _merge_crm,
    _provider_from_admin_profile,
    _ui_crm_to_config,
    get_integration_settings,
    get_source_root_info,
    save_integration_settings,
    test_crm_connection,
)
