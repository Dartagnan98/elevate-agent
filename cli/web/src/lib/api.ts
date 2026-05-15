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
  SourceInboxProfileStatus,
  CrmIntegrationForm,
  IntegrationSettingsResponse,
  IntegrationTestResponse,
  ActionResponse,
  ActionStatusResponse,
  UpdateStatusResponse,
  StatusResponse,
  AgentHandoff,
  AgentHandoffCreateRequest,
  AgentHandoffResultRequest,
  AgentHandoffApproveRequest,
  AgentWorkerSnapshot,
  AgentHubSnapshot,
  HarnessSnapshot,
  PaginatedSessions,
  EnvVarInfo,
  SessionMessagesResponse,
  LogsResponse,
  AnalyticsResponse,
  CronJob,
  CronJobCreateRequest,
  SkillInfo,
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
} from "./api-types";

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
  getAccessStatus: () => fetchJSON<AccessStatusResponse>("/api/access"),
  getLicenseStatus: () => fetchJSON<LicenseStatusResponse>("/api/license/status"),
  activateLicense: (email: string, password: string, backendUrl?: string) =>
    fetchJSON<LicenseActivateResponse>("/api/license/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, backend_url: backendUrl || undefined }),
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
    options?: { includeTotal?: boolean; includeDetails?: boolean },
  ) => {
    const qs = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (options?.includeTotal === false) qs.set("include_total", "false");
    if (options?.includeDetails) qs.set("include_details", "true");
    return fetchJSON<PaginatedSessions>(`/api/sessions?${qs.toString()}`);
  },
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
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status}: ${text}`);
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
  getCronJobs: (options?: { compact?: boolean }) =>
    fetchJSON<CronJob[]>(`/api/cron/jobs${options?.compact ? "?compact=true" : ""}`),
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
  getComposioConnections: () =>
    fetchJSON<ComposioApiResult<ComposioConnectedAccount[]>>(
      "/api/composio/connections",
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
  getUpdateStatus: (refresh = false) =>
    fetchJSON<UpdateStatusResponse>(
      `/api/elevate/update/status${refresh ? "?refresh=true" : ""}`,
    ),
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
    return fetchJSON<AgentHubSnapshot>(`/api/agent-hub${suffix ? `?${suffix}` : ""}`);
  },
  updateAgent: (
    agentId: string,
    patch: {
      enabled?: boolean;
      role?: string;
      description?: string;
      prompt?: string;
      skills?: string[];
      toolsets?: string[];
      platforms?: string[];
      session_sources?: string[];
    },
  ) =>
    fetchJSON<Record<string, unknown>>(`/api/agent-hub/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
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
  drainAgentHandoffs: (body: { toAgentId?: string; limit?: number } = {}) =>
    fetchJSON<{ items: AgentHandoff[]; count: number }>("/api/agent-handoffs/drain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  runAgentWorkerTick: () =>
    fetchJSON<AgentWorkerSnapshot>("/api/agent-worker/tick", {
      method: "POST",
    }),
  wakeAgentWorker: () =>
    fetchJSON<AgentWorkerSnapshot>("/api/agent-worker/wake", {
      method: "POST",
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
  getLeadsSetup: () => fetchJSON<LeadsSetupSnapshot>("/api/leads/setup"),
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
    return fetchJSON<AdminDealsResponse>(`/api/admin/deals${tail}`);
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
    return fetchJSON<{ items: AdminActionRun[]; count: number }>(`/api/admin/action-runs${tail}`);
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
    return fetchJSON<AdminDealTasksResponse>(`/api/admin/tasks${tail}`);
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
  getSourceConnectors: () =>
    fetchJSON<SourceConnectorsResponse>("/api/source-connectors"),
  getSourceRecords: (sourceId: string, limit = 12) =>
    fetchJSON<SourceRecordsResponse>(
      `/api/source-connectors/${encodeURIComponent(sourceId)}/records?limit=${limit}`,
    ),
  getSourceInbox: (limit = 16) =>
    fetchJSON<SourceInboxResponse>(`/api/source-inbox?limit=${limit}`),
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
  updateSourceInboxThread: (sourceId: string, threadId: string, action: "done" | "archive" | "restore" | "open") =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/thread", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceId, threadId, action }),
    }),
  updateSourceInboxDraft: (sourceId: string, taskId: string, action: "approve" | "edit" | "skip" | "restore" | "open", draftText = "") =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceId, taskId, action, draftText }),
    }),
  updateSourceInboxProfile: (profileId: string, status: SourceInboxProfileStatus | null) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profileId, status }),
    }),
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
        execution: "server_inline" | "agent_task_dispatched";
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
