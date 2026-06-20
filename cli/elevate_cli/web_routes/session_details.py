"""Session detail routes for the dashboard."""

import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


GetSessionDb = Callable[[], Any]
OpenInFileManager = Callable[[Path], None]
SessionRevealTarget = Callable[[str], Path]
LiveSubagentChildSessionIds = Callable[[], set[str]]


class SessionTitleUpdate(BaseModel):
    title: Optional[str] = None


_SESSION_FILE_ARG_KEYS = (
    "path", "file_path", "target_file", "filename", "file", "notebook_path",
)
_SESSION_FILE_RESULT_KEYS = _SESSION_FILE_ARG_KEYS + (
    "files", "paths", "files_read", "files_written", "output_path",
    "output_file", "artifact", "artifacts", "artifact_path",
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w/])(?:/Users|/tmp|/private/tmp|/var/folders|/Volumes)/[^\s`'\"<>),]+"
)


def _subagent_meta(db: Any, session_id: str) -> Dict[str, Any]:
    """For a subagent session, surface its parent and display agent."""
    out: Dict[str, Any] = {}
    try:
        row = db.get_session(session_id) or {}
        parent = row.get("parent_session_id") or row.get("parentSessionId")
        if parent:
            out["parent_session_id"] = parent
        mc = row.get("model_config") or row.get("modelConfig")
        if isinstance(mc, str):
            try:
                mc = json.loads(mc)
            except Exception:
                mc = {}
        agent_id = (mc or {}).get("agent_id") if isinstance(mc, dict) else None
        if agent_id:
            out["agent_id"] = agent_id
            try:
                from elevate_cli.agent_hub import get_agent_def

                d = get_agent_def(str(agent_id))
                if isinstance(d, dict) and d.get("name"):
                    out["agent_name"] = d.get("name")
            except Exception:
                pass
    except Exception:
        pass
    return out


def _session_identity_payload(identity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requested_session_id": identity.get("requested_session_id"),
        "lineage_root_id": identity.get("lineage_root_id"),
        "active_session_id": identity.get("active_session_id"),
        "session_kind": identity.get("session_kind"),
        "is_compression_tip": identity.get("is_compression_tip"),
        "parent_session_id": identity.get("parent_session_id"),
        "agent_id": identity.get("agent_id"),
        "agent_name": identity.get("agent_name"),
    }


def _is_cron_session_row(session: Dict[str, Any] | None, session_id: str = "") -> bool:
    sid = str((session or {}).get("id") or session_id or "")
    source = str((session or {}).get("source") or "")
    return source == "cron" or sid.startswith("cron_")


def _resolve_active_session_or_404(db: Any, session_id: str) -> tuple[str, str, Dict[str, Any]]:
    sid = db.resolve_session_id(session_id)
    if not sid:
        raise HTTPException(status_code=404, detail="Session not found")
    identity = db.resolve_canonical_session_identity(sid)
    requested_session = db.get_session(sid)
    if _is_cron_session_row(requested_session, sid):
        identity["active_session_id"] = sid
        identity["lineage_root_id"] = identity.get("lineage_root_id") or sid
        identity["session_kind"] = "cron"
        identity["is_compression_tip"] = True
        return sid, sid, identity
    active_id = str(identity.get("active_session_id") or sid)
    if not db.get_session(active_id):
        active_id = sid
        identity["active_session_id"] = sid
        identity["lineage_root_id"] = identity.get("lineage_root_id") or sid
        identity["session_kind"] = identity.get("session_kind") or "chat"
    if identity.get("session_kind") == "subagent":
        identity.update(_subagent_meta(db, active_id))
    return sid, active_id, identity


def _read_session_checkpoint(db: Any, *session_ids: Any) -> dict:
    seen: set[str] = set()
    for raw_sid in session_ids:
        sid = str(raw_sid or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            raw = db.get_meta(f"session_checkpoint:{sid}")
        except Exception:
            continue
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _content_as_text(content: Any) -> str:
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


def _append_path_values(value: Any, out: list[str], seen: set[str], *, recursive: bool = True) -> None:
    if len(out) >= 2000:
        return
    if isinstance(value, str):
        raw = value.strip()
        if raw and raw not in seen:
            seen.add(raw)
            out.append(raw)
        return
    if isinstance(value, list):
        for item in value:
            _append_path_values(item, out, seen, recursive=recursive)
        return
    if recursive and isinstance(value, dict):
        for item in value.values():
            _append_path_values(item, out, seen, recursive=recursive)


def _extract_session_file_candidates(messages: list[dict]) -> list[str]:
    raw_seen: set[str] = set()
    candidates: list[str] = []
    for msg in messages:
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else None
                args = (fn or {}).get("arguments", call.get("arguments"))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        args = None
                if isinstance(args, dict):
                    for key in _SESSION_FILE_ARG_KEYS:
                        _append_path_values(args.get(key), candidates, raw_seen, recursive=True)

        content_text = _content_as_text(msg.get("content"))
        if content_text:
            for match in _ABSOLUTE_PATH_RE.findall(content_text):
                _append_path_values(match.rstrip(".:;"), candidates, raw_seen, recursive=False)
            if msg.get("role") == "tool" and "{" in content_text:
                try:
                    data = json.loads(content_text)
                except (json.JSONDecodeError, TypeError, ValueError):
                    data = None
                if isinstance(data, dict):
                    for key in _SESSION_FILE_RESULT_KEYS:
                        _append_path_values(data.get(key), candidates, raw_seen, recursive=True)
    return candidates


def _resolve_existing_session_files(candidates: list[str], *, limit: int = 500) -> list[dict]:
    files: list[dict] = []
    out_seen: set[str] = set()
    for raw in candidates:
        try:
            cleaned = re.sub(r":\d+(?::\d+)?$", "", raw.strip())
            path = Path(os.path.expandvars(cleaned)).expanduser()
        except (OSError, ValueError):
            continue
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_file():
                continue
        except OSError:
            continue
        key = str(resolved)
        if key in out_seen:
            continue
        out_seen.add(key)
        files.append({"path": key, "name": resolved.name})
        if len(files) >= limit:
            break
    return files


def _artifact_kind(path: Path, mime_type: Optional[str]) -> str:
    suffix = path.suffix.lower()
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if mime_type and mime_type.startswith("video/"):
        return "video"
    if mime_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown", ".txt", ".json", ".csv", ".tsv", ".html", ".svg"}:
        return "document"
    if suffix in {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx"}:
        return "document"
    return "file"


def create_session_detail_router(
    *,
    get_session_db: GetSessionDb,
    session_reveal_target: SessionRevealTarget,
    open_in_file_manager: OpenInFileManager,
    live_subagent_child_session_ids: LiveSubagentChildSessionIds,
    log: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            session = db.get_session(active_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            session.update(_session_identity_payload(identity))
            session["requested_session_id"] = sid
            return session
        finally:
            db.close()

    @router.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            messages = db.get_messages(active_id)
            _INTERNAL_ROW_PREFIXES = (
                "[CONTEXT COMPACTION",
                "[Your latest Plan panel plan was preserved",
                "[Your active task list was preserved",
                "[RECENT AUTONOMOUS ACTIVITY",
            )
            display: list = []
            for msg in messages:
                if not isinstance(msg, dict) or msg.get("role") != "user":
                    display.append(msg)
                    continue
                content = msg.get("content")
                text = content if isinstance(content, str) else ""
                stripped = text.lstrip()
                if stripped.startswith(_INTERNAL_ROW_PREFIXES):
                    continue
                if stripped.startswith("[Elevation Hub interface context]"):
                    marker = "User request:"
                    idx = stripped.find(marker)
                    if idx != -1:
                        msg = {**msg, "content": stripped[idx + len(marker):].strip()}
                display.append(msg)
            messages = display
            for i, msg in enumerate(messages):
                if isinstance(msg, dict) and not msg.get("client_message_id"):
                    msg["client_message_id"] = f"legacy.{active_id}.{i}"
                if isinstance(msg, dict):
                    msg["message_id"] = msg["client_message_id"]
            return {
                "session_id": active_id,
                "requested_session_id": sid,
                **_session_identity_payload(identity),
                "messages": messages,
            }
        finally:
            db.close()

    @router.get("/api/sessions/{session_id}/todos")
    async def get_session_todos(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            checkpoint = _read_session_checkpoint(
                db, active_id, identity.get("lineage_root_id"), sid
            )
            messages = db.get_messages(active_id)
        finally:
            db.close()

        todos: list = []
        updated_at = checkpoint.get("updated_at") if checkpoint else None
        if isinstance(checkpoint.get("todos"), list):
            todos = [t for t in checkpoint["todos"] if isinstance(t, dict)]
        from tools.todo_tool import parse_todo_injection

        for msg in reversed(messages):
            content = _content_as_text(msg.get("content"))
            if msg.get("role") == "tool" and '"todos"' in content:
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    data = None
                if isinstance(data, dict) and isinstance(data.get("todos"), list):
                    todos = [t for t in data["todos"] if isinstance(t, dict)]
                    updated_at = msg.get("created_at") or msg.get("timestamp")
                    break
            injected = parse_todo_injection(content)
            if injected:
                todos = injected
                updated_at = msg.get("created_at") or msg.get("timestamp")
                break

        def _count(status: str) -> int:
            return sum(1 for t in todos if t.get("status") == status)

        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "todos": todos,
            "updated_at": updated_at,
            "summary": {
                "total": len(todos),
                "pending": _count("pending"),
                "in_progress": _count("in_progress"),
                "completed": _count("completed"),
                "cancelled": _count("cancelled"),
            },
        }

    @router.get("/api/sessions/{session_id}/plan")
    async def get_session_plan(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            checkpoint = _read_session_checkpoint(
                db, active_id, identity.get("lineage_root_id"), sid
            )
            messages = db.get_messages(active_id)
        finally:
            db.close()

        plan_md = str(checkpoint.get("plan") or "") if checkpoint else ""
        title = str(checkpoint.get("plan_title") or "") if checkpoint else ""
        updated_at = checkpoint.get("updated_at") if checkpoint else None
        from tools.present_plan_tool import PLAN_INJECTION_HEADER, extract_latest_plan_from_messages

        latest = extract_latest_plan_from_messages(messages)
        if latest:
            plan_md, parsed_title = latest
            title = parsed_title or ""
            for msg in reversed(messages):
                content = _content_as_text(msg.get("content"))
                if PLAN_INJECTION_HEADER in content or '"plan"' in content:
                    updated_at = msg.get("created_at") or msg.get("timestamp")
                    break

        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "plan": plan_md,
            "title": title,
            "updated_at": updated_at,
        }

    @router.get("/api/sessions/{session_id}/files")
    async def get_session_files(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            checkpoint = _read_session_checkpoint(
                db, active_id, identity.get("lineage_root_id"), sid
            )
            messages = db.get_messages(active_id)
        finally:
            db.close()

        checkpoint_files = checkpoint.get("files") if isinstance(checkpoint, dict) else None
        candidates = [str(p) for p in checkpoint_files if isinstance(p, str)] if isinstance(checkpoint_files, list) else []
        if not candidates:
            candidates = _extract_session_file_candidates(messages)
        files = _resolve_existing_session_files(candidates)
        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "files": files,
        }

    @router.get("/api/sessions/{session_id}/turn_usage")
    async def get_session_turn_usage(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            rows = db.turn_usage_for_session(active_id)
        finally:
            db.close()

        fields = (
            "message_id", "model", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
            "total_tokens", "estimated_cost_usd", "latency_ms", "timestamp",
        )
        return {
            "session_id": active_id,
            "requested_session_id": sid,
            "turn_usage": [{k: r.get(k) for k in fields} for r in rows],
        }

    @router.get("/api/sessions/{session_id}/artifacts")
    async def get_session_artifacts(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            checkpoint = _read_session_checkpoint(
                db, active_id, identity.get("lineage_root_id"), sid
            )
            messages = db.get_messages(active_id)
        finally:
            db.close()

        checkpoint_files = checkpoint.get("files") if isinstance(checkpoint, dict) else None
        candidates = [str(p) for p in checkpoint_files if isinstance(p, str)] if isinstance(checkpoint_files, list) else []
        if not candidates:
            candidates = _extract_session_file_candidates(messages)

        artifacts: list[dict] = []
        for file_entry in _resolve_existing_session_files(candidates, limit=500):
            path = Path(file_entry["path"])
            mime_type, _encoding = mimetypes.guess_type(str(path))
            try:
                stat = path.stat()
                size = stat.st_size
                modified_at = stat.st_mtime
            except OSError:
                size = None
                modified_at = None
            artifacts.append({
                "id": hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16],
                "path": str(path),
                "name": path.name,
                "kind": _artifact_kind(path, mime_type),
                "mime_type": mime_type,
                "size": size,
                "modified_at": modified_at,
            })

        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "artifacts": artifacts,
        }

    @router.get("/api/sessions/{session_id}/children")
    async def get_session_children(session_id: str):
        db = get_session_db()
        try:
            sid, active_id, identity = _resolve_active_session_or_404(db, session_id)
            try:
                db.finalize_interrupted_delegate_children(
                    active_id,
                    active_child_session_ids=live_subagent_child_session_ids(),
                )
            except Exception as exc:
                log.debug(
                    "Failed to finalize interrupted delegate children for %s: %s",
                    active_id,
                    exc,
                )
            children = db.list_child_sessions(active_id)
        finally:
            db.close()

        return {
            "session_id": active_id,
            "requested_session_id": sid,
            **_session_identity_payload(identity),
            "children": children,
        }

    @router.put("/api/sessions/{session_id}/title")
    async def update_session_title_endpoint(session_id: str, payload: SessionTitleUpdate):
        db = get_session_db()
        try:
            sid = db.resolve_session_id(session_id)
            if not sid:
                raise HTTPException(status_code=404, detail="Session not found")
            try:
                updated = db.set_session_title(sid, payload.title or "")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if not updated:
                raise HTTPException(status_code=404, detail="Session not found")
            session = db.get_session(sid)
            return {"ok": True, "title": session.get("title") if session else None}
        finally:
            db.close()

    @router.post("/api/sessions/{session_id}/reveal")
    async def reveal_session_endpoint(session_id: str):
        db = get_session_db()
        try:
            sid = db.resolve_session_id(session_id)
            if not sid or not db.get_session(sid):
                raise HTTPException(status_code=404, detail="Session not found")
            target = session_reveal_target(sid)
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
            open_in_file_manager(target)
            return {"ok": True, "path": str(target)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"File manager unavailable: {exc}")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not open session location: {exc}")
        finally:
            db.close()

    @router.delete("/api/sessions/{session_id}")
    async def delete_session_endpoint(session_id: str):
        db = get_session_db()
        deleted = False
        try:
            resolver = getattr(db, "resolve_session_id", None)
            sid = resolver(session_id) if callable(resolver) else session_id
            if sid:
                deleted = bool(db.delete_session(sid))
            try:
                from elevate_cli.data.chat_sessions import delete_session as delete_chat_session

                deleted = bool(delete_chat_session(sid or session_id)) or deleted
            except Exception:
                log.debug("PG chat session delete failed", exc_info=True)
            if not deleted:
                raise HTTPException(status_code=404, detail="Session not found")
            return {"ok": True}
        finally:
            db.close()

    return router
