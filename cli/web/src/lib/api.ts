const BASE = "";

import type { DashboardTheme } from "@/themes/types";

// Ephemeral session token for protected endpoints.
// Injected into index.html by the server — never fetched via API.
declare global {
  interface Window {
    __ELEVATE_SESSION_TOKEN__?: string;
  }
}
let _sessionToken: string | null = null;
const SESSION_HEADER = "X-Elevate-Session-Token";

function setSessionHeader(headers: Headers, token: string): void {
  if (!headers.has(SESSION_HEADER)) {
    headers.set(SESSION_HEADER, token);
  }
}

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // Inject the session token into all /api/ requests.
  const headers = new Headers(init?.headers);
  const token = window.__ELEVATE_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function fetchBlob(url: string, init?: RequestInit): Promise<BlobResponse> {
  const headers = new Headers(init?.headers);
  const token = window.__ELEVATE_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return {
    blob: await res.blob(),
    contentType: res.headers.get("content-type") ?? "",
    fileName: res.headers.get("x-elevate-file-name") ?? "",
    size: Number(res.headers.get("x-elevate-file-size") ?? "0") || undefined,
  };
}

async function getSessionToken(): Promise<string> {
  if (_sessionToken) return _sessionToken;
  const injected = window.__ELEVATE_SESSION_TOKEN__;
  if (injected) {
    _sessionToken = injected;
    return _sessionToken;
  }
  throw new Error("Session token not available — page must be served by the Elevate dashboard server");
}

