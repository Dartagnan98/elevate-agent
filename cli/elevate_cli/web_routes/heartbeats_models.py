"""Request body models for heartbeat routes."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class HeartbeatSurfaceCreateBody(BaseModel):
    surface: str
    title: Optional[str] = None
    name: Optional[str] = None
    schedule: Optional[str] = None
    goal: Optional[str] = None
    experiment: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class AgentHeartbeatMdBody(BaseModel):
    content: str


class HeartbeatCycleCreateBody(BaseModel):
    name: str
    metric: str
    metric_type: str
    direction: str
    window: str
    every_n_runs: Optional[int] = None
    measurement: Optional[str] = None
    approval_required: Optional[bool] = None
    surface: Optional[str] = None
    created_by: Optional[str] = None


class HeartbeatCyclePatchBody(BaseModel):
    metric_type: Optional[str] = None
    direction: Optional[str] = None
    window: Optional[str] = None
    loop_interval: Optional[str] = None
    every_n_runs: Optional[int] = None
    surface: Optional[str] = None
    measurement: Optional[str] = None
    enabled: Optional[bool] = None


class HeartbeatRouteBody(BaseModel):
    deliver: str


class HeartbeatSurfaceEnabledBody(BaseModel):
    enabled: bool


class HeartbeatConfigPatchBody(BaseModel):
    goal: Optional[str] = None
    cadence: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    timezone: Optional[str] = None
    day_mode_start: Optional[str] = None
    day_mode_end: Optional[str] = None
    communication_style: Optional[str] = None
    approval_rules: Optional[Dict[str, Any]] = None
    max_session_seconds: Optional[int] = None
    heartbeat_report_mode: Optional[str] = None
    report_mode: Optional[str] = None
    notification_mode: Optional[str] = None


class HeartbeatGoalItem(BaseModel):
    id: Optional[str] = None
    title: str
    progress: Optional[int] = None
    order: Optional[int] = None


class HeartbeatGoalsPatchBody(BaseModel):
    bottleneck: Optional[str] = None
    daily_focus: Optional[str] = None
    goals: Optional[List[HeartbeatGoalItem]] = None


class HeartbeatAutomationEnabledBody(BaseModel):
    enabled: bool
