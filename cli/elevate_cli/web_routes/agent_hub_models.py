"""Request body models for Agent Hub routes."""

from typing import Any, Dict, Optional

from pydantic import BaseModel


class AgentHandoffCreate(BaseModel):
    fromAgentId: str
    toAgentId: str
    task: str
    title: Optional[str] = None
    priority: str = "normal"
    dealId: Optional[str] = None
    profileId: Optional[str] = None
    contactId: Optional[str] = None
    conversationId: Optional[str] = None
    sourceRunId: Optional[str] = None
    parentHandoffId: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    idempotencyKey: Optional[str] = None
    runNow: bool = False


class AgentHandoffDrain(BaseModel):
    toAgentId: Optional[str] = None
    limit: int = 50


class AgentHandoffMessageCreate(BaseModel):
    fromAgentId: str
    toAgentId: Optional[str] = None
    kind: str = "note"
    content: str = ""
    payload: Optional[Dict[str, Any]] = None


class AgentHandoffResultCreate(BaseModel):
    status: str = "completed"
    result: Optional[Dict[str, Any]] = None
    errorMessage: Optional[str] = None
    humanPrompt: Optional[Dict[str, Any]] = None
    idempotencyKey: Optional[str] = None
    actor: str = "human:web"


class AgentHandoffApproveCreate(BaseModel):
    approved: bool = True
    runNow: bool = True
    actor: str = "human:web"


class AgentConfigPatch(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    role: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    skills: Optional[list[str]] = None
    toolsets: Optional[list[str]] = None
    platforms: Optional[list[str]] = None
    session_sources: Optional[list[str]] = None
    runtime: Optional[Any] = None
    routing: Optional[Dict[str, Any]] = None
    safety: Optional[Dict[str, Any]] = None
    identity: Optional[Dict[str, Any]] = None
    soul: Optional[Dict[str, Any]] = None
    lifecycle: Optional[Dict[str, Any]] = None
    ecosystem: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    runtime_type: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    working_directory: Optional[str] = None
    timezone: Optional[str] = None
    ctx_warning_threshold: Optional[int] = None
    ctx_handoff_threshold: Optional[int] = None
    codex_context_cap: Optional[int] = None
    dangerously_skip_permissions: Optional[bool] = None
    day_mode_start: Optional[str] = None
    day_mode_end: Optional[str] = None
    communication_style: Optional[str] = None
    startup_delay: Optional[int] = None
    max_session_seconds: Optional[int] = None
    max_crashes_per_day: Optional[int] = None
    crash_window: Optional[Dict[str, Any]] = None
    telegram_polling: Optional[bool] = None
    approval_rules: Optional[Dict[str, Any]] = None


class AgentConfigCreate(AgentConfigPatch):
    id: Optional[str] = None
    name: str
    memorySeed: Optional[Dict[str, Any]] = None
    memory_seed: Optional[Dict[str, Any]] = None


class AgentWorkerAction(BaseModel):
    agentId: Optional[str] = None