export const api = {
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getSessions: (limit = 20, offset = 0) =>
    fetchJSON<PaginatedSessions>(`/api/sessions?limit=${limit}&offset=${offset}`),
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
  renameSession: (id: string, title: string | null) =>
    fetchJSON<{ ok: boolean; title: string | null }>(
      `/api/sessions/${encodeURIComponent(id)}/title`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
    ),
  revealSession: (id: string) =>
    fetchJSON<{ ok: boolean; path: string }>(
      `/api/sessions/${encodeURIComponent(id)}/reveal`,
      {
        method: "POST",
      },
    ),
  deleteSession: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  previewFile: (path: string) =>
    fetchBlob(`/api/files/preview?path=${encodeURIComponent(path)}`),
  getLogs: (params: { file?: string; lines?: number; level?: string; component?: string }) => {
    const qs = new URLSearchParams();
    if (params.file) qs.set("file", params.file);
    if (params.lines) qs.set("lines", String(params.lines));
    if (params.level && params.level !== "ALL") qs.set("level", params.level);
    if (params.component && params.component !== "all") qs.set("component", params.component);
    return fetchJSON<LogsResponse>(`/api/logs?${qs.toString()}`);
  },
  getAnalytics: (days: number) =>
    fetchJSON<AnalyticsResponse>(`/api/analytics/usage?days=${days}`),
  getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
  getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
  saveConfig: (config: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
  saveConfigRaw: (yaml_text: string) =>
    fetchJSON<{ ok: boolean }>("/api/config/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text }),
    }),
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: async (key: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ key }),
    });
  },

  // Cron jobs
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: { prompt: string; schedule: string; name?: string; deliver?: string }) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  pauseCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
  resumeCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
  triggerCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
  deleteCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),

  // Skills & Toolsets
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // Session search (FTS5)
  searchSessions: (q: string) =>
    fetchJSON<SessionSearchResponse>(`/api/sessions/search?q=${encodeURIComponent(q)}`),

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean; provider: string }>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },
  startOAuthLogin: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthStartResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: "{}",
      },
    );
  },
  submitOAuthCode: async (providerId: string, sessionId: string, code: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthSubmitResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: JSON.stringify({ session_id: sessionId, code }),
      },
    );
  },
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: async (sessionId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean }>(
      `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },

  // Gateway / update actions
  startGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/start", { method: "POST" }),
  restartGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/restart", { method: "POST" }),
  updateElevate: () =>
    fetchJSON<ActionResponse>("/api/elevate/update", { method: "POST" }),
  getActionStatus: (name: string, lines = 200) =>
    fetchJSON<ActionStatusResponse>(
      `/api/actions/${encodeURIComponent(name)}/status?lines=${lines}`,
    ),

  // Dashboard plugins
  getPlugins: () =>
    fetchJSON<PluginManifestResponse[]>("/api/dashboard/plugins"),
  rescanPlugins: () =>
    fetchJSON<{ ok: boolean; count: number }>("/api/dashboard/plugins/rescan"),

  // Dashboard themes
  getThemes: () =>
    fetchJSON<DashboardThemesResponse>("/api/dashboard/themes"),
  setTheme: (name: string) =>
    fetchJSON<{ ok: boolean; theme: string }>("/api/dashboard/theme", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  // Agent Hub
  getAgentHub: () => fetchJSON<AgentHubSnapshot>("/api/agent-hub"),
  getHarness: () => fetchJSON<HarnessSnapshot>("/api/harness"),

  // Real-estate source connectors and integrations
  getSourceConnectors: () =>
    fetchJSON<SourceConnectorsResponse>("/api/source-connectors"),
  getSourceRecords: (sourceId: string, limit = 12) =>
    fetchJSON<SourceRecordsResponse>(
      `/api/source-connectors/${encodeURIComponent(sourceId)}/records?limit=${limit}`,
    ),
  getSourceInbox: (limit = 16) =>
    fetchJSON<SourceInboxResponse>(`/api/source-inbox?limit=${limit}`),
  updateSourceInboxThread: (sourceId: string, threadId: string, action: "done" | "archive" | "restore" | "open") =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/thread", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceId, threadId, action }),
    }),
  scaffoldSourceConnector: (sourceId: string) =>
    fetchJSON<SourceConnectorsResponse>("/api/source-connectors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "scaffold", sourceId }),
    }),
  getIntegrations: () => fetchJSON<IntegrationSettingsResponse>("/api/integrations"),
  saveIntegrations: (crm: CrmIntegrationForm) =>
    fetchJSON<IntegrationSettingsResponse>("/api/integrations", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(crm),
    }),
  testIntegration: (crm: CrmIntegrationForm) =>
    fetchJSON<IntegrationTestResponse>("/api/integrations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...crm, action: "test" }),
    }),
};

export type SourceConnectorState =
  | "not_configured"
  | "connected"
  | "import_only"
  | "needs_operator"
  | "blocked"
  | "error";

export interface SourceConnectionBlueprint {
  id: string;
  source: string;
  category: "messages" | "leads" | "operations" | "admin" | "forms" | string;
  informationNeeded: string;
  connectionLayer: string;
  uiDestination: string;
  successSignal: string;
  prompt: string;
}

export interface SourceConnectorStatus {
  id: string;
  label: string;
  category: string;
  state: SourceConnectorState;
  sourceExists: boolean;
  sourceDir: string;
  sourcePath: string;
  statusPath: string;
  artifactsDir: string;
  connectionType: string | null;
  syncMode: string | null;
  authStatus: string | null;
  initializeBehavior: "local_messages_import" | "composio_social_setup" | "agent_setup_task" | string;
  ownerAgent: string;
  enabledUiSurfaces: string[];
  connected: boolean;
  importOnly: boolean;
  blocked: boolean;
  lastError: string | null;
  nextOperatorStep: string | null;
  lastCheckedAt: string | null;
  recordCounts: Record<string, number>;
  prompt: string;
}

export interface SourceConnectorsResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  blueprints: SourceConnectionBlueprint[];
  promptCategories: Array<{ id: string; label: string }>;
  connectors: SourceConnectorStatus[];
}

export interface SourceRecord {
  source_id?: string;
  source_record_id?: string;
  source_url?: string | null;
  display_name?: string;
  channel?: string;
  direction?: "inbound" | "outbound" | string;
  timestamp?: string;
  day?: string;
  text?: string;
  summary?: string;
  title?: string;
  status?: string;
  confidence?: number;
  tags?: string[];
  target_ui_surfaces?: string[];
  conversation_id?: string;
  contact_id?: string | null;
  message_count?: number;
  inbound_count?: number;
  outbound_count?: number;
  total_messages?: number;
  last_text?: string;
  last_message_at?: string;
  last_seen_at?: string;
  [key: string]: unknown;
}

export interface SourceRecordsResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  sourceId: string;
  source: SourceConnectorStatus;
  limit: number;
  records: {
    contacts: SourceRecord[];
    conversations: SourceRecord[];
    messages: SourceRecord[];
    messageDays: SourceRecord[];
    leadEvents: SourceRecord[];
    tasks: SourceRecord[];
  };
}

export interface SourceInboxThread {
  id: string;
  sourceId: string;
  sourceLabel: string;
  sourceState: SourceConnectorState | string | null;
  threadId: string;
  conversationId: string | null;
  contactId: string | null;
  personName: string;
  channel: string;
  latestText: string;
  latestAt: string;
  direction: "inbound" | "outbound" | string | null;
  messageCount: number;
  inboundCount: number;
  outboundCount: number;
  heatScore: number;
  heatLabel: "hot" | "warm" | "watch" | "normal" | string;
  status: "open" | "done" | "archived" | string;
  record: SourceRecord;
}

export interface SourceInboxResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  limit: number;
  recordCounts: Record<string, number>;
  hiddenCounts: Record<string, number>;
  sources: SourceConnectorStatus[];
  threads: SourceInboxThread[];
}

export interface CrmIntegrationForm {
  provider: string;
  label: string;
  apiKeyEnv: string;
  apiKey?: string;
  hasApiKey: boolean;
  apiKeyPreview: string | null;
  baseUrl: string;
  authType: "header" | "query" | string;
  authHeader: string;
  authPrefix: string;
  authQueryParam: string;
  dbColumns: {
    leadId: string;
    stage: string;
    tags: string;
  };
  endpoints: {
    leads: string;
    lead: string;
    notes: string;
  };
}

export interface IntegrationSettingsResponse {
  configPath: string;
  secretsPath: string;
  sourceRoot: string;
  crm: CrmIntegrationForm;
}

export interface IntegrationTestResponse {
  success: boolean;
  status?: number;
  message?: string;
  error?: string;
}

export interface ActionResponse {
  name: string;
  ok: boolean;
  pid: number;
}

export interface ActionStatusResponse {
  exit_code: number | null;
  lines: string[];
  name: string;
  pid: number | null;
  running: boolean;
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_health_url: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  project_root: string;
  elevate_home: string;
  latest_config_version: number;
  release_date: string;
  version: string;
}

export interface AgentHubAgent {
  id: string;
  name: string;
  role: string;
  description: string;
  enabled: boolean;
  platforms: string[];
  session_sources: string[];
  skills: string[];
  toolsets: string[];
  status: "online" | "ready" | "offline" | "disabled" | "needs_model" | string;
  session_count: number;
  active_session_count: number;
  has_prompt: boolean;
}

export interface AgentHubPlatform {
  name: string;
  enabled: boolean;
  configured: boolean;
  token_configured: boolean;
  api_key_configured: boolean;
  home_channel: { platform: string; chat_id: string; name: string } | null;
  reply_to_mode: string;
  runtime?: PlatformStatus;
  approved_users: number;
  pending_pairings: Array<{
    code: string;
    user_id: string;
    user_name: string;
    age_minutes: number;
  }>;
  error?: string;
}

export interface AgentHubMemoryNode {
  id: string;
  label: string;
  type: "entity" | "fact" | string;
  weight: number;
  category?: string;
}

export interface AgentHubMemoryEdge {
  source: string;
  target: string;
  type: string;
}

export interface AgentHubSessionSummary {
  total: number;
  active: number;
  recent: Array<{
    id: string;
    title: string;
    source: string;
    started_at: number;
    last_active: number;
    is_active: boolean;
    message_count: number;
    tool_call_count: number;
    model: string;
  }>;
  by_source: Record<string, number>;
  by_day: Record<string, number>;
  error: string;
}

export interface AgentHubSnapshot {
  generated_at: number;
  config_path: string;
  elevate_home: string;
  gateway: {
    running: boolean;
    pid: number | null;
    state: string | null;
    updated_at: string | null;
    active_agents: number;
    exit_reason: string | null;
  };
  model: {
    model: string;
    provider: string;
    base_url_configured: boolean;
    api_key_configured: boolean;
    configured: boolean;
  };
  access: {
    profile: string;
    label: string;
    affiliation: Record<string, unknown>;
    entitlements: Record<string, { status?: string; owned_snapshot?: boolean }>;
  };
  agents: AgentHubAgent[];
  orchestration?: {
    agents: unknown[];
    runs: unknown[];
    active_runs: number;
    error?: string;
  };
  platforms: AgentHubPlatform[];
  sessions: AgentHubSessionSummary;
  memory: {
    provider: string;
    db_path: string;
    db_exists: boolean;
    facts: number;
    entities: number;
    embeddings: number;
    indexed_facts: number;
    documents: number;
    chunks: number;
    indexed_chunks: number;
    community_reports: number;
    relations: number;
    modal_assets: number;
    journal: {
      total: number;
      pending: number;
      processed: number;
      failed: number;
      active_session_count: number;
      session_segment_count: number;
      sessions: Array<{
        session_id: string;
        session_day: string;
        total: number;
        pending: number;
        processed: number;
        failed: number;
        latest_created_at: string | null;
      }>;
    };
    embedding: {
      enabled: boolean;
      provider: string;
      model: string;
      api_key_env: string;
    };
    graph: { nodes: AgentHubMemoryNode[]; edges: AgentHubMemoryEdge[] };
    error: string;
  };
  cron: {
    total: number;
    enabled: number;
    paused: number;
    recent: Array<{
      id: string;
      name: string;
      schedule: unknown;
      enabled: boolean;
      deliver: string;
    }>;
    error: string;
  };
  skills: {
    total: number;
    enabled: number;
    disabled: number;
    categories: Record<string, number>;
    error: string;
  };
  toolsets: {
    total: number;
    enabled: string[];
    known: Array<{
      name: string;
      label: string;
      description: string;
      enabled: boolean;
    }>;
    error: string;
  };
  harness?: HarnessSnapshot | { error?: string; available?: boolean };
}

export interface HarnessProfile {
  name: string;
  toolsets: string[];
  loaded_tools: number;
  requested_tools: number;
  system_prompt_tokens: number;
  tool_schema_tokens: number;
  request_tokens: number;
  savings_pct: number | null;
  issues: number;
}

export interface HarnessSnapshot {
  generated_at: string;
  elevate_home: string;
  server: {
    pattern: string;
    gateway_running: boolean;
    gateway_pid: number | null;
    clients: Array<{ id: string; label: string; connected: boolean }>;
  };
  orchestration: {
    visible: boolean;
    coordinator: string;
    agent_states: string[];
    total_agents: number;
    active_runs: number;
    recent_runs: number;
    route_labeled_runs: number;
    recent_events: number;
    event_tail: Array<{
      run_id?: string | null;
      type?: string | null;
      message?: string | null;
      timestamp?: string | null;
    }>;
    plan_graph: {
      ready_runs: number;
      blocked_runs: number;
      active_runs: number;
      completed_runs: number;
      cycle_runs: number;
      unresolved_dependencies: number;
      next_ready_run_ids: string[];
    };
    lifecycle_states: string[];
  };
  skills: {
    mode: string;
    index_visible: boolean;
    enabled: number;
    total: number;
    details_loaded_on_demand: boolean;
    tool_index_visible: boolean;
    enabled_toolsets: string[];
  };
  memory: {
    mode: string;
    provider: string;
    embeddings_enabled: boolean;
    embedding_provider: string;
    embedding_model: string;
    pending_turns: number;
    processed_turns: number;
    session_segments: number;
    graph_nodes: number;
    graph_edges: number;
    pipeline: {
      derived_from_journal: boolean;
      state: string;
      search: string;
      verify: string;
      inject: string;
      maintain: string;
      active: boolean;
      backlog: number;
      failure_count: number;
      indexed_facts: number;
      facts: number;
      last_step?: string;
      updated_at?: string;
      recent_events?: Array<{
        kind?: string;
        message?: string;
        timestamp?: string;
        state?: string;
        step?: string;
        status?: string;
        data?: Record<string, unknown>;
      }>;
    };
  };
  safety: {
    dangerous_command_mode: string;
    external_actions_policy: string;
    human_communication_requires_review: boolean;
    send_message_available: boolean;
    approval_surfaces: string[];
  };
  performance: {
    available: boolean;
    error: string;
    model?: string;
    baseline_request_tokens?: number;
    best_profile?: HarnessProfile | null;
    worst_profile?: HarnessProfile | null;
    profiles: HarnessProfile[];
  };
  recommendations: string[];
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsSkillEntry {
  skill: string;
  view_count: number;
  manage_count: number;
  total_count: number;
  percentage: number;
  last_used_at: number | null;
}

export interface AnalyticsSkillsSummary {
  total_skill_loads: number;
  total_skill_edits: number;
  total_skill_actions: number;
  distinct_skills_used: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  skills: {
    summary: AnalyticsSkillsSummary;
    top_skills: AnalyticsSkillEntry[];
  };
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr: string; display: string };
  schedule_display: string;
  enabled: boolean;
  state: string;
  deliver?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export interface BlobResponse {
  blob: Blob;
  contentType: string;
  fileName: string;
  size?: number;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

// ── Model info types ──────────────────────────────────────────────────

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      user_code: string;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
}

// ── Dashboard theme types ──────────────────────────────────────────────

export interface DashboardThemeSummary {
  description: string;
  label: string;
  name: string;
  /** Full theme definition for user themes; undefined for built-ins
   *  (which the frontend already has locally). */
  definition?: DashboardTheme;
}

export interface DashboardThemesResponse {
  active: string;
  themes: DashboardThemeSummary[];
}

// ── Dashboard plugin types ─────────────────────────────────────────────

export interface PluginManifestResponse {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}
