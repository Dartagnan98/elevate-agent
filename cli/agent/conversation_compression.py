"""Context compression — extract the AIAgent methods that drive summarisation.

Three concerns live here:

* :func:`check_compression_model_feasibility` — startup probe of the
  configured auxiliary compression model.  Warns when the aux context
  window can't fit the main model's compression threshold; auto-lowers
  the session threshold when possible; hard-rejects auxes below
  ``MINIMUM_CONTEXT_LENGTH``.

* :func:`replay_compression_warning` — re-emit a stored warning through
  the gateway ``status_callback`` once it's wired up (the callback is
  set after :class:`AIAgent` construction).

* :func:`compress_context` — the actual compression call.  Runs the
  configured compressor, splits the SQLite session, rotates the
  session_id, notifies plugin context engines / memory providers, and
  returns the compressed message list and freshly-built system prompt.

* :func:`try_shrink_image_parts_in_messages` — image-too-large recovery
  helper that re-encodes ``data:image/...;base64,...`` parts at a smaller
  size so retries can fit under provider ceilings (Anthropic's 5 MB).

``run_agent`` keeps thin wrappers for each so existing call sites
(``self._compress_context(...)``) keep working.  Tests that exercise
these paths see no behavioural change.
"""

from __future__ import annotations

import logging
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

from agent.model_metadata import (
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
)

logger = logging.getLogger(__name__)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _is_preserved_context_message(msg: Any) -> bool:
    if not isinstance(msg, dict):
        return False
    text = _content_text(msg.get("content")).strip()
    if not text:
        return False
    try:
        from tools.present_plan_tool import PLAN_INJECTION_HEADER
    except Exception:
        PLAN_INJECTION_HEADER = (
            "[Your latest Plan panel plan was preserved across context compression "
            "- reference only, not a new request]"
        )
    try:
        from tools.todo_tool import TODO_INJECTION_HEADER
    except Exception:
        TODO_INJECTION_HEADER = "[Your active task list was preserved across context compression]"
    return text.startswith(PLAN_INJECTION_HEADER) or text.startswith(TODO_INJECTION_HEADER)


def insert_preserved_context(
    compressed: list,
    snapshots: List[Optional[str]],
) -> list:
    """Insert preserved plan/todo context without hiding the latest user ask."""
    to_insert = [s.strip() for s in snapshots if isinstance(s, str) and s.strip()]
    if not to_insert:
        return compressed

    existing = {_content_text(m.get("content")).strip() for m in compressed if isinstance(m, dict)}
    to_insert = [s for s in to_insert if s not in existing]
    if not to_insert:
        return compressed

    snapshot = "\n\n".join(to_insert)
    insert_at = None
    for i in range(len(compressed) - 1, -1, -1):
        msg = compressed[i]
        if (
            isinstance(msg, dict)
            and msg.get("role") == "user"
            and not _is_preserved_context_message(msg)
        ):
            insert_at = i
            break

    next_messages = list(compressed)
    preserved_msg = {"role": "user", "content": snapshot}
    if insert_at is None:
        next_messages.append(preserved_msg)
    else:
        next_messages.insert(insert_at, preserved_msg)
    return next_messages


