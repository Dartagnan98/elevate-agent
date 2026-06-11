const BASE = "";

import type {
  LicenseStatusResponse,
  LicenseActivateResponse,
  LicenseSyncSkillsResponse,
  LicenseLogoutResponse,
  AccessStatusResponse,
  SourceConnectorsResponse,
  SourceRecordsResponse,
  OutreachTemplate,
  OutreachOverview,
  AdminDealSide,
  AdminDealToggleValue,
  AdminDealCreateRequest,
  AdminProfilePromotionRequest,
  AdminProfilePromotionResponse,
  AdminDeal,
  DealContactCreateRequest,
  DealContact,
  DealAttachmentCreateRequest,
  DealAttachment,
  AdminAction,
  AdminActionRun,
  AdminDealTasksResponse,
  AdminDealTaskRunRequest,
  AdminUpcomingEventsResponse,
  DealRunResultRequest,
  DealContext,
  AdminProvinceGuide,
  AdminProvinceGuidesResponse,
  AdminProvinceGuideImportResult,
  AdminJurisdiction,
  AdminJurisdictionUpdateRequest,
  AdminSetupSnapshot,
  AdminSetupUpdateRequest,
  PackOnboardingSnapshot,
  PackOnboardingUpdateRequest,
  LeadsSetupSnapshot,
  LeadsSetupItemUpdate,
  AgentSetupSnapshot,
  AgentSetupItemUpdate,
  AdminDealsResponse,
  AdminContactsResponse,
  ComposioStatus,
  AyrshareStatus,
  SocialSnapshot,
  SocialIdea,
  SocialMetricRow,
  ComposioApiResult,
  ComposioConnectedAccount,
  ComposioToolkit,
  ComposioConnectInitResponse,
  ComposioToolkitDetails,
  ThreadContextResponse,
  SourceInboxResponse,
  SourceInboxSentResponse,
  TodayDashboardResponse,
  SourceInboxProfileStatus,
  CrmIntegrationForm,
  IntegrationSettingsResponse,
  IntegrationTestResponse,
  ActionResponse,
  ActionStatusResponse,
  UpdateStatusResponse,
  WorkspaceGitStatus,
  WorkspaceOpenResponse,
  StatusResponse,
  AgentHandoff,
  AgentCommsChannel,
  AgentCommsChannelResponse,
  AgentCommsMessage,
  AgentCommsMessageCreateRequest,
  AgentHandoffCreateRequest,
  AgentHandoffMessage,
  AgentHandoffMessageCreateRequest,
  AgentHandoffResultRequest,
  AgentHandoffApproveRequest,
  AgentWorkerSnapshot,
  AgentHubSnapshot,
  AgentRuntimeConfig,
  AgentRoutingConfig,
  AgentSafetyConfig,
  AgentIdentityConfig,
  AgentSoulConfig,
  AgentLifecycleConfig,
  AgentEcosystemConfig,
  AgentMemoryConfig,
  HarnessSnapshot,
  PaginatedSessions,
  EnvVarInfo,
  SessionMessagesResponse,
  SessionTodosResponse,
  SessionPlanResponse,
  SessionFilesResponse,
  SessionArtifactsResponse,
  SessionChildrenResponse,
  SessionTurnUsageResponse,
  FilesTreeResponse,
  LogsResponse,
  AnalyticsResponse,
  CronJob,
  CronJobCreateRequest,
  SkillInfo,
  SkillTreeResponse,
  SkillFileResponse,
  BlobResponse,
  ToolsetInfo,
  SessionSearchResponse,
  ModelInfoResponse,
  OAuthProvidersResponse,
  OAuthStartResponse,
  OAuthSubmitResponse,
  OAuthPollResponse,
  TelegramPairStartResponse,
  TelegramPairListResponse,
  TelegramPairApproveResponse,
  DashboardThemesResponse,
  PluginManifestResponse,
  HeartbeatSurfacesResponse,
  HeartbeatExperimentsResponse,
  SurfaceApproval,
} from "./api-types";
import { recordStartupApiTiming } from "./startup-performance";

// Ephemeral session token for protected endpoints.
// Injected into index.html by the server — never fetched via API.
declare global {
  interface Window {
    __ELEVATE_SESSION_TOKEN__?: string;
  }
}
let _sessionToken: string | null = null;
const SESSION_HEADER = "X-Elevate-Session-Token";
const DEFAULT_GET_CACHE_TTL_MS = 2_500;
const GET_CACHE = new Map<
  string,
  {
    expiresAt: number;
    promise: Promise<unknown>;
  }
>();

function setSessionHeader(headers: Headers, token: string): void {
  if (!headers.has(SESSION_HEADER)) {
    headers.set(SESSION_HEADER, token);
  }
}

function clearGetCache(): void {
  GET_CACHE.clear();
}

function extractErrorDetail(body: string): string {
  const trimmed = body.trim();
  if (!trimmed) return "";
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed && typeof parsed === "object") {
      const record = parsed as Record<string, unknown>;
      for (const key of ["detail", "error", "message", "reason"]) {
        const value = record[key];
        if (typeof value === "string" && value.trim()) {
          return value.trim();
        }
      }
      return JSON.stringify(parsed);
    }
  } catch {
    // Plain-text response bodies are already useful as-is.
  }
  return trimmed;
}

async function responseError(res: Response, url: string): Promise<Error> {
  const body = await res.text().catch(() => "");
  const detail = extractErrorDetail(body);
  const statusText = res.statusText || "Request failed";
  const suffix = detail ? `: ${detail}` : ": no response body";
  return new Error(`${res.status} ${statusText} on ${url}${suffix}`);
}

function shouldCacheGet(url: string, init?: RequestInit): boolean {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET") return false;
  if (init?.signal) return false;
  if (init?.cache === "no-store" || init?.cache === "reload") return false;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.searchParams.get("refresh") === "true") return false;
    if (parsed.searchParams.get("fresh") === "true") return false;
    if (parsed.searchParams.has("_")) return false;
  } catch {
    if (url.includes("refresh=true") || url.includes("fresh=true") || url.includes("_=")) {
      return false;
    }
  }
  return true;
}

async function fetchJSONNetwork<T>(url: string, init?: RequestInit): Promise<T> {
  // Inject the session token into all /api/ requests.
  const headers = new Headers(init?.headers);
  const token = window.__ELEVATE_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const method = (init?.method ?? "GET").toUpperCase();
  const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
  let status = 0;
  try {
    const res = await fetch(`${BASE}${url}`, { ...init, headers });
    status = res.status;
    if (!res.ok) {
      throw await responseError(res, url);
    }
    if (method !== "GET") {
      clearGetCache();
    }
    const json = await res.json();
    const endedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    recordStartupApiTiming(url, method, status, endedAt - startedAt, true);
    return json;
  } catch (error) {
    const endedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    recordStartupApiTiming(url, method, status, endedAt - startedAt, false);
    throw error;
  }
}

export function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  if (shouldCacheGet(url, init)) {
    return cachedFetchJSON<T>(url, DEFAULT_GET_CACHE_TTL_MS, init);
  }
  return fetchJSONNetwork<T>(url, init);
}

function cachedFetchJSON<T>(url: string, ttlMs: number, init?: RequestInit): Promise<T> {
  const tokenKey = window.__ELEVATE_SESSION_TOKEN__ ? "session" : "anonymous";
  const key = `${tokenKey}:${url}`;
  const now = Date.now();
  const cached = GET_CACHE.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.promise as Promise<T>;
  }

  const promise = fetchJSONNetwork<T>(url, init).catch((error) => {
    if (GET_CACHE.get(key)?.promise === promise) {
      GET_CACHE.delete(key);
    }
    throw error;
  });
  GET_CACHE.set(key, { expiresAt: now + ttlMs, promise });
  return promise;
}