def _collect_checkpoint_files(messages: list) -> List[str]:
    file_keys = {
        "path", "file_path", "target_file", "filename", "file", "notebook_path",
        "files", "paths", "files_read", "files_written", "output_path",
        "output_file", "artifact_path",
    }
    seen: set[str] = set()
    out: List[str] = []

    def add_value(value: Any) -> None:
        if len(out) >= 500:
            return
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("/") and raw not in seen:
                seen.add(raw)
                out.append(raw)
            return
        if isinstance(value, list):
            for item in value:
                add_value(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in file_keys:
                    add_value(item)

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            args = fn.get("arguments", call.get("arguments"))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (TypeError, ValueError):
                    args = None
            if isinstance(args, dict):
                add_value(args)
        content = msg.get("content")
        if isinstance(content, str) and "{" in content:
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                add_value(parsed)
    return out


def _store_compression_checkpoint(
    agent: Any,
    *,
    session_id: str,
    old_session_id: Optional[str],
    source_messages: list,
    compressed_messages: list,
) -> None:
    db = getattr(agent, "_session_db", None)
    if db is None or not session_id:
        return
    lineage_root_id = old_session_id or session_id
    try:
        identity = db.resolve_canonical_session_identity(old_session_id or session_id)
        lineage_root_id = identity.get("lineage_root_id") or lineage_root_id
    except Exception:
        pass
    checkpoint: dict[str, Any] = {
        "version": 1,
        "session_id": session_id,
        "lineage_root_id": lineage_root_id,
        "active_session_id": session_id,
        "updated_at": time.time(),
        "message_count": len(compressed_messages),
    }
    try:
        from tools.present_plan_tool import extract_latest_plan_from_messages

        latest_plan = extract_latest_plan_from_messages(source_messages)
        if latest_plan:
            plan, title = latest_plan
            checkpoint["plan"] = plan
            checkpoint["plan_title"] = title or ""
    except Exception:
        pass
    try:
        todos = getattr(agent, "_todo_store", None)
        if todos is not None:
            checkpoint["todos"] = todos.read()
    except Exception:
        pass
    files = _collect_checkpoint_files(source_messages) or _collect_checkpoint_files(compressed_messages)
    if files:
        checkpoint["files"] = files
        checkpoint["artifacts"] = [{"path": path} for path in files]
    try:
        checkpoint["children"] = db.list_child_sessions(session_id)
    except Exception:
        pass
    try:
        db.set_meta(f"session_checkpoint:{session_id}", json.dumps(checkpoint))
        if old_session_id and old_session_id != session_id:
            db.set_meta(f"session_checkpoint:{old_session_id}", json.dumps(checkpoint))
    except Exception as exc:
        logger.debug("compression checkpoint write failed for %s: %s", session_id, exc)


def check_compression_model_feasibility(agent: Any) -> None:
    """Warn at session start if the auxiliary compression model's context
    window is smaller than the main model's compression threshold.

    When the auxiliary model cannot fit the content that needs summarising,
    compression will either fail outright (the LLM call errors) or produce
    a severely truncated summary.

    Called during ``AIAgent.__init__`` so CLI users see the warning
    immediately (via ``_vprint``).  The gateway sets ``status_callback``
    *after* construction, so :func:`replay_compression_warning` re-sends
    the stored warning through the callback on the first
    ``run_conversation()`` call.
    """
    if not agent.compression_enabled:
        return
    try:
        from agent.auxiliary_client import (
            _resolve_task_provider_model,
            get_text_auxiliary_client,
        )
        from agent.model_metadata import (
            MINIMUM_CONTEXT_LENGTH,
            get_model_context_length,
        )

        client, aux_model = get_text_auxiliary_client(
            "compression",
            main_runtime=agent._current_main_runtime(),
        )
        # Best-effort aux provider label for the warning message. The
        # configured provider may be "auto", in which case we fall back
        # to the client's base_url hostname so the user can still tell
        # where the compression model is actually being called.
        try:
            _aux_cfg_provider, _, _, _, _ = _resolve_task_provider_model("compression")
        except Exception:
            _aux_cfg_provider = ""
        if client is None or not aux_model:
            if _aux_cfg_provider and _aux_cfg_provider != "auto":
                msg = (
                    "⚠ Configured auxiliary compression provider "
                    f"'{_aux_cfg_provider}' is unavailable — context "
                    "compression will abort rather than drop context. "
                    "Check auxiliary.compression in config.yaml and "
                    "reauthenticate that provider."
                )
            else:
                msg = (
                    "⚠ No auxiliary LLM provider configured — context "
                    "compression will abort rather than drop context. "
                    "Run `elevate setup` or set OPENROUTER_API_KEY."
                )
            agent._compression_warning = msg
            agent._emit_status(msg)
            logger.warning(
                "No auxiliary LLM provider for compression — "
                "summaries will be unavailable."
            )
            return

        aux_base_url = str(getattr(client, "base_url", ""))
        # ``client.api_key`` may be a callable (Azure Foundry Entra ID
        # bearer provider). The context-length resolver chain expects a
        # string, but it only needs a key for live catalogue probes
        # (provider model lists). For Entra clients the model-metadata
        # chain still resolves via models.dev + hardcoded family
        # fallbacks, which don't require auth — pass empty string rather
        # than minting a bearer JWT just to look up a context length.
        _raw_aux_key = getattr(client, "api_key", "")
        aux_api_key = "" if (callable(_raw_aux_key) and not isinstance(_raw_aux_key, str)) else str(_raw_aux_key or "")

        aux_context = get_model_context_length(
            aux_model,
            base_url=aux_base_url,
            api_key=aux_api_key,
            config_context_length=getattr(agent, "_aux_compression_context_length_config", None),
            # Each model must be resolved with its own provider so that
            # provider-specific paths (e.g. Bedrock static table, OpenRouter API)
            # are invoked for the correct client, not inherited from the main model.
            provider=(_aux_cfg_provider if _aux_cfg_provider and _aux_cfg_provider != "auto" else getattr(agent, "provider", "")),
            custom_providers=agent._custom_providers,
        )

        # Hard floor: the auxiliary compression model must have at least
        # MINIMUM_CONTEXT_LENGTH (64K) tokens of context.  The main model
        # is already required to meet this floor (checked earlier in
        # __init__), so the compression model must too — otherwise it
        # cannot summarise a full threshold-sized window of main-model
        # content.  Mirrors the main-model rejection pattern.
        if aux_context and aux_context < MINIMUM_CONTEXT_LENGTH:
            raise ValueError(
                f"Auxiliary compression model {aux_model} has a context "
                f"window of {aux_context:,} tokens, which is below the "
                f"minimum {MINIMUM_CONTEXT_LENGTH:,} required by Elevate "
                f"Agent.  Choose a compression model with at least "
                f"{MINIMUM_CONTEXT_LENGTH // 1000}K context (set "
                f"auxiliary.compression.model in config.yaml), or set "
                f"auxiliary.compression.context_length to override the "
                f"detected value if it is wrong."
            )

        threshold = agent.context_compressor.threshold_tokens
        if aux_context < threshold:
            # Auto-correct: lower the live session threshold so
            # compression actually works this session.  The hard floor
            # above guarantees aux_context >= MINIMUM_CONTEXT_LENGTH,
            # so the new threshold is always >= 64K.
            #
            old_threshold = threshold
            # Keep real room for the summarizer template, previous rolling
            # summary, and output budget.  Using the aux model's whole window
            # as the trigger point made the warning technically correct while
            # still letting the summarizer request overflow.
            new_threshold = min(
                aux_context,
                max(MINIMUM_CONTEXT_LENGTH, int(aux_context * 0.72)),
            )
            agent.context_compressor.threshold_tokens = new_threshold
            # Keep threshold_percent in sync so future main-model
            # context_length changes (update_model) re-derive from a
            # sensible number rather than the original too-high value.
            main_ctx = agent.context_compressor.context_length
            if main_ctx:
                agent.context_compressor.threshold_percent = (
                    new_threshold / main_ctx
                )
            safe_pct = int((new_threshold / main_ctx) * 100) if main_ctx else 50
            # Build human-readable "model (provider)" labels for both
            # the main model and the compression model so users can
            # tell at a glance which provider each side is actually
            # using. When the configured provider is empty or "auto",
            # fall back to the client's base_url hostname.
            _main_model = getattr(agent, "model", "") or "?"
            _main_provider = getattr(agent, "provider", "") or ""
            _aux_provider_label = (
                _aux_cfg_provider
                if _aux_cfg_provider and _aux_cfg_provider != "auto"
                else ""
            )
            if not _aux_provider_label:
                try:
                    from urllib.parse import urlparse
                    _aux_provider_label = (
                        urlparse(aux_base_url).hostname or aux_base_url
                    )
                except Exception:
                    _aux_provider_label = aux_base_url or "auto"
            _main_label = (
                f"{_main_model} ({_main_provider})"
                if _main_provider
                else _main_model
            )
            _aux_label = f"{aux_model} ({_aux_provider_label})"
            msg = (
                f"⚠ Compression model {_aux_label} context is "
                f"{aux_context:,} tokens, but the main model "
                f"{_main_label}'s compression threshold was "
                f"{old_threshold:,} tokens. "
                f"Auto-lowered this session's threshold to "
                f"{new_threshold:,} tokens so compression can run.\n"
                f"  To make this permanent, edit config.yaml — either:\n"
                f"  1. Use a larger compression model:\n"
                f"       auxiliary:\n"
                f"         compression:\n"
                f"           model: <model-with-{old_threshold:,}+-context>\n"
                f"  2. Lower the compression threshold:\n"
                f"       compression:\n"
                f"         threshold: 0.{safe_pct:02d}"
            )
            agent._compression_warning = msg
            agent._emit_status(msg)
            logger.warning(
                "Auxiliary compression model %s has %d token context, "
                "below the main model's compression threshold of %d "
                "tokens — auto-lowered session threshold to %d to "
                "keep compression working.",
                aux_model,
                aux_context,
                old_threshold,
                new_threshold,
            )
    except ValueError:
        # Hard rejections (aux below minimum context) must propagate
        # so the session refuses to start.
        raise
    except Exception as exc:
        logger.debug(
            "Compression feasibility check failed (non-fatal): %s", exc
        )


def replay_compression_warning(agent: Any) -> None:
    """Re-send the compression warning through ``status_callback``.

    During ``__init__`` the gateway's ``status_callback`` is not yet
    wired, so ``_emit_status`` only reaches ``_vprint`` (CLI).  This
    method is called once at the start of the first
    ``run_conversation()`` — by then the gateway has set the callback,
    so every platform (Telegram, Discord, Slack, etc.) receives the
    warning.
    """
    msg = getattr(agent, "_compression_warning", None)
    if msg and agent.status_callback:
        try:
            agent.status_callback("lifecycle", msg)
        except Exception:
            pass


def compress_context(
    agent: Any,
    messages: list,
    system_message: str,
    *,
    approx_tokens: Optional[int] = None,
    task_id: str = "default",
    focus_topic: Optional[str] = None,
    force: bool = False,
) -> Tuple[list, str]:
    """Compress conversation context and split the session in SQLite.

    Args:
        agent: The owning :class:`AIAgent`.
        messages: Current message history (will be summarised).
        system_message: Current system prompt; rebuilt after compression.
        approx_tokens: Pre-compression token estimate, logged for ops.
        task_id: Tool task scope (used for clearing file-read dedup state).
        focus_topic: Optional focus string for guided compression — the
            summariser will prioritise preserving information related to
            this topic.  Inspired by Claude Code's ``/compact <focus>``.
        force: If True, bypass any active summary-failure cooldown.  Set
            by the manual ``/compress`` slash command so users can retry
            immediately after an auto-compress abort.  Auto-compress
            callers use the default ``False``.

    Returns:
        ``(compressed_messages, new_system_prompt)`` tuple.  When
        compression aborts (aux LLM failed to produce a usable summary),
        returns the original messages unchanged and the existing system
        prompt — the session is NOT rotated.  Callers should detect the
        no-op via ``len(returned) == len(input)`` and stop the retry loop.
    """
    # Lazy feasibility check — run the auxiliary-provider probe + context
    # length lookup just-in-time on the first compression attempt instead of
    # at AIAgent.__init__. Saves ~400ms cold off every short session that
    # never reaches the threshold (the vast majority of ``chat -q`` runs).
    # The check itself sets ``agent._compression_warning`` so the
    # status-callback replay machinery still emits the warning to the user
    # the first time it would matter.
    if not getattr(agent, "_compression_feasibility_checked", True):
        try:
            check_compression_model_feasibility(agent)
        finally:
            agent._compression_feasibility_checked = True

    _pre_msg_count = len(messages)
    logger.info(
        "context compression started: session=%s messages=%d tokens=~%s model=%s focus=%r",
        agent.session_id or "none", _pre_msg_count,
        f"{approx_tokens:,}" if approx_tokens else "unknown", agent.model,
        focus_topic,
    )
    try:
        agent._emit_status(
            "🗜️ Compacting context — summarizing earlier conversation so I can continue..."
        )
    except Exception:
        pass  # a flaky status sink must never abort the compaction itself

    # Notify external memory provider before compression discards context
    if agent._memory_manager:
        try:
            agent._memory_manager.on_pre_compress(messages)
        except Exception:
            pass

    # Keepalive heartbeat for the blocking summary call. compress() runs the
    # auxiliary summary LLM synchronously and can block the turn for tens of
    # seconds (observed ~112s on a 252K-token session) with nothing streaming.
    # During that window this thread (a) calls _touch_activity every interval to
    # reset the gateway inactivity-kill watchdog, and (b) re-emits a status frame
    # so the "Compacting context" pill stays visible and (where the throttle
    # allows) ticks elapsed time, instead of the chat looking hung / the thinking
    # indicator vanishing.
    # NOTE: this is NOT what keeps the WebSocket open. uvicorn already pings every
    # ~20s (ws_ping_interval default), so the socket survives a silent compaction
    # on its own; _touch_activity only feeds the internal watchdog, and the
    # throttled _emit_status (default 30s same-category) is SLOWER than uvicorn's
    # ping -- it is for the pill/progress display, not socket survival. (To show
    # true per-second elapsed on web, lower the throttle for this category; left
    # as-is to avoid flooding no-overwrite lanes like Telegram.)
    # Fires only past one interval (default 15s), so short compactions carry zero
    # overhead; no-ops when the agent has no status_callback.
    _ka_stop = threading.Event()
    _ka_start = time.monotonic()
    try:
        _ka_interval = float(os.getenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "") or 15.0)
    except (TypeError, ValueError):
        _ka_interval = 15.0
    if _ka_interval < 0.05:
        _ka_interval = 0.05

    def _compaction_keepalive() -> None:
        while not _ka_stop.wait(_ka_interval):
            _elapsed = int(time.monotonic() - _ka_start)
            try:
                agent._touch_activity(f"compacting context ({_elapsed}s elapsed)")
            except Exception:
                pass
            try:
                agent._emit_status(
                    f"🗜️ Compacting context — still summarizing ({_elapsed}s elapsed)…"
                )
            except Exception:
                pass

    _ka_thread = threading.Thread(
        target=_compaction_keepalive, daemon=True, name="compaction-keepalive"
    )
    _ka_thread.start()
    # Compaction redesign (docs/compaction-redesign.md): the transcript is NEVER
    # rewritten or rotated. Compute a new payload cursor + synthetic summary over
    # messages[prev_cursor:compacted_idx], fold the prior summary in iteratively,
    # and persist BOTH as session metadata. messages_for_api injects the summary
    # and skips the compacted head only when the API payload is built.
    _prev_cursor = int(getattr(agent, "compaction_cursor", 0) or 0)
    _prev_summary = getattr(agent, "compaction_summary", None)
    try:
        summary_text, compacted_idx = agent.context_compressor.summarize_to_cursor(
            messages,
            prev_cursor=_prev_cursor,
            previous_summary=_prev_summary,
            focus_topic=focus_topic,
            force=force,
        )
    except Exception:
        raise
    finally:
        _ka_stop.set()
        _ka_thread.join(timeout=2.0)

    # If compression aborted (aux LLM failed to produce a usable summary)
    # the compressor returns the input messages unchanged.  Surface the
    # error to the user, skip the session-rotation work entirely (no
    # session has logically ended), and let auto-compress callers detect
    # the no-op via len(returned) == len(input).
    if getattr(agent.context_compressor, "_last_compress_aborted", False):
        _err = getattr(agent.context_compressor, "_last_summary_error", None) or "unknown error"
        if getattr(agent, "_last_compression_summary_warning", None) != _err:
            agent._last_compression_summary_warning = _err
            agent._emit_warning(
                f"⚠ Compression aborted: {_err}. "
                "No messages were dropped — conversation continues unchanged. "
                "Run /compress to retry, or /new to start a fresh session."
            )
        _existing_sp = getattr(agent, "_cached_system_prompt", None)
        if not _existing_sp:
            _existing_sp = agent._build_system_prompt(system_message)
        return messages, _existing_sp

    summary_error = getattr(agent.context_compressor, "_last_summary_error", None)
    if summary_error:
        if getattr(agent, "_last_compression_summary_warning", None) != summary_error:
            agent._last_compression_summary_warning = summary_error
            agent._emit_warning(
                f"⚠ Compression summary failed: {summary_error}. "
                "Inserted a fallback context marker."
            )
    else:
        # No hard failure — but did the configured aux model error out
        # and get recovered by retrying on main?  Surface that so users
        # know their auxiliary.compression.model setting is broken even
        # though compression succeeded.
        _aux_fail_model = getattr(agent.context_compressor, "_last_aux_model_failure_model", None)
        _aux_fail_err = getattr(agent.context_compressor, "_last_aux_model_failure_error", None)
        if _aux_fail_model:
            # Dedup on (model, error) so we don't spam on every compaction
            _aux_key = (_aux_fail_model, _aux_fail_err)
            if getattr(agent, "_last_aux_fallback_warning_key", None) != _aux_key:
                agent._last_aux_fallback_warning_key = _aux_key
                agent._emit_warning(
                    f"ℹ Configured compression model '{_aux_fail_model}' failed "
                    f"({_aux_fail_err or 'unknown error'}). Recovered using main model — "
                    "check auxiliary.compression.model in config.yaml."
                )

    # No-op compaction: the cut did not advance past the current cursor, so
    # nothing new was hidden (summarize_to_cursor returned None without
    # aborting). It already armed the low-yield cooldown so should_compress()
    # backs off. Leave cursor/summary AND the usage projector untouched — the
    # payload did not shrink — and return the transcript unchanged.
    if summary_text is None:
        _existing_sp = getattr(agent, "_cached_system_prompt", None) or agent._build_system_prompt(system_message)
        return messages, _existing_sp

    # Trigger memory extraction over the compacted region before it scrolls out
    # of the model's window. NO rotation: the session id is stable, the
    # transcript stays append-only, only the compaction METADATA moves.
    try:
        agent.commit_memory_session(messages)
    except Exception as _mem_err:
        logger.debug("commit_memory_session (compression) skipped: %s", _mem_err)

    # Persist the new compaction state as SESSION METADATA (NOT message rows):
    # the payload-time cursor + synthetic summary. The transcript is never
    # rewritten — messages_for_api applies these only when building the API copy.
    agent.compaction_cursor = compacted_idx
    agent.compaction_summary = summary_text
    if agent._session_db:
        try:
            agent._session_db.update_compaction(
                agent.session_id, summary_text, compacted_idx
            )
        except Exception as _meta_err:
            logger.warning(
                "Compaction metadata write failed for %s: %s",
                agent.session_id, _meta_err,
            )

    # The system prompt is intentionally NOT rebuilt on compaction: nothing
    # about the cursor model changes it (the summary lives in a payload-time
    # synthetic message, not the system prompt), and keeping it byte-stable
    # preserves the provider prompt-cache prefix across the compaction boundary.
    new_system_prompt = (
        getattr(agent, "_cached_system_prompt", None)
        or agent._build_system_prompt(system_message)
    )
    agent._cached_system_prompt = new_system_prompt

    # Warn on repeated compressions (quality degrades with each pass)
    _cc = agent.context_compressor.compression_count
    if _cc >= 2:
        agent._vprint(
            f"{agent.log_prefix}⚠️  Session compressed {_cc} times — "
            f"accuracy may degrade. Consider /new to start fresh.",
            force=True,
        )

    # Post-compaction trigger guard (#14695): the visible message list is
    # unchanged, so the usage projector's snapshot (taken on the FULL payload)
    # would project the pre-compaction size and immediately re-fire compaction.
    # Park the -1 sentinel + invalidate the projector so the trigger stays quiet
    # until the next API call reports real usage for the now-trimmed payload.
    # (In the old rotating design the projector self-invalidated because the
    # caller rebound `messages` to a brand-new list; the cursor model reuses the
    # same list object, so we must invalidate explicitly here.)
    agent.context_compressor.last_prompt_tokens = -1
    agent.context_compressor.last_completion_tokens = 0
    try:
        agent.context_compressor.awaiting_real_usage_after_compression = True
    except Exception:
        pass
    _usage_projector = getattr(agent, "_usage_projector", None)
    if _usage_projector is not None:
        try:
            _usage_projector.invalidate()
        except Exception:
            pass

    # Context-pressure telemetry — summarise from the synthetic summary itself
    # (the compacted head is now represented by it) so the dashboard pressure
    # panel reflects what the model actually carries forward.
    try:
        from gateway.session_context import get_session_env

        _pressure_agent_id = (
            get_session_env("ELEVATE_SESSION_AGENT_ID", "")
            or str(getattr(agent, "_agent_id", "") or "")
            or os.environ.get("ELEVATE_AGENT_ID", "")
        ).strip()
        _context_limit = int(getattr(agent.context_compressor, "context_length", 0) or 0)
        if _pressure_agent_id and _context_limit:
            from elevate_cli.agent_policy import record_agent_context_pressure
            from elevate_cli.data import connect

            with connect() as _conn:
                record_agent_context_pressure(
                    _pressure_agent_id,
                    session_id=str(getattr(agent, "session_id", "") or ""),
                    current_tokens=int(approx_tokens or 0),
                    context_limit=_context_limit,
                    summary=str(summary_text or "")[:4000],
                    conn=_conn,
                    actor=_pressure_agent_id,
                )
    except Exception as _pressure_exc:
        logger.debug("agent context-pressure record skipped: %s", _pressure_exc)

    # Clear the file-read dedup cache.  After compaction the original read
    # content is summarised away — if the model re-reads the same file it needs
    # the full content, not a "file unchanged" stub.
    try:
        from tools.file_tools import reset_file_dedup
        reset_file_dedup(task_id)
    except Exception:
        pass

    logger.info(
        "context compaction done: session=%s cursor=%d->%d summary=%d chars "
        "(transcript untouched, no rotation)",
        agent.session_id or "none", _prev_cursor, compacted_idx,
        len(summary_text or ""),
    )
    return messages, new_system_prompt


def try_shrink_image_parts_in_messages(api_messages: list) -> bool:
    """Re-encode all native image parts at a smaller size to recover from
    image-too-large errors (Anthropic 5 MB, unknown other providers).

    Mutates ``api_messages`` in place. Returns True if any image part was
    actually replaced, False if there were no image parts to shrink or
    Pillow couldn't help (caller should surface the original error).

    Strategy: look for ``image_url`` / ``input_image`` parts carrying a
    ``data:image/...;base64,...`` payload.  For each one whose encoded
    size exceeds 4 MB (a safe target that slides under Anthropic's 5 MB
    ceiling with header overhead), write the base64 to a tempfile, call
    ``vision_tools._resize_image_for_vision`` to produce a smaller data
    URL, and substitute it in place.

    Non-data-URL images (http/https URLs) are not touched — the provider
    fetches those itself and the size limit is different.
    """
    if not api_messages:
        return False

    try:
        from tools.vision_tools import _resize_image_for_vision
    except Exception as exc:
        logger.warning("image-shrink recovery: vision_tools unavailable — %s", exc)
        return False

    # 4 MB target leaves comfortable headroom under Anthropic's 5 MB.
    # Non-Anthropic providers we haven't observed rejecting are fine with
    # much larger; shrinking to 4 MB here loses quality but only fires
    # after a confirmed provider rejection, so the alternative is failure.
    target_bytes = 4 * 1024 * 1024
    changed_count = 0

    def _shrink_data_url(url: str) -> Optional[str]:
        """Return a smaller data URL, or None if shrink can't help."""
        if not isinstance(url, str) or not url.startswith("data:"):
            return None
        if len(url) <= target_bytes:
            # This specific image wasn't the oversized one.
            return None
        try:
            header, _, data = url.partition(",")
            mime = "image/jpeg"
            if header.startswith("data:"):
                mime_part = header[len("data:"):].split(";", 1)[0].strip()
                if mime_part.startswith("image/"):
                    mime = mime_part
            import base64 as _b64
            raw = _b64.b64decode(data)
            suffix = {
                "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
                "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/bmp": ".bmp",
            }.get(mime, ".jpg")
            tmp = tempfile.NamedTemporaryFile(
                prefix="elevate_shrink_", suffix=suffix, delete=False,
            )
            try:
                tmp.write(raw)
                tmp.close()
                resized = _resize_image_for_vision(
                    Path(tmp.name),
                    mime_type=mime,
                    max_base64_bytes=target_bytes,
                )
            finally:
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:
                    pass
            if not resized or len(resized) >= len(url):
                # Shrink didn't help (or made it bigger — corrupt input?).
                return None
            return resized
        except Exception as exc:
            logger.warning("image-shrink recovery: re-encode failed — %s", exc)
            return None

    for msg in api_messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype not in {"image_url", "input_image"}:
                continue
            image_value = part.get("image_url")
            # OpenAI chat.completions: {"image_url": {"url": "data:..."}}
            # OpenAI Responses: {"image_url": "data:..."}
            if isinstance(image_value, dict):
                url = image_value.get("url", "")
                resized = _shrink_data_url(url)
                if resized:
                    image_value["url"] = resized
                    changed_count += 1
            elif isinstance(image_value, str):
                resized = _shrink_data_url(image_value)
                if resized:
                    part["image_url"] = resized
                    changed_count += 1

    if changed_count:
        logger.info(
            "image-shrink recovery: re-encoded %d image part(s) to fit under %.0f MB",
            changed_count, target_bytes / (1024 * 1024),
        )
    return changed_count > 0