function maxSessionLimit(limit: number): number {
  const parsed = Number.isFinite(limit) ? Math.trunc(limit) : 20;
  return Math.max(1, Math.min(parsed || 20, 200));
}

async function fetchBlob(url: string, init?: RequestInit): Promise<BlobResponse> {
  const headers = new Headers(init?.headers);
  const token = window.__ELEVATE_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    throw await responseError(res, url);
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
  throw new Error("Session token not available — page must be served by the Elevation dashboard server");
}

export type AdminDeadlineDeal = {
  id: string;
  title: string;
  side: string;
  currentStage: number;
  subjectRemovalDate: string | null;
  completionDate: string | null;
  primaryContactId: string | null;
};

export const api = {
  getStatus: (options?: { refresh?: boolean }) =>
    options?.refresh
      ? fetchJSON<StatusResponse>("/api/status")
      : cachedFetchJSON<StatusResponse>("/api/status", 2_000),
  getAccessStatus: () => cachedFetchJSON<AccessStatusResponse>("/api/access", 5_000),
  getLicenseStatus: () =>
    cachedFetchJSON<LicenseStatusResponse>("/api/license/status", 5_000),
  activateLicense: (
    email: string,
    password: string,
    backendUrl?: string,
    skipSkillSync?: boolean,
  ) =>
    fetchJSON<LicenseActivateResponse>("/api/license/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        backend_url: backendUrl || undefined,
        skip_skill_sync: skipSkillSync || undefined,
      }),
    }),
  createAccount: (
    email: string,
    password: string,
    firstName: string,
    lastName: string,
    backendUrl?: string,
    skipSkillSync?: boolean,
  ) =>
    fetchJSON<LicenseActivateResponse>("/api/license/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
        backend_url: backendUrl || undefined,
        skip_skill_sync: skipSkillSync || undefined,
      }),
    }),
  requestLoginCode: (email: string) =>
    fetchJSON<{ ok: boolean }>("/api/license/request-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),
  activateWithCode: (email: string, code: string, skipSkillSync?: boolean) =>
    fetchJSON<LicenseActivateResponse>("/api/license/activate-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        code,
        skip_skill_sync: skipSkillSync || undefined,
      }),
    }),
  syncLicenseSkills: () =>
    fetchJSON<LicenseSyncSkillsResponse>("/api/license/sync-skills", {
      method: "POST",
    }),
  logoutLicense: () =>
    fetchJSON<LicenseLogoutResponse>("/api/license/logout", {
      method: "POST",
    }),
  getSessions: (
    limit = 20,
    offset = 0,
    options?: { includeTotal?: boolean; includeDetails?: boolean; refresh?: boolean },
  ) => {
    const requestedLimit = maxSessionLimit(limit);
    const shouldUseSharedShellList =
      offset === 0 && options?.includeTotal === false && !options?.includeDetails && requestedLimit <= 48;
    const fetchLimit = shouldUseSharedShellList ? 48 : requestedLimit;
    const qs = new URLSearchParams({
      limit: String(fetchLimit),
      offset: String(offset),
    });
    if (options?.includeTotal === false) qs.set("include_total", "false");
    if (options?.includeDetails) qs.set("include_details", "true");
    const url = `/api/sessions?${qs.toString()}`;
    const request = options?.refresh
      ? fetchJSON<PaginatedSessions>(url)
      : cachedFetchJSON<PaginatedSessions>(url, 2_500);
    return request.then((resp) => {
      if (!shouldUseSharedShellList) return resp;
      const sessions = resp.sessions.slice(0, requestedLimit);
      return {
        ...resp,
        sessions,
        limit: requestedLimit,
        total: offset + sessions.length,
      };
    });
  },
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
  getSessionTodos: (id: string) =>
    fetchJSON<SessionTodosResponse>(`/api/sessions/${encodeURIComponent(id)}/todos`),
  getSessionPlan: (id: string) =>
    fetchJSON<SessionPlanResponse>(`/api/sessions/${encodeURIComponent(id)}/plan`),
  getSessionFiles: (id: string) =>
    fetchJSON<SessionFilesResponse>(`/api/sessions/${encodeURIComponent(id)}/files`),
  getSessionArtifacts: (id: string) =>
    fetchJSON<SessionArtifactsResponse>(`/api/sessions/${encodeURIComponent(id)}/artifacts`),
  getSessionChildren: (id: string) =>
    fetchJSON<SessionChildrenResponse>(`/api/sessions/${encodeURIComponent(id)}/children`),
  getSessionTurnUsage: (id: string) =>
    fetchJSON<SessionTurnUsageResponse>(
      `/api/sessions/${encodeURIComponent(id)}/turn_usage`,
    ),
  getFilesTree: (root?: string, depth?: number) => {
    const qs = new URLSearchParams();
    if (root) qs.set("root", root);
    if (depth) qs.set("depth", String(depth));
    const suffix = qs.toString();
    return fetchJSON<FilesTreeResponse>(`/api/files/tree${suffix ? `?${suffix}` : ""}`);
  },
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
  uploadChatAttachment: async (
    sessionId: string,
    file: File,
  ): Promise<{ path: string; name: string; size: number; media_type: string }> => {
    const headers = new Headers();
    const token = window.__ELEVATE_SESSION_TOKEN__;
    if (token) setSessionHeader(headers, token);
    const form = new FormData();
    form.append("file", file, file.name);
    const res = await fetch(
      `${BASE}/api/uploads/${encodeURIComponent(sessionId)}`,
      { method: "POST", body: form, headers },
    );
    if (!res.ok) {
      throw await responseError(res, `/api/uploads/${encodeURIComponent(sessionId)}`);
    }
    return res.json();
  },
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
  getProviderModels: (provider: string) =>
    fetchJSON<{ provider: string; models: string[] }>(
      `/api/models/by-provider?provider=${encodeURIComponent(provider)}`,
    ),
  testSlackWebhook: (params: { webhook_url: string; channel?: string; text?: string }) =>
    fetchJSON<{ ok: boolean; status: number; detail: string }>(
      "/api/channels/slack/test",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      },
    ),
  configureDiscord: (params: {
    bot_token?: string;
    allowed_users?: string;
    home_channel?: string;
  }) =>
    fetchJSON<{
      ok: boolean;
      tokenPreview: string;
      allowedUsers: string;
      homeChannel: string;
    }>("/api/channels/discord/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  getTelegramStatus: () =>
    fetchJSON<{
      configured: boolean;
      tokenPreview: string;
      allowedUsers: string;
      homeChannel: string;
      dmBehavior: string;
      allowAllUsers: boolean;
      botId?: number;
      botUsername?: string;
      botName?: string;
      canJoinGroups?: boolean;
      canReadAllGroupMessages?: boolean;
      error?: string;
    }>("/api/channels/telegram/status"),
  configureTelegram: (params: {
    bot_token?: string;
    allowed_users?: string | null;
    home_channel?: string | null;
    dm_behavior?: "pair" | "ignore" | "open" | "";
    allow_all_users?: boolean;
  }) =>
    fetchJSON<{
      ok: boolean;
      tokenPreview: string;
      allowedUsers: string;
      homeChannel: string;
      dmBehavior: string;
      allowAllUsers: boolean;
    }>("/api/channels/telegram/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  configureSlackBot: (params: {
    bot_token?: string;
    app_token?: string;
    allowed_users?: string;
  }) =>
    fetchJSON<{
      ok: boolean;
      botTokenPreview: string;
      appTokenPreview: string;
      allowedUsers: string;
    }>("/api/channels/slack/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  configureBlueBubbles: (params: {
    server_url?: string;
    password?: string;
    allowed_users?: string;
    home_channel?: string;
  }) =>
    fetchJSON<{
      ok: boolean;
      serverUrl: string;
      passwordSet: boolean;
      allowedUsers: string;
      homeChannel: string;
    }>("/api/channels/imessage/bluebubbles/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  configureWhatsApp: (params: { mode?: "bot" | "self-chat"; allowed_users?: string }) =>
    fetchJSON<{
      ok: boolean;
      mode: string;
      enabled: boolean;
      allowedUsers: string;
      bridgePresent: boolean;
      bridgeInstalled: boolean;
      paired: boolean;
    }>("/api/channels/whatsapp/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  installWhatsAppBridge: () =>
    fetchJSON<{ ok: boolean; installed: boolean }>(
      "/api/channels/whatsapp/install",
      { method: "POST" },
    ),
  getWhatsAppStatus: () =>
    fetchJSON<{
      bridgePresent: boolean;
      bridgeInstalled: boolean;
      mode: string;
      enabled: boolean;
      paired: boolean;
      allowedUsers: string;
    }>("/api/channels/whatsapp/status"),
  getAgentPeers: () =>
    fetchJSON<{
      peers: Array<{
        org: string;
        name: string;
        enabled: boolean;
        workingDirectory: string;
        timezone: string;
        communicationStyle: string;
        cronCount: number;
        roleHint: string;
        configPath: string;
        telegram?: {
          configured: boolean;
          botHandle: string;
          chatId: string;
          tokenPreview: string;
          source: string;
        };
      }>;
      rootsSearched: string[];
    }>("/api/agents/peers"),
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
  getCronJobs: (options?: { compact?: boolean; refresh?: boolean }) => {
    const url = `/api/cron/jobs${options?.compact ? "?compact=true" : ""}`;
    return options?.refresh
      ? fetchJSON<CronJob[]>(url)
      : cachedFetchJSON<CronJob[]>(url, 2_000);
  },
  createCronJob: (job: CronJobCreateRequest) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  ensureLaneCronJobs: (
    lanes: { name: string; schedule: string; prompt: string; deliver?: string }[],
  ) =>
    fetchJSON<{ created: CronJob[]; updated?: CronJob[]; skipped: string[] }>("/api/cron/jobs/ensure-lanes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lanes }),
    }),
  updateCronJob: (id: string, updates: Record<string, unknown>) =>
    fetchJSON<CronJob>(`/api/cron/jobs/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates }),
    }),
  pauseCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
  resumeCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
  triggerCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
  deleteCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),
  getCronAttention: () =>
    fetchJSON<import("./api-types").CronAttention>(`/api/cron/attention`),

  // Surface heartbeats — per-account work+experiment loop per surface (Admin, Leads).
  getHeartbeatSurfaces: (options?: { refresh?: boolean }) => {
    const url = "/api/heartbeats/surfaces";
    return options?.refresh
      ? fetchJSON<HeartbeatSurfacesResponse>(url)
      : cachedFetchJSON<HeartbeatSurfacesResponse>(url, 5_000);
  },
  // Opt-in toggle: surface heartbeats ship OFF and the realtor turns them on here.
  setHeartbeatSurfaceEnabled: (surface: string, enabled: boolean) =>
    fetchJSON<{ surface: string; enabled: boolean }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/enabled`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      },
    ),
  // Per-automation toggle: each surface's automation cron jobs ship OFF and the
  // realtor turns one on here (reuses the same pause/resume cron path as above).
  setHeartbeatAutomationEnabled: (jobId: string, enabled: boolean) =>
    fetchJSON<{ id: string; enabled: boolean }>(
      `/api/heartbeats/automations/${encodeURIComponent(jobId)}/enabled`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      },
    ),

  // Experiments — autoresearch view: per-surface research cycles + experiments.
  getHeartbeatExperiments: (options?: { refresh?: boolean }) => {
    const url = "/api/heartbeats/experiments";
    return options?.refresh
      ? fetchJSON<HeartbeatExperimentsResponse>(url)
      : cachedFetchJSON<HeartbeatExperimentsResponse>(url, 5_000);
  },
  // Create a NEW custom surface from the template (cortextOS add-agent). Seeds it
  // opt-in/off; the realtor turns it on from the Heartbeat page.
  createHeartbeatSurface: (body: {
    surface: string;
    title?: string;
    name?: string;
    goal?: string;
    schedule?: string;
    experiment?: Record<string, unknown>;
    config?: Record<string, unknown>;
  }) =>
    fetchJSON<{ ok: boolean; surface: string }>("/api/heartbeats/surfaces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteHeartbeatSurface: (surface: string, options?: { force?: boolean }) => {
    const qs = new URLSearchParams();
    if (options?.force) qs.set("force", "true");
    const tail = qs.toString();
    return fetchJSON<{
      ok: boolean;
      surface: string;
      removed: { registry: boolean; files: boolean; jobs: string[] };
    }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}${tail ? `?${tail}` : ""}`,
      { method: "DELETE" },
    );
  },
  // Create a new experiment cycle on a surface (the analyst's lever — a new
  // self-improvement track). Mirrors cortextOS manage-cycle create.
  createHeartbeatCycle: (
    surface: string,
    body: {
      name: string;
      metric: string;
      metric_type: string;
      direction: string;
      window: string;
      every_n_runs?: number;
      measurement?: string;
    },
  ) =>
    fetchJSON<{ ok: boolean; cycles: unknown[] }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/cycles`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  // Pause/resume or delete a cycle (analyst controls; surfaces only run them).
  updateHeartbeatCycle: (
    surface: string,
    name: string,
    body: Record<string, unknown>,
  ) =>
    fetchJSON<{ ok: boolean; cycles: unknown[] }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/cycles/${encodeURIComponent(name)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  deleteHeartbeatCycle: (surface: string, name: string) =>
    fetchJSON<{ ok: boolean; cycles: unknown[] }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/cycles/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  // Per-surface settings (model picker, day/night, comms style, approval rules).
  getHeartbeatSurfaceConfig: (surface: string) =>
    fetchJSON<{ surface: string; config: Record<string, unknown>; mode: string }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/config`,
    ),
  patchHeartbeatSurfaceConfig: (surface: string, body: Record<string, unknown>) =>
    fetchJSON<{ surface: string; config: Record<string, unknown>; mode: string }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/config`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  // Per-surface delivery routing — where this agent's heartbeat output goes
  // (in-app or a connected channel/bot). Faithful to CTRL Flow per-agent routing.
  getHeartbeatSurfaceRoute: (surface: string) =>
    fetchJSON<{
      surface: string;
      deliver: string;
      routes: { value: string; label: string; platform: string }[];
    }>(`/api/heartbeats/surfaces/${encodeURIComponent(surface)}/route`),
  setHeartbeatSurfaceRoute: (surface: string, deliver: string) =>
    fetchJSON<{ surface: string; deliver: string }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/route`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deliver }),
      },
    ),
  // Available models for the per-surface model picker ({models:[{id,...}], default}).
  getAvailableModels: () =>
    cachedFetchJSON<{ models: { id: string; label?: string }[]; default?: string }>(
      "/api/models/available",
      60_000,
    ),
  // Per-surface goals (north-star focus + bottleneck + rich goal list w/ progress).
  getHeartbeatSurfaceGoals: (surface: string) =>
    fetchJSON<{
      surface: string;
      bottleneck: string;
      daily_focus: string;
      goals: { id: string; title: string; progress: number; order: number }[];
      updated_at?: string | null;
    }>(`/api/heartbeats/surfaces/${encodeURIComponent(surface)}/goals`),
  patchHeartbeatSurfaceGoals: (
    surface: string,
    body: {
      bottleneck?: string;
      daily_focus?: string;
      goals?: { id?: string; title: string; progress?: number; order?: number }[];
    },
  ) =>
    fetchJSON<{
      surface: string;
      bottleneck: string;
      daily_focus: string;
      goals: { id: string; title: string; progress: number; order: number }[];
      updated_at?: string | null;
    }>(
      `/api/heartbeats/surfaces/${encodeURIComponent(surface)}/goals`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  // Per-agent heartbeat — the 10-step beat doc (HEARTBEAT.md) each agent reads
  // when its heartbeat cron fires, plus that cron's enabled state.
  getAgentHeartbeatMd: (agentId: string) =>
    fetchJSON<{
      agent: string;
      path: string;
      content: string;
      job_id?: string | null;
      enabled: boolean;
    }>(`/api/agents/${encodeURIComponent(agentId)}/heartbeat-md`),
  putAgentHeartbeatMd: (agentId: string, content: string) =>
    fetchJSON<{ ok: boolean; agent: string; path: string }>(
      `/api/agents/${encodeURIComponent(agentId)}/heartbeat-md`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),

  // Surface Tasks — dispatch work to a surface (or 'human'); kanban board.
  listSurfaceTasks: (params?: { status?: string; assignee?: string; priority?: string; project?: string; include_archived?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.assignee) qs.set("assignee", params.assignee);
    if (params?.priority) qs.set("priority", params.priority);
    if (params?.project) qs.set("project", params.project);
    if (params?.include_archived) qs.set("include_archived", "true");
    const q = qs.toString();
    return fetchJSON<{ tasks: import("./api-types").SurfaceTask[] }>(
      `/api/surface-tasks${q ? `?${q}` : ""}`,
    );
  },
  createSurfaceTask: (body: {
    title: string;
    description?: string;
    type?: string;
    status?: string;
    assignee?: string;
    assigned_to?: string;
    priority?: string;
    project?: string;
    needs_approval?: boolean;
    created_by?: string;
    createdBy?: string;
    org?: string;
    kpi_key?: string;
    kpiKey?: string;
    due_date?: string;
    dueDate?: string;
    blocked_by?: string[];
    blockedBy?: string[];
    blocks?: string[];
    actor?: string;
    agentId?: string;
    agent_id?: string;
    policyCategory?: string;
    policy_category?: string;
  }) =>
    fetchJSON<{ ok: boolean; task: import("./api-types").SurfaceTask }>("/api/surface-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateSurfaceTask: (id: string, body: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean; task: import("./api-types").SurfaceTask }>(
      `/api/surface-tasks/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  claimSurfaceTask: (id: string, body: { agent: string; actor?: string; agentId?: string; agent_id?: string }) =>
    fetchJSON<{ ok: boolean; task: import("./api-types").SurfaceTask }>(
      `/api/surface-tasks/${encodeURIComponent(id)}/claim`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  getSurfaceTaskAudit: (id: string, limit = 200) =>
    fetchJSON<{ events: import("./api-types").SurfaceTaskAuditEvent[] }>(
      `/api/surface-tasks/${encodeURIComponent(id)}/audit?limit=${encodeURIComponent(String(limit))}`,
    ),
  checkSurfaceTaskStale: () =>
    fetchJSON<import("./api-types").SurfaceTaskStaleReport>("/api/surface-tasks/stale"),
  archiveSurfaceTasks: (body?: { dry_run?: boolean; dryRun?: boolean; older_than_days?: number; olderThanDays?: number }) =>
    fetchJSON<{ archived: number; items: Array<Record<string, unknown>>; skipped: Array<Record<string, unknown>>; dry_run: boolean }>(
      "/api/surface-tasks/archive",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      },
    ),
  compactSurfaceTasks: (body?: { dry_run?: boolean; dryRun?: boolean; older_than_days?: number; olderThanDays?: number }) =>
    fetchJSON<{ archived: Array<Record<string, unknown>>; skipped: Array<Record<string, unknown>>; dry_run: boolean }>(
      "/api/surface-tasks/compact",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      },
    ),
  deleteSurfaceTask: (id: string, params?: { actor?: string; agentId?: string; agent_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.actor) qs.set("actor", params.actor);
    if (params?.agentId) qs.set("agentId", params.agentId);
    if (params?.agent_id) qs.set("agent_id", params.agent_id);
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJSON<{ ok: boolean; approvalRequired?: boolean; approval?: SurfaceApproval; task?: import("./api-types").SurfaceTask }>(`/api/surface-tasks/${encodeURIComponent(id)}${tail}`, {
      method: "DELETE",
    });
  },

  // Surface Approvals — decisions kanban (dashboard-only resolve).
  listSurfaceApprovals: (params?: { status?: string; surface?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.surface) qs.set("surface", params.surface);
    if (params?.category) qs.set("category", params.category);
    const q = qs.toString();
    return fetchJSON<{ approvals: import("./api-types").SurfaceApproval[] }>(
      `/api/surface-approvals${q ? `?${q}` : ""}`,
    );
  },
  resolveSurfaceApproval: (id: string, decision: "approve" | "reject", note?: string) =>
    fetchJSON<{ ok: boolean; approval: import("./api-types").SurfaceApproval }>(
      `/api/surface-approvals/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note }),
      },
    ),

  // Outreach templates
  getOutreachTemplates: (lane?: string) => {
    const qs = lane ? `?lane=${encodeURIComponent(lane)}` : "";
    return fetchJSON<{ templates: OutreachTemplate[] }>(`/api/outreach/templates${qs}`);
  },
  createOutreachTemplate: (body: { lane: string; name: string; body: string; channel?: string }) =>
    fetchJSON<{ template: OutreachTemplate }>("/api/outreach/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateOutreachTemplate: (
    id: string,
    body: { name?: string; body?: string; channel?: string; active?: boolean },
  ) =>
    fetchJSON<{ template: OutreachTemplate }>(`/api/outreach/templates/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteOutreachTemplate: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/outreach/templates/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getOutreachOverview: () => fetchJSON<OutreachOverview>("/api/outreach/templates/overview"),
  suggestOutreachTemplate: (body: { lane: string; channel?: string; extraBrief?: string }) =>
    fetchJSON<{ template: OutreachTemplate }>("/api/outreach/templates/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  approveOutreachTemplate: (id: string) =>
    fetchJSON<{ template: OutreachTemplate }>(
      `/api/outreach/templates/${encodeURIComponent(id)}/approve`,
      { method: "POST" },
    ),
  rejectOutreachTemplate: (id: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/outreach/templates/${encodeURIComponent(id)}/reject`,
      { method: "POST" },
    ),

  // Composio
  getComposioStatus: () => fetchJSON<ComposioStatus>("/api/composio/status"),
  setComposioKey: (apiKey: string) =>
    fetchJSON<ComposioStatus>("/api/composio/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKey }),
    }),
  clearComposioKey: () =>
    fetchJSON<ComposioStatus>("/api/composio/key", { method: "DELETE" }),
  // Pass ``fresh`` to bypass the server SWR cache — used right after a
  // connect/delete and on window focus so a just-linked account shows up.
  getComposioConnections: (fresh = false) =>
    fetchJSON<ComposioApiResult<ComposioConnectedAccount[]>>(
      `/api/composio/connections${fresh ? "?fresh=1" : ""}`,
    ),
  getComposioToolkits: (category?: string) => {
    const qs = category ? `?category=${encodeURIComponent(category)}` : "";
    return fetchJSON<ComposioApiResult<ComposioToolkit[]>>(`/api/composio/toolkits${qs}`);
  },
  // Paginated/searched version. ``all=false`` plus ``cursor`` lets the
  // wizard load page-by-page without waiting on the full catalog walk.
  // Pass ``search`` to use Composio's fuzzy search server-side.
  getComposioToolkitsPage: (params: {
    category?: string;
    cursor?: string;
    search?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    qs.set("all", "false");
    qs.set("limit", String(params.limit ?? 30));
    if (params.category) qs.set("category", params.category);
    if (params.cursor) qs.set("cursor", params.cursor);
    if (params.search) qs.set("search", params.search);
    return fetchJSON<ComposioApiResult<ComposioToolkit[]>>(
      `/api/composio/toolkits?${qs.toString()}`,
    );
  },
  initiateComposioConnection: (body: {
    toolkitSlug: string;
    redirectUrl?: string;
    userId?: string;
  }) =>
    fetchJSON<ComposioApiResult<ComposioConnectInitResponse>>(
      "/api/composio/connect",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  getComposioToolkitDetails: (slug: string) =>
    fetchJSON<ComposioApiResult<ComposioToolkitDetails>>(
      `/api/composio/toolkits/${encodeURIComponent(slug)}`,
    ),
  createComposioCustomAuth: (body: {
    toolkitSlug: string;
    credentials: Record<string, string>;
    authScheme?: string;
    redirectUrl?: string;
    userId?: string;
  }) =>
    fetchJSON<ComposioApiResult<ComposioConnectInitResponse>>(
      "/api/composio/auth-configs/custom",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  deleteComposioConnection: (accountId: string) =>
    fetchJSON<ComposioApiResult<unknown>>(
      `/api/composio/connections/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
    ),
  getComposioFacebookPages: () =>
    fetchJSON<{
      ok: boolean;
      pages: Array<{
        id: string;
        name: string;
        selected: boolean;
        tasks?: string[];
        connected_account_id?: string;
      }>;
      selected_page_ids: string[];
      error?: string;
    }>("/api/composio/facebook/pages"),
  setComposioFacebookPages: (pageIds: string[]) =>
    fetchJSON<{ ok: boolean; selected_page_ids: string[] }>(
      "/api/composio/facebook/pages",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pageIds }),
      },
    ),

  // Ayrshare (publishing layer for /social-media)
  getAyrshareStatus: () => fetchJSON<AyrshareStatus>("/api/ayrshare/status"),
  setAyrshareKey: (apiKey: string) =>
    fetchJSON<AyrshareStatus>("/api/ayrshare/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKey }),
    }),
  clearAyrshareKey: () =>
    fetchJSON<AyrshareStatus>("/api/ayrshare/key", { method: "DELETE" }),
  getAyrshareProfiles: () =>
    fetchJSON<{ ok: boolean; data?: unknown; error?: string }>(
      "/api/ayrshare/profiles",
    ),
  getAyrshareScheduled: () =>
    fetchJSON<{ ok: boolean; data?: unknown; error?: string }>(
      "/api/ayrshare/scheduled",
    ),
  getAyrshareHistory: (params?: { lastRecords?: number; lastDays?: number }) => {
    const qs = new URLSearchParams();
    if (params?.lastRecords) qs.set("last_records", String(params.lastRecords));
    if (params?.lastDays) qs.set("last_days", String(params.lastDays));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJSON<{ ok: boolean; data?: unknown; error?: string }>(
      `/api/ayrshare/history${tail}`,
    );
  },

  // Social content engine (backs the /social-media page)
  getSocialSnapshot: (signal?: AbortSignal) =>
    fetchJSON<SocialSnapshot>("/api/social/snapshot", { signal }),
  getSocialIdeas: (status?: string, signal?: AbortSignal) => {
    const tail = status ? `?status=${encodeURIComponent(status)}` : "";
    return fetchJSON<{ items: SocialIdea[]; count: number }>(
      `/api/social/ideas${tail}`,
      { signal },
    );
  },
  socialIdeaAction: (
    recordId: string,
    body: { action: "approve" | "reject" | "edit"; notes?: string; edit?: Partial<SocialIdea> },
  ) =>
    fetchJSON<{ ok: boolean; record_id: string; action: string }>(
      `/api/social/ideas/${encodeURIComponent(recordId)}/action`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  getSocialRecentPosts: (limit = 30, signal?: AbortSignal) =>
    fetchJSON<{ items: SocialMetricRow[]; count: number }>(
      `/api/social/recent-posts?limit=${limit}`,
      { signal },
    ),
  refreshSocialMetrics: (
    opts: { platform?: "instagram" | "facebook" | "youtube"; lookbackDays?: number; maxPosts?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (opts.platform) qs.set("platform", opts.platform);
    if (opts.lookbackDays) qs.set("lookback_days", String(opts.lookbackDays));
    if (opts.maxPosts) qs.set("max_posts", String(opts.maxPosts));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJSON<{
      ok: boolean;
      results: Record<string, { platform: string; status: string; posts_seen?: number; errors?: string[] }>;
    }>(`/api/social/refresh${tail}`, { method: "POST" });
  },

  // Skills & Toolsets
  getSkills: () => cachedFetchJSON<SkillInfo[]>("/api/skills", 3_000),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  getSkillTree: (name: string) =>
    fetchJSON<SkillTreeResponse>(`/api/skills/${encodeURIComponent(name)}/tree`),
  getSkillFile: (name: string, path?: string) => {
    const qs = path ? `?path=${encodeURIComponent(path)}` : "";
    return fetchJSON<SkillFileResponse>(`/api/skills/${encodeURIComponent(name)}/file${qs}`);
  },
  getToolsets: () => cachedFetchJSON<ToolsetInfo[]>("/api/tools/toolsets", 5_000),

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

  // Telegram pairing ritual (wizard step 3)
  startTelegramPairing: async (botToken: string) => {
    const token = await getSessionToken();
    return fetchJSON<TelegramPairStartResponse>("/api/telegram/pair/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ bot_token: botToken }),
    });
  },
  listTelegramPairings: () =>
    fetchJSON<TelegramPairListResponse>("/api/telegram/pair/pending"),
  approveTelegramPairing: async (code: string, setHome = false) => {
    const token = await getSessionToken();
    return fetchJSON<TelegramPairApproveResponse>("/api/telegram/pair/approve", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ code, set_home: setHome }),
    });
  },

  // Gateway / update actions
  startGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/start", { method: "POST" }),
  restartGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/restart", { method: "POST" }),
  updateElevate: () =>
    fetchJSON<ActionResponse>("/api/elevate/update", { method: "POST" }),
  getUpdateStatus: (refresh = false) => {
    if (refresh) {
      clearGetCache();
      return fetchJSON<UpdateStatusResponse>("/api/elevate/update/status?refresh=true")
        .finally(clearGetCache);
    }
    return cachedFetchJSON<UpdateStatusResponse>("/api/elevate/update/status", 30_000);
  },
  getWorkspaceGitStatus: (params?: { force?: boolean; sessionId?: string | null; workingDirectory?: string | null }) => {
    const qs = new URLSearchParams();
    if (params?.sessionId) qs.set("session_id", params.sessionId);
    if (params?.workingDirectory) qs.set("working_directory", params.workingDirectory);
    const suffix = qs.toString();
    const url = `/api/workspace/git/status${suffix ? `?${suffix}` : ""}`;
    return params?.force
      ? fetchJSON<WorkspaceGitStatus>(url)
      : cachedFetchJSON<WorkspaceGitStatus>(url, 5_000);
  },
  openWorkspace: (path?: string | null) =>
    fetchJSON<WorkspaceOpenResponse>("/api/workspace/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(path ? { path } : {}),
    }),
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

  // Activity — fleet feed of what every agent did (heartbeat runs + cron runs).
  getActivity: (params?: { agent?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.agent) qs.set("agent", params.agent);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return fetchJSON<{
      items: {
        kind: string;
        agent: string;
        ts: string;
        title: string;
        detail?: string | null;
        status?: string;
      }[];
    }>(`/api/activity${q ? `?${q}` : ""}`);
  },
  // Comms — CortextOS-style meeting room and pair channels, projected from the
  // native handoff bus.
  getCommsFeed: (params: { limit?: number; search?: string; agent?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.search) qs.set("search", params.search);
    if (params.agent) qs.set("agent", params.agent);
    const tail = qs.toString();
    return fetchJSON<AgentCommsMessage[]>(`/api/comms/feed${tail ? `?${tail}` : ""}`);
  },
  getCommsChannels: (params: { includeArchived?: boolean; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.includeArchived) qs.set("include_archived", "true");
    if (params.limit != null) qs.set("limit", String(params.limit));
    const tail = qs.toString();
    return fetchJSON<AgentCommsChannel[]>(`/api/comms/channels${tail ? `?${tail}` : ""}`);
  },
  getCommsChannel: (pair: string, params: { limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit != null) qs.set("limit", String(params.limit));
    const tail = qs.toString();
    return fetchJSON<AgentCommsChannelResponse>(
      `/api/comms/channel/${encodeURIComponent(pair)}${tail ? `?${tail}` : ""}`,
    );
  },
  sendCommsMessage: (body: AgentCommsMessageCreateRequest) =>
    fetchJSON<{ handoff: AgentHandoff; message: AgentCommsMessage }>("/api/comms/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getCommsDeliveryChannels: () =>
    cachedFetchJSON<{
      channels: { platform: string; id: string; name: string; type?: string }[];
      updated_at?: string | null;
    }>("/api/comms/delivery-channels", 30_000),

  // Agent Hub
  getAgentHub: (
    options?: {
      lite?: boolean;
      includeMemoryGraph?: boolean;
      includeSessionTotal?: boolean;
      includeOrchestration?: boolean;
      includeSkills?: boolean;
      includeToolsets?: boolean;
      includeHarness?: boolean;
    },
  ) => {
    const qs = new URLSearchParams();
    if (options?.lite) qs.set("lite", "true");
    if (typeof options?.includeMemoryGraph === "boolean") {
      qs.set("include_memory_graph", String(options.includeMemoryGraph));
    }
    if (typeof options?.includeSessionTotal === "boolean") {
      qs.set("include_session_total", String(options.includeSessionTotal));
    }
    if (typeof options?.includeOrchestration === "boolean") {
      qs.set("include_orchestration", String(options.includeOrchestration));
    }
    if (typeof options?.includeSkills === "boolean") {
      qs.set("include_skills", String(options.includeSkills));
    }
    if (typeof options?.includeToolsets === "boolean") {
      qs.set("include_toolsets", String(options.includeToolsets));
    }
    if (typeof options?.includeHarness === "boolean") {
      qs.set("include_harness", String(options.includeHarness));
    }
    const suffix = qs.toString();
    return cachedFetchJSON<AgentHubSnapshot>(
      `/api/agent-hub${suffix ? `?${suffix}` : ""}`,
      1_500,
    );
  },
  createAgent: (body: {
    [key: string]: unknown;
    id?: string;
    name: string;
    role?: string;
    description?: string;
    prompt?: string;
    enabled?: boolean;
    skills?: string[];
    toolsets?: string[];
    platforms?: string[];
    session_sources?: string[];
    runtime?: AgentRuntimeConfig;
    routing?: AgentRoutingConfig;
    safety?: AgentSafetyConfig;
    identity?: AgentIdentityConfig;
    soul?: AgentSoulConfig;
    lifecycle?: AgentLifecycleConfig;
    ecosystem?: AgentEcosystemConfig;
    memory?: AgentMemoryConfig;
    memorySeed?: { content: string; source?: string; scopes?: string[] };
    metadata?: Record<string, unknown>;
  }) =>
    fetchJSON<Record<string, unknown>>("/api/agent-hub/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getCortextAgentPacks: () =>
    fetchJSON<{
      root: string | null;
      packs: Array<{
        id: string;
        name: string;
        role: string;
        description: string;
        sourcePath: string;
        sourceExists: boolean;
        includes: string[];
        automationCount: number;
        payload: {
          [key: string]: unknown;
          id?: string;
          name: string;
          role?: string;
          description?: string;
          prompt?: string;
          enabled?: boolean;
          skills?: string[];
          toolsets?: string[];
          platforms?: string[];
          session_sources?: string[];
          runtime?: AgentRuntimeConfig;
          routing?: AgentRoutingConfig;
          safety?: AgentSafetyConfig;
          identity?: AgentIdentityConfig;
          soul?: AgentSoulConfig;
          lifecycle?: AgentLifecycleConfig;
          ecosystem?: AgentEcosystemConfig;
          memory?: AgentMemoryConfig;
          memorySeed?: { content: string; source?: string; scopes?: string[] };
          metadata?: Record<string, unknown>;
        };
      }>;
    }>("/api/agent-hub/cortext-packs"),
  updateAgent: (
    agentId: string,
    patch: {
      [key: string]: unknown;
      name?: string;
      enabled?: boolean;
      role?: string;
      description?: string;
      prompt?: string;
      skills?: string[];
      toolsets?: string[];
      platforms?: string[];
      session_sources?: string[];
      runtime?: AgentRuntimeConfig;
      routing?: AgentRoutingConfig;
      safety?: AgentSafetyConfig;
      identity?: AgentIdentityConfig;
      soul?: AgentSoulConfig;
      lifecycle?: AgentLifecycleConfig;
      ecosystem?: AgentEcosystemConfig;
      memory?: AgentMemoryConfig;
      metadata?: Record<string, unknown>;
    },
  ) =>
    fetchJSON<Record<string, unknown>>(`/api/agent-hub/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  deleteAgent: (agentId: string) =>
    fetchJSON<{ ok: boolean; id: string }>(`/api/agent-hub/agents/${encodeURIComponent(agentId)}`, {
      method: "DELETE",
    }),
  cleanupAgentInstallArtifacts: (
    agentId: string,
    options?: { deleteAgent?: boolean; force?: boolean },
  ) => {
    const qs = new URLSearchParams();
    if (options?.deleteAgent === false) qs.set("delete_agent", "false");
    if (options?.force) qs.set("force", "true");
    const tail = qs.toString();
    return fetchJSON<{
      ok: boolean;
      id: string;
      removed: {
        agent: boolean;
        heartbeatSurface:
          | { ok: boolean; surface: string; missing?: boolean; removed?: Record<string, unknown> }
          | null;
        onboardingTasks: string[];
        memory: { agent: string; removed: number; source?: string | null } | null;
      };
    }>(
      `/api/agent-hub/agents/${encodeURIComponent(agentId)}/install-artifacts${tail ? `?${tail}` : ""}`,
      { method: "DELETE" },
    );
  },
  getAgentHandoffs: (
    params: {
      toAgentId?: string;
      fromAgentId?: string;
      status?: string;
      dealId?: string;
      profileId?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.toAgentId) qs.set("to_agent_id", params.toAgentId);
    if (params.fromAgentId) qs.set("from_agent_id", params.fromAgentId);
    if (params.status) qs.set("status", params.status);
    if (params.dealId) qs.set("deal_id", params.dealId);
    if (params.profileId) qs.set("profile_id", params.profileId);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJSON<{ items: AgentHandoff[]; count: number }>(`/api/agent-handoffs${tail}`);
  },
  createAgentHandoff: (body: AgentHandoffCreateRequest) =>
    fetchJSON<AgentHandoff>("/api/agent-handoffs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAgentHandoff: (handoffId: string) =>
    fetchJSON<AgentHandoff>(`/api/agent-handoffs/${encodeURIComponent(handoffId)}`),
  createAgentHandoffMessage: (handoffId: string, body: AgentHandoffMessageCreateRequest) =>
    fetchJSON<AgentHandoffMessage>(
      `/api/agent-handoffs/${encodeURIComponent(handoffId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  drainAgentHandoffs: (body: { toAgentId?: string; limit?: number } = {}) =>
    fetchJSON<{ items: AgentHandoff[]; count: number }>("/api/agent-handoffs/drain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  runAgentWorkerTick: (body: { agentId?: string } = {}) =>
    fetchJSON<AgentWorkerSnapshot>("/api/agent-worker/tick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  wakeAgentWorker: (body: { agentId?: string } = {}) =>
    fetchJSON<AgentWorkerSnapshot>("/api/agent-worker/wake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  completeAgentHandoff: (handoffId: string, body: AgentHandoffResultRequest) =>
    fetchJSON<AgentHandoff>(`/api/agent-handoffs/${encodeURIComponent(handoffId)}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  approveAgentHandoff: (handoffId: string, body: AgentHandoffApproveRequest) =>
    fetchJSON<AgentHandoff>(`/api/agent-handoffs/${encodeURIComponent(handoffId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getHarness: () => fetchJSON<HarnessSnapshot>("/api/harness"),

  // Admin Hub deals
  getAdminSetup: () => fetchJSON<AdminSetupSnapshot>("/api/admin/setup"),
  updateAdminSetup: (body: AdminSetupUpdateRequest) =>
    fetchJSON<AdminSetupSnapshot>("/api/admin/setup", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  verifyAdminSetup: () =>
    fetchJSON<AdminSetupSnapshot>("/api/admin/setup/verify", {
      method: "POST",
    }),
  completeAdminSetup: () =>
    fetchJSON<AdminSetupSnapshot>("/api/admin/setup/complete", {
      method: "POST",
    }),
  postAdminOnboardingChat: (messages: Array<{ role: string; content: string }>) =>
    fetchJSON<{ ok: boolean; reply: string; model?: string | null; warning?: string }>(
      "/api/admin/onboarding/chat",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      },
    ),

  // Leads onboarding gate
  getLeadsSetup: (options?: { refresh?: boolean }) =>
    options?.refresh
      ? fetchJSON<LeadsSetupSnapshot>("/api/leads/setup")
      : cachedFetchJSON<LeadsSetupSnapshot>("/api/leads/setup", 30_000),
  updateLeadsSetup: (items: LeadsSetupItemUpdate[]) =>
    fetchJSON<LeadsSetupSnapshot>("/api/leads/setup", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  completeLeadsSetup: () =>
    fetchJSON<LeadsSetupSnapshot>("/api/leads/setup/complete", { method: "POST" }),
  resetLeadsSetup: () =>
    fetchJSON<LeadsSetupSnapshot>("/api/leads/setup/reset", { method: "POST" }),

  // Agent (top-level) onboarding gate
  getAgentSetup: () => fetchJSON<AgentSetupSnapshot>("/api/agent/setup"),
  updateAgentSetup: (items: AgentSetupItemUpdate[]) =>
    fetchJSON<AgentSetupSnapshot>("/api/agent/setup", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  completeAgentSetup: () =>
    fetchJSON<AgentSetupSnapshot>("/api/agent/setup/complete", { method: "POST" }),
  resetAgentSetup: () =>
    fetchJSON<AgentSetupSnapshot>("/api/agent/setup/reset", { method: "POST" }),
  launchAdminOnboardingBrowserUse: (portalKey: "mls" | "compliance" | "showing", taskHint?: string) =>
    fetchJSON<{
      ok: boolean;
      taskId?: string;
      runUrl?: string | null;
      error?: string;
      portal?: { loginUrl?: string; provider?: string; credentialRef?: string };
    }>("/api/admin/onboarding/browser-use/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ portalKey, taskHint }),
    }),
  getPackOnboarding: () => fetchJSON<PackOnboardingSnapshot>("/api/pack-onboarding"),
  updatePackOnboarding: (packId: string, body: PackOnboardingUpdateRequest) =>
    fetchJSON<PackOnboardingSnapshot>(`/api/pack-onboarding/${encodeURIComponent(packId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  completePackOnboarding: (packId: string) =>
    fetchJSON<PackOnboardingSnapshot>(`/api/pack-onboarding/${encodeURIComponent(packId)}/complete`, {
      method: "POST",
    }),
  getAdminDeadlines: () =>
    fetchJSON<{
      subjectsSoon: AdminDeadlineDeal[];
      closingsSoon: AdminDeadlineDeal[];
      staleStages: AdminDeadlineDeal[];
    }>("/api/admin/deals/deadlines"),
  getAdminJurisdiction: () => fetchJSON<AdminJurisdiction>("/api/admin/jurisdiction"),
  setAdminJurisdiction: (body: AdminJurisdictionUpdateRequest) =>
    fetchJSON<AdminJurisdiction>("/api/admin/jurisdiction", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAdminProvinceGuides: (province?: string) => {
    const tail = province ? `?province=${encodeURIComponent(province)}` : "";
    return fetchJSON<AdminProvinceGuidesResponse | AdminProvinceGuide>(`/api/admin/province-guides${tail}`);
  },
  importAdminProvinceGuides: (root?: string | null) =>
    fetchJSON<AdminProvinceGuideImportResult>("/api/admin/province-guides/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(root ? { root } : {}),
    }),
  getAdminDeals: (
    params: {
      side?: AdminDealSide;
      currentStage?: number;
      status?: string | null;
      province?: string | null;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.side) qs.set("side", params.side);
    if (params.currentStage != null) qs.set("current_stage", String(params.currentStage));
    if (params.status !== undefined) qs.set("status", params.status ?? "");
    if (params.province !== undefined) qs.set("province", params.province ?? "");
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return cachedFetchJSON<AdminDealsResponse>(`/api/admin/deals${tail}`, 2_500);
  },
  getAdminUpcomingEvents: (days = 21) => {
    const safeDays = Math.max(1, Math.min(Math.trunc(days || 21), 90));
    return cachedFetchJSON<AdminUpcomingEventsResponse>(
      `/api/admin/upcoming-events?days=${encodeURIComponent(String(safeDays))}`,
      2_500,
    );
  },
  createAdminDeal: (body: AdminDealCreateRequest) =>
    fetchJSON<AdminDeal>("/api/admin/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  promoteProfileToAdminDeal: (body: AdminProfilePromotionRequest) =>
    fetchJSON<AdminProfilePromotionResponse>("/api/admin/profile-promotions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  moveAdminDeal: (dealId: string, toStage: number) =>
    fetchJSON<AdminDeal>(`/api/admin/deals/${encodeURIComponent(dealId)}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toStage }),
    }),
  setAdminDealToggle: (dealId: string, field: string, value: AdminDealToggleValue) =>
    fetchJSON<AdminDeal>(`/api/admin/deals/${encodeURIComponent(dealId)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, value }),
    }),
  getDealContext: (dealId: string) =>
    fetchJSON<DealContext>(`/api/deals/${encodeURIComponent(dealId)}/context`),
  advanceDeal: (dealId: string, force = false) =>
    fetchJSON<DealContext>(`/api/deals/${encodeURIComponent(dealId)}/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    }),
  updateDealFields: (dealId: string, fields: Record<string, unknown>) =>
    fetchJSON<AdminDeal>(`/api/deals/${encodeURIComponent(dealId)}/fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields }),
    }),
  addDealContact: (dealId: string, body: DealContactCreateRequest) =>
    fetchJSON<DealContact>(`/api/deals/${encodeURIComponent(dealId)}/contacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  addDealAttachment: (dealId: string, body: DealAttachmentCreateRequest) =>
    fetchJSON<DealAttachment>(`/api/deals/${encodeURIComponent(dealId)}/attachments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  recordDealRunResult: (dealId: string, runId: string, body: DealRunResultRequest) =>
    fetchJSON<AdminActionRun>(`/api/deals/${encodeURIComponent(dealId)}/runs/${encodeURIComponent(runId)}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  approveAdminActionRun: (runId: string, body: { approved?: boolean; runNow?: boolean } = {}) =>
    fetchJSON<AdminActionRun>(`/api/admin/action-runs/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAdminActionRuns: (
    params: { dealId?: string; registryId?: string; status?: string; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.dealId) qs.set("deal_id", params.dealId);
    if (params.registryId) qs.set("registry_id", params.registryId);
    if (params.status) qs.set("status", params.status);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return cachedFetchJSON<{ items: AdminActionRun[]; count: number }>(`/api/admin/action-runs${tail}`, 2_500);
  },
  ensureDefaultAdminActions: () =>
    fetchJSON<{ created: AdminAction[]; updated?: AdminAction[]; skipped: AdminAction[]; count: number }>("/api/admin/actions/defaults", {
      method: "POST",
    }),
  drainAdminActionRuns: (limit = 50) =>
    fetchJSON<{ items: AdminActionRun[]; count: number }>(`/api/admin/action-runs/drain?limit=${encodeURIComponent(String(limit))}`, {
      method: "POST",
    }),
  getAdminDealTasks: (
    params: { status?: "open" | "done" | "all"; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return cachedFetchJSON<AdminDealTasksResponse>(`/api/admin/tasks${tail}`, 2_500);
  },
  runAdminDealTask: (body: AdminDealTaskRunRequest) =>
    fetchJSON<AdminActionRun>("/api/admin/tasks/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAdminContacts: (
    params: { tab?: string; type?: string; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.tab) qs.set("tab", params.tab);
    if (params.type) qs.set("type", params.type);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const tail = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJSON<AdminContactsResponse>(`/api/admin/contacts${tail}`);
  },

  // Real-estate source connectors and integrations
  getSourceConnectors: (options?: { includePrompts?: boolean }) =>
    fetchJSON<SourceConnectorsResponse>(
      `/api/source-connectors${options?.includePrompts ? "?include_prompts=true" : ""}`,
    ),
  getSourceRecords: (sourceId: string, limit = 12) =>
    fetchJSON<SourceRecordsResponse>(
      `/api/source-connectors/${encodeURIComponent(sourceId)}/records?limit=${limit}`,
    ),
  getSourceConnectorPrompt: (sourceId: string) =>
    fetchJSON<{ sourceId: string; prompt: string }>(
      `/api/source-connectors/${encodeURIComponent(sourceId)}/prompt`,
    ),
  getToday: (sourceLimit = 160) =>
    fetchJSON<TodayDashboardResponse>(`/api/today?source_limit=${encodeURIComponent(String(sourceLimit))}`),
  getSourceInbox: (limit = 16) =>
    cachedFetchJSON<SourceInboxResponse>(`/api/source-inbox?limit=${limit}`, 5_000),
  getThreadContext: (sourceId: string, threadId: string, limit = 200) =>
    fetchJSON<ThreadContextResponse>(
      `/api/source-inbox/thread/${encodeURIComponent(sourceId)}/${encodeURIComponent(threadId)}?limit=${limit}`,
    ),
  // Manual trigger for the composio inbound puller — used by the hub Refresh
  // button so a click pulls new DMs/replies in addition to re-reading state.
  pullComposioInbound: () =>
    fetchJSON<{
      tick_at: string;
      total_new: number;
      total_fetched: number;
      toolkits: Array<{
        toolkit: string;
        ok: boolean;
        skipped?: boolean;
        reason?: string;
        new?: number;
        fetched?: number;
      }>;
    }>("/api/composio/inbound/pull", { method: "POST" }),
  updateSourceInboxThread: (
    sourceId: string,
    threadId: string,
    action: "done" | "archive" | "restore" | "open",
    options?: { returnInbox?: boolean },
  ) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/thread", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceId, threadId, action, returnInbox: options?.returnInbox ?? true }),
    }),
  updateSourceInboxDraft: (
    sourceId: string,
    taskId: string,
    action: "approve" | "edit" | "skip" | "restore" | "open",
    draftText = "",
    options?: { returnInbox?: boolean },
  ) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceId, taskId, action, draftText, returnInbox: options?.returnInbox ?? true }),
    }),
  getAppleMessagesDirections: () =>
    fetchJSON<{ inbound: boolean; outbound: boolean }>(
      "/api/source-inbox/apple-messages/directions",
    ),
  setAppleMessagesDirections: (body: { inbound?: boolean; outbound?: boolean }) =>
    fetchJSON<{ inbound: boolean; outbound: boolean }>(
      "/api/source-inbox/apple-messages/directions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  updateSourceInboxProfile: (
    profileId: string,
    status: SourceInboxProfileStatus | null,
    options?: { returnInbox?: boolean },
  ) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profileId, status, returnInbox: options?.returnInbox ?? true }),
    }),
  updateSourceInboxProfileFavorite: (
    profileId: string,
    favorite: boolean,
    options?: { contactId?: string | null; returnInbox?: boolean },
  ) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/profile/favorite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId,
        favorite,
        contactId: options?.contactId ?? null,
        returnInbox: options?.returnInbox ?? true,
      }),
    }),
  // Sent-messages list for the /leads "Sent" tab. Reads outreach.db.send_queue
  // (status=sent by default). Set includePending=true to also see queued /
  // sending / retrying / failed for debugging mid-flight rows.
  getSourceInboxSent: (limit = 100, includePending = false) =>
    fetchJSON<SourceInboxSentResponse>(
      `/api/source-inbox/sent?limit=${limit}&include_pending=${includePending ? "true" : "false"}`,
    ),
  scaffoldSourceConnector: (sourceId: string) =>
    fetchJSON<SourceConnectorsResponse>("/api/source-connectors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "scaffold", sourceId }),
    }),
  refreshSourceConnector: (sourceId: string) =>
    fetchJSON<SourceConnectorsResponse & { refresh?: { tick_at: string; total_new: number; total_fetched: number; toolkits: Array<Record<string, unknown>> } }>(
      "/api/source-connectors",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "refresh", sourceId }),
      },
    ),
  runSourceConnectorPrompt: (sourceId: string) =>
    fetchJSON<SourceConnectorsResponse & {
      refresh?: { tick_at: string; total_new: number; total_fetched: number; toolkits: Array<Record<string, unknown>> };
      run?: {
        sourceId: string;
        wired: boolean;
        execution: "server_inline" | "agent_session_seed" | "agent_task_dispatched";
        prompt: string;
        next_action_for_operator: string | null;
        outcome: {
          kind: "ok" | "error" | "needs_operator" | "dispatched";
          message: string;
          recordCounts: { contacts: number; conversations: number; messages: number };
          lastError: string | null;
          authStatus: string | null;
          nextOperatorStep: string | null;
          sourceDir: string | null;
        };
      };
    }>("/api/source-connectors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "run-prompt", sourceId }),
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

export type * from "./api-types";