# ──────────────────────────────────────────────────────────────────────
# Real-count compression trigger (2026-06)
#
# The compaction trigger historically ran off a mix of provider-reported
# prompt_tokens and chars/4 estimates, with the default threshold parked
# at 0.85 because a single turn can add ~10-12% of the window before the
# next iteration-boundary check. These helpers close the gap to Claude
# Code's ~90-92% ceiling:
#
#   1. RealUsageProjector tracks the last server-reported TOTAL prompt
#      size for the conversation and projects current usage as
#      real_count + delta-estimate of messages appended since that call.
#      Projection is only valid while the message list has not been
#      mutated beyond appends (compaction / prune / prefill-pops
#      invalidate it).
#   2. The trigger line becomes
#          min(threshold_line, window - output_reserve)
#      where output_reserve is a FIXED headroom (session max output
#      tokens + summarizer overhead + pad) instead of a percentage
#      margin, so the next call's output AND the compaction request
#      itself always fit.
#   3. When a real count backs the measurement, the default threshold
#      rises to 0.90; pure-estimate mode keeps 0.85. A user-pinned
#      compression.threshold always wins over both mode defaults.
#
# Anti-thrash guards from #14695 are preserved: should_compress_now()
# delegates to the compressor's own should_compress() (ineffective-
# compression backoff), and callers keep the post-compaction -1
# prompt-token sentinel + projector invalidation so a compaction never
# immediately re-triggers off a stale or schema-inflated measurement.
# ──────────────────────────────────────────────────────────────────────

# Default trigger thresholds per measurement mode. The compressor object
# keeps 0.85 as its construction-time default (estimate mode); the
# real-count bump is applied at check time so post-compaction /resumed
# sessions automatically drop back to the conservative line.
ESTIMATE_MODE_THRESHOLD = 0.85
REAL_COUNT_MODE_THRESHOLD = 0.90

# Fixed output headroom components. The summarizer overhead covers the
# compaction request's own generation budget: the summary token ceiling
# (12K, see context_compressor._SUMMARY_TOKENS_CEILING) times the 1.3x
# max_tokens factor _generate_summary passes, rounded up. NOTE: this is
# a size constant, not a model choice — the summarizer follows the
# session/configured model (house rule: never hardcode a model id).
SUMMARIZER_OUTPUT_OVERHEAD_TOKENS = 16_000
OUTPUT_RESERVE_SAFETY_PAD_TOKENS = 2_000
# When the session has no explicit max_tokens configured (provider
# default applies), assume a realistic per-call output size for the
# reserve rather than 0.
DEFAULT_MAX_OUTPUT_TOKENS_GUESS = 8_192


def compute_output_reserve_tokens(session_max_tokens: Any = None) -> int:
    """Fixed output-headroom reserve for the compression trigger.

    reserve = max(summarizer overhead, session max output tokens) + pad.
    The max() (rather than a sum) matches the actual constraint: the next
    main-model call needs ``input + max_tokens <= window`` and the
    compaction request needs ``input + summary_budget*1.3 <= window`` —
    whichever is larger bounds the input we can let accumulate.
    """
    try:
        configured = int(session_max_tokens) if session_max_tokens else 0
    except (TypeError, ValueError):
        configured = 0
    if configured <= 0:
        configured = DEFAULT_MAX_OUTPUT_TOKENS_GUESS
    return max(SUMMARIZER_OUTPUT_OVERHEAD_TOKENS, configured) + OUTPUT_RESERVE_SAFETY_PAD_TOKENS


class RealUsageProjector:
    """Tracks the last server-reported prompt token count and projects the
    current conversation size as ``real + delta-estimate``.

    ``record()`` is called when an API response reports usage: the
    ``prompt_tokens`` of that call is ground truth for "context size as of
    that call" (system prompt + tools + messages included). ``project()``
    returns that real count plus a chars/4 estimate of ONLY the messages
    appended since — never re-estimating the whole conversation.

    Projection invalidates (returns None) when:
      - no real count has been recorded yet (fresh / resumed session),
      - the message *list object* was replaced (compress / prune_only
        both return new lists),
      - messages were removed (e.g. thinking-prefill pops), or
      - the last message covered by the real count is no longer the same
        object (in-place surgery before the snapshot point).
    """

    def __init__(self) -> None:
        self._real_tokens = 0
        self._list_id: Optional[int] = None
        self._snapshot_len = 0
        self._last_counted_msg_id: Optional[int] = None

    def invalidate(self) -> None:
        """Drop the snapshot — next project() falls back to estimate mode."""
        self._real_tokens = 0
        self._list_id = None
        self._snapshot_len = 0
        self._last_counted_msg_id = None

    @property
    def has_real_count(self) -> bool:
        return self._real_tokens > 0

    def record(self, messages: Any, prompt_tokens: Any) -> None:
        """Snapshot a provider-reported prompt size for ``messages``.

        A non-positive / missing count is ignored (the previous snapshot
        stays valid — the conversation has only grown by appends, which
        project() still covers via delta estimation).
        """
        try:
            real = int(prompt_tokens or 0)
        except (TypeError, ValueError):
            real = 0
        if real <= 0 or not isinstance(messages, list):
            return
        self._real_tokens = real
        self._list_id = id(messages)
        self._snapshot_len = len(messages)
        self._last_counted_msg_id = id(messages[-1]) if messages else None

    def project(self, messages: Any) -> Optional[int]:
        """Projected current prompt size, or None when no valid real count."""
        if self._real_tokens <= 0 or not isinstance(messages, list):
            return None
        if id(messages) != self._list_id:
            return None
        if len(messages) < self._snapshot_len:
            return None
        if self._snapshot_len:
            if not messages or id(messages[self._snapshot_len - 1]) != self._last_counted_msg_id:
                return None
        delta = messages[self._snapshot_len:]
        delta_tokens = estimate_messages_tokens_rough(delta) if delta else 0
        return self._real_tokens + delta_tokens


def effective_compression_trigger_tokens(
    compressor: Any,
    *,
    real_mode: bool,
    output_reserve_tokens: int,
    threshold_pinned: bool,
) -> int:
    """The token line at which full compaction should fire.

        trigger = min(threshold_line, window - output_reserve)

    threshold_line is the compressor's existing ``threshold_tokens``
    (config-pinned value, the 0.85 estimate-mode default, or an
    aux-feasibility auto-lowered value — all already floored at
    MINIMUM_CONTEXT_LENGTH), bumped to 0.90×window in real-count mode
    when, and only when, it is still the un-pinned 0.85 default.

    The reserve line never drops the trigger below 50% of the window —
    tiny windows with a large configured max_tokens would otherwise
    compact every turn (#14695 territory).
    """
    window = int(getattr(compressor, "context_length", 0) or 0)
    threshold_line = int(getattr(compressor, "threshold_tokens", 0) or 0)
    if window <= 0:
        return threshold_line

    if real_mode and not threshold_pinned:
        current_percent = float(
            getattr(compressor, "threshold_percent", ESTIMATE_MODE_THRESHOLD) or 0.0
        )
        # Only bump the untouched default — a pinned config value or an
        # auto-lowered (aux-feasibility) threshold must keep winning.
        if abs(current_percent - ESTIMATE_MODE_THRESHOLD) < 1e-6:
            threshold_line = max(
                threshold_line, int(window * REAL_COUNT_MODE_THRESHOLD)
            )

    reserve_line = window - max(0, int(output_reserve_tokens or 0))
    reserve_line = max(reserve_line, window // 2)
    return min(threshold_line, reserve_line)


def resolve_compression_pressure(
    compressor: Any,
    projector: Optional[RealUsageProjector],
    messages: list,
    *,
    output_reserve_tokens: int,
    threshold_pinned: bool,
) -> Tuple[int, int, bool]:
    """Measurement + trigger line for the iteration-boundary check.

    Returns ``(measured_tokens, trigger_tokens, real_mode)``.

    Measurement preference order:
      1. Real-count projection (last provider prompt_tokens + delta
         estimate of appended messages) — real mode.
      2. Post-compaction sentinel (last_prompt_tokens == -1): report 0 so
         nothing re-triggers until the next API call reports real usage
         for the compacted conversation (#14695 guard).
      3. Stale-but-real last_prompt_tokens (list shape changed since) —
         estimate mode, matches the historical behavior.
      4. Full chars/4 estimate of the message list (#2153 fallback when
         usage was never reported).
    """
    projected = projector.project(messages) if projector is not None else None
    real_mode = projected is not None
    if real_mode:
        measured = int(projected)
    else:
        last = int(getattr(compressor, "last_prompt_tokens", 0) or 0)
        if last == -1:
            measured = 0
        elif last > 0:
            measured = last
        else:
            measured = estimate_messages_tokens_rough(messages)

    trigger = effective_compression_trigger_tokens(
        compressor,
        real_mode=real_mode,
        output_reserve_tokens=output_reserve_tokens,
        threshold_pinned=threshold_pinned,
    )
    return measured, trigger, real_mode


def should_compress_now(compressor: Any, measured_tokens: int, trigger_tokens: int) -> bool:
    """True when full compaction should run at this iteration boundary.

    Compares the measurement against the effective trigger line, then
    delegates to the compressor's own ``should_compress`` so its
    anti-thrash backoff (two ineffective compressions in a row → skip)
    keeps applying. The delegated value is raised to ``threshold_tokens``
    when the output reserve forced a trigger below the percent line —
    otherwise should_compress's internal threshold compare would veto the
    earlier trigger.
    """
    if measured_tokens <= 0 or trigger_tokens <= 0:
        return False
    if measured_tokens < trigger_tokens:
        return False
    threshold_tokens = int(getattr(compressor, "threshold_tokens", 0) or 0)
    return bool(compressor.should_compress(max(measured_tokens, threshold_tokens)))


# Critical line: the last synchronous-compaction trigger before a turn would
# overflow the provider context window and fall back to error-recovery
# compaction. The normal trigger leaves ``output_reserve`` of headroom and
# obeys the anti-thrash backoff; the critical line fires a FORCED compaction
# even when the backoff would otherwise skip, because at >=95% of the window
# the next call is about to 400 on context length.
CRITICAL_THRESHOLD = 0.95


def should_critical_compress_now(measured_tokens: int, window: int) -> bool:
    """True when compaction MUST run synchronously this iteration, bypassing the
    anti-thrash cooldown.

    ``measured_tokens`` is the projected (real-count) or estimated prompt size of
    what the next call would send; ``window`` is the model context length. At or
    above ``CRITICAL_THRESHOLD`` of the window, overflow safety wins over thrash
    avoidance — the caller forces compaction (``force=True``) regardless of the
    low-yield / ineffective-compression backoff.
    """
    if measured_tokens <= 0 or window <= 0:
        return False
    return measured_tokens >= int(window * CRITICAL_THRESHOLD)


def should_prune_only_now(compressor: Any, measured_tokens: int, trigger_tokens: int) -> bool:
    """True when the cheap no-LLM prune pass should run.

    The prune stage keeps its existing band: from the soft bar (72% of
    the window, owned by the compressor) up to the FULL-compaction
    trigger. When real-count mode raises the trigger above the
    compressor's threshold_tokens, the gap [threshold_tokens, trigger)
    stays prune territory — the compressor's own rate limit (regrow 5%
    of the window between attempts) is re-applied for that band.
    """
    if measured_tokens <= 0 or measured_tokens >= trigger_tokens:
        return False
    prune_check = getattr(compressor, "should_prune_only", None)
    if not callable(prune_check):
        return False
    threshold_tokens = int(getattr(compressor, "threshold_tokens", 0) or 0)
    if measured_tokens < threshold_tokens:
        return bool(prune_check(measured_tokens))
    # Band between the estimate-mode threshold and the raised real-count
    # trigger: should_prune_only() itself would return False (it treats
    # >= threshold_tokens as full-compress territory), so replicate its
    # rate limit here.
    window = int(getattr(compressor, "context_length", 0) or 0)
    regrow = int(window * 0.05) if window > 0 else 0
    last_attempt = int(getattr(compressor, "_last_prune_attempt_tokens", 0) or 0)
    return measured_tokens >= last_attempt + regrow


__all__ = [
    "check_compression_model_feasibility",
    "replay_compression_warning",
    "compress_context",
    "insert_preserved_context",
    "try_shrink_image_parts_in_messages",
    "ESTIMATE_MODE_THRESHOLD",
    "REAL_COUNT_MODE_THRESHOLD",
    "SUMMARIZER_OUTPUT_OVERHEAD_TOKENS",
    "OUTPUT_RESERVE_SAFETY_PAD_TOKENS",
    "DEFAULT_MAX_OUTPUT_TOKENS_GUESS",
    "compute_output_reserve_tokens",
    "RealUsageProjector",
    "effective_compression_trigger_tokens",
    "resolve_compression_pressure",
    "CRITICAL_THRESHOLD",
    "should_critical_compress_now",
    "should_compress_now",
    "should_prune_only_now",
]
