# Elevate: API, Plugins, i18n
API client, types, plugin system, internationalization.

---
## `src/lib/api.ts`
```ts
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
  SourceInboxSentResponse,
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
  getCronAttention: () =>
    fetchJSON<import("./api-types").CronAttention>(`/api/cron/attention`),

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
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
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

```

---
## `src/lib/api-types.ts`
```ts
import type { DashboardTheme } from "@/themes/types";

export interface LicenseStatusResponse {
  authenticated: boolean;
  email: string | null;
  tier: string | null;
  license_id: string | null;
  entitlements: string[];
  expires_at: number | null;
  expired: boolean;
  status_text: string;
  packs: AccessStatusResponse["packs"];
}

export interface LicenseActivateResponse {
  authenticated: boolean;
  email: string;
  tier: string;
  license_id: string;
  entitlements: string[];
  expires_at: number;
  packs: AccessStatusResponse["packs"];
  skill_count: number;
  skill_names: string[];
  skill_error: string | null;
}

export interface LicenseSyncSkillsResponse {
  skill_count: number;
  skill_names: string[];
  path: string | null;
  removed: string[];
  errors: string[];
  packs: AccessStatusResponse["packs"];
}

export interface LicenseLogoutResponse {
  authenticated: false;
  cleared: boolean;
  packs: AccessStatusResponse["packs"];
}

export interface AccessEntitlementState {
  status: string;
  active: boolean;
  ownedSnapshot: boolean;
  description: string;
  requiresActiveAffiliation: boolean;
  manualLock: boolean;
}

export interface AccessStatusResponse {
  profile: string;
  devOverride?: boolean;
  mode?: "development" | "entitlement" | string;
  entitlements: Record<string, AccessEntitlementState>;
  packs: {
    realEstateSales: boolean;
    realEstateMarketing: boolean;
    realEstateAdmin: boolean;
    realEstateCma: boolean;
    realEstateAny: boolean;
  };
}

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

export interface SourceCategoryMeta {
  id: string;
  label: string;
  description: string;
}

export interface SourceConnectorStatus {
  id: string;
  label: string;
  category: string;
  description: string;
  wired: boolean;
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
  runMode: "server_inline" | "agent_session" | "agent_setup_task" | string;
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
  categories: SourceCategoryMeta[];
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
  leadSectionIds?: string[];
  record: SourceRecord;
}

export interface SourceInboxProfileVerifier {
  kind: "phone" | "email" | string;
  value: string;
  key: string;
}

export type SourceInboxProfileStatus =
  | "new_lead"
  | "follow_up"
  | "ghosting"
  | "dead"
  | "closed_seller"
  | "closed_buyer";

export interface SourceInboxProfile {
  id: string;
  displayName: string;
  sources: string[];
  sourceIds: string[];
  channels: string[];
  contactIds: string[];
  conversationIds: string[];
  verifiers: SourceInboxProfileVerifier[];
  phones: string[];
  emails: string[];
  threadIds: string[];
  threadCount: number;
  latestText: string;
  latestAt: string;
  heatScore: number;
  heatLabel: "hot" | "warm" | "watch" | "normal" | string;
  hasCrm: boolean;
  hasConversation: boolean;
  isPotentialLead: boolean;
  crmStage: string | null;
  leadSource: string | null;
  tags: string[];
  status: SourceInboxProfileStatus | null;
  statusUpdatedAt: string | null;
  leadSectionIds?: string[];
}

export interface SourceInboxDraft {
  id: string;
  sourceId: string;
  sourceLabel: string;
  taskId: string;
  threadId: string;
  contactId: string | null;
  conversationId: string | null;
  personName: string;
  channel: string;
  title: string;
  draftText: string;
  context: string;
  latestAt: string;
  status: "pending" | "approved" | "skipped" | string;
  approvalRequired: boolean;
  generated: boolean;
  fallback?: boolean;
  templateId?: string | null;
  templateName?: string | null;
  outreachLane?: OutreachLane | string | null;
  record: SourceRecord;
  skippedAt?: string | null;
  score?: number | null;
  leadLabel?: string | null;
  scoreReason?: string | null;
  leadSectionIds?: string[];
}

export type OutreachLane = "new-outreach" | "hot-leads-watcher" | "follow-ups";

export type OutreachTemplateStatus = "active" | "pending_approval" | "archived";

export interface OutreachTemplate {
  id: string;
  lane: OutreachLane;
  name: string;
  body: string;
  channel: string;
  active: boolean;
  status: OutreachTemplateStatus;
  rationale?: string | null;
  uses: number;
  replies: number;
  wins: number;
  replyRate: number;
  winRate: number;
  createdAt: string;
  updatedAt: string;
}

export interface OutreachLaneOverview {
  lane: OutreachLane;
  totalTemplates: number;
  activeTemplates: number;
  pendingTemplates: number;
  totalAttempts: number;
  totalReplies: number;
  laneReplyRate: number;
  best: OutreachTemplate | null;
  worst: OutreachTemplate | null;
  drift: {
    template: OutreachTemplate;
    recent: { uses: number; replies: number; wins: number; replyRate: number; winRate: number };
    deltaPct: number;
  }[];
  pending: OutreachTemplate[];
}

export interface OutreachOverview {
  lanes: OutreachLaneOverview[];
  pendingTotal: number;
  thresholds: { minUsesForRanking: number; driftDropPct: number; recentWindowDays: number };
}

export type AdminDealSide = "listing" | "buyer";

export type AdminDealToggleValue = string | boolean | null;

export interface AdminDealCreateRequest {
  title: string;
  side: AdminDealSide;
  // Province chooses the backend flow package. Board/market are optional deal metadata.
  province?: string;
  board?: string | null;
  market?: string | null;
  currentStage?: number;
  primaryContactId?: string | null;
  loftyContactId?: string | null;
  listingAddress?: string | null;
  fields?: Record<string, unknown>;
}

export interface AdminProfilePromotionRequest {
  profileId: string;
  side: AdminDealSide;
  displayName?: string | null;
  primaryContactId?: string | null;
  listingAddress?: string | null;
  workflow?: string | null;
  province?: string | null;
  board?: string | null;
  market?: string | null;
  currentStage?: number;
  profileContext?: Record<string, unknown>;
  verifiers?: SourceInboxProfileVerifier[];
  fields?: Record<string, unknown>;
  dispatchInitialStage?: boolean;
}

export interface AdminProfilePromotionResponse {
  action: "created" | "updated" | string;
  matchReason: string | null;
  deal: AdminDeal;
}

export interface AdminDeal {
  id: string;
  title: string;
  side: AdminDealSide;
  currentStage: number;
  status: "active" | "closed" | "archived" | string;
  province: string | null;
  board?: string | null;
  market?: string | null;
  sourceKey?: string | null;
  sourceRowId?: string | null;
  sourceLabel?: string | null;
  sourceSyncedAt?: string | null;
  primaryContactId: string | null;
  loftyContactId: string | null;
  listingAddress: string | null;
  extraToggles: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  stageEnteredAt: string;
  closedAt: string | null;
  signingAuthority: string | null;
  fintracFormType: string | null;
  listingTrack: string | null;
  propertySubtype: string | null;
  estateStatus: string | null;
  transactionType: string | null;
  listingType: string | null;
  pep: boolean | null;
  tenanted: boolean | null;
  poaSigning: boolean | null;
  corporate: boolean | null;
  hasSuite: boolean | null;
  multipleOffers: boolean | null;
  familyMember: boolean | null;
  dualRep: boolean | null;
  unrepresentedOtherSide: boolean | null;
  lockbox: boolean | null;
  delayedOffer: boolean | null;
  saleOfBuyersProperty: boolean | null;
  listingDate?: string | null;
  offerDate?: string | null;
  subjectRemovalDate?: string | null;
  depositDueDate?: string | null;
  completionDate?: string | null;
  possessionDate?: string | null;
  anniversaryDate?: string | null;
  listPrice?: number | null;
  offerPrice?: number | null;
  depositAmount?: number | null;
  commissionPct?: number | null;
  mlsNumber?: string | null;
  legalDescription?: string | null;
  lotSizeSqft?: number | null;
  yearBuilt?: number | null;
  depositInTrustAt?: string | null;
  listingPublishedAt?: string | null;
  offerAcceptedAt?: string | null;
  subjectsRemovedAt?: string | null;
  completedAt?: string | null;
}

export interface DealContactCreateRequest {
  role: string;
  contactId: string;
  notes?: string | null;
}

export interface DealContact {
  id: string;
  dealId: string;
  role: string;
  contactId: string;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
  contact?: AdminContact | null;
}

export interface DealAttachmentCreateRequest {
  kind: string;
  filePath: string;
  summary?: string | null;
  sourceRunId?: string | null;
  sourceSnapshotId?: string | null;
}

export interface DealAttachment {
  id: string;
  dealId: string;
  kind: string;
  filePath: string;
  summary: string | null;
  sourceRunId: string | null;
  sourceSnapshotId: string | null;
  createdAt: string;
}

export interface AdminAction {
  id: string;
  name: string;
  side: AdminDealSide | null;
  fromStage: number | null;
  toStage: number | null;
  trigger: string;
  fieldKey: string | null;
  condition: Record<string, unknown> | null;
  skill: string;
  skillArgs: Record<string, unknown>;
  provinceFilter: string[] | null;
  enabled: boolean;
  priority: number;
  approvalRequired: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface AdminActionRun {
  id: string;
  registryId: string;
  dealId: string;
  dealEventId: string | null;
  cronJobId: string | null;
  harnessRunId?: string | null;
  status: string;
  outputPath: string | null;
  errorMessage: string | null;
  payload: Record<string, unknown> | null;
  humanPrompt?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  resultIdempotencyKey?: string | null;
  createdAt: string;
  startedAt?: string | null;
  updatedAt: string;
  completedAt: string | null;
  skill?: string | null;
  registryName?: string | null;
}

export interface AdminDealTask {
  id: string;
  type: "action_run" | "ai_action" | "checklist" | "field" | "document" | string;
  source: string;
  title: string;
  description: string | null;
  status: string;
  dealId: string;
  dealTitle: string;
  side: AdminDealSide;
  currentStage: number;
  stageName: string;
  packageKey: string;
  skill: string | null;
  canRunWithAi: boolean;
  runId: string | null;
  handoffId?: string | null;
  field: string | null;
  kind: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface AdminDealTasksResponse {
  items: AdminDealTask[];
  count: number;
}

export interface AdminDealTaskRunRequest {
  dealId: string;
  skill: string;
  title?: string | null;
  sourceTaskId?: string | null;
  runNow?: boolean;
}

export interface DealRunResultArtifact {
  kind: string;
  filePath?: string | null;
  file_path?: string | null;
  summary?: string | null;
  sourceSnapshotId?: string | null;
  source_snapshot_id?: string | null;
}

export interface DealRunResultRequest {
  status: string;
  idempotency_key?: string | null;
  idempotencyKey?: string | null;
  artifacts?: DealRunResultArtifact[];
  next_tasks?: Array<Record<string, unknown>>;
  nextTasks?: Array<Record<string, unknown>>;
  checklist_updates?: Array<Record<string, unknown>>;
  checklistUpdates?: Array<Record<string, unknown>>;
  human_prompt?: Record<string, unknown> | null;
  humanPrompt?: Record<string, unknown> | null;
  error?: string | null;
}

export interface DealFlowChecklistItem {
  id: string;
  label: string;
  required?: boolean;
}

export interface DealFlowFieldRequirement {
  field: string;
  label: string;
}

export interface DealFlowDocRequirement {
  kind: string;
  label: string;
}

export interface DealFlowRunBlocker {
  id: string;
  label: string;
  status: string;
  updatedAt?: string | null;
}

export interface DealPhaseGate {
  stage: number;
  stageName: string;
  nextStage: number | null;
  nextStageName: string | null;
  canAdvance: boolean;
  completedChecklist: number;
  totalChecklist: number;
  missingChecklist: DealFlowChecklistItem[];
  missingFields: DealFlowFieldRequirement[];
  missingDocs: DealFlowDocRequirement[];
  blockingRuns: DealFlowRunBlocker[];
}

export interface DealFlowResolution {
  packageKey: string;
  side: AdminDealSide;
  stage: number;
  stageName: string;
  stageSubtitle: string;
  nextStage: number | null;
  nextStageName: string | null;
  checklistItems: DealFlowChecklistItem[];
  requiredFields: DealFlowFieldRequirement[];
  requiredDocs: DealFlowDocRequirement[];
  requiredForms: Array<{ code: string; name: string }>;
  automationTriggers: Array<{ id: string; label: string; skill: string }>;
  backgroundAutomations: Array<{
    id: string;
    name: string;
    skill: string;
    kind: string;
    affectsStages?: number[];
    description?: string;
  }>;
  localOverrides: Record<string, unknown>;
  gate: DealPhaseGate;
}

export interface DealContext {
  deal: AdminDeal;
  primaryContact: AdminContact | null;
  coContacts: DealContact[];
  conditions: Record<string, AdminDealToggleValue>;
  conditionalDocs?: ProvinceConditionalDoc[];
  checklist: Record<string, unknown>;
  attachments: DealAttachment[];
  priorRuns: AdminActionRun[];
  dealFlow?: DealFlowResolution;
  provinceGuide?: AdminProvinceGuide;
  agentGuideMemory?: Record<string, unknown>;
  stageDocuments?: ProvinceStageDocuments;
  events: Array<Record<string, unknown>>;
}

export interface ProvinceStageDocumentItem {
  code: string;
  name: string;
  source: "form" | "conditional";
  side?: string | null;
  category?: string | null;
  sourcePath?: string | null;
  condition?: { field: string; value: string } | null;
}

export interface ProvinceStageDocuments {
  province: string;
  side: string;
  stages: Record<string, ProvinceStageDocumentItem[]>;
  unmapped: Array<{ code: string; name: string; category?: string | null }>;
  otherSide: Array<{ code: string; name: string; category?: string | null; side?: string | null }>;
  coverage: {
    forms: number;
    mapped: number;
    conditional: number;
    otherSide: number;
    unmapped: number;
  };
}

export interface ProvinceConditionalDoc {
  id: string;
  province: string;
  side?: string | null;
  stage?: number | null;
  fieldKey: string;
  fieldValue: string;
  docCode: string;
  docName: string;
  notes?: string | null;
}

export interface AdminProvinceGuidePage {
  province: string;
  slug: string;
  pageType?: string;
  title: string;
  sourceUrl?: string | null;
  sourcePath?: string | null;
}

export interface AdminProvinceGuideForm {
  province: string;
  code: string;
  name: string;
  category?: string | null;
  pageCount?: number | null;
  annotationCount?: number | null;
  localImagePaths?: string[];
}

export interface AdminProvinceGuide {
  province: string;
  provinceLabel: string;
  coverage: {
    referencePages: number;
    checklists: number;
    forms: number;
    pageTypes?: Record<string, number>;
    hasTransactionGuide: boolean;
  };
  pages: AdminProvinceGuidePage[];
  checklists: AdminProvinceGuidePage[];
  forms: AdminProvinceGuideForm[];
}

export interface AdminProvinceGuideCoverage {
  province: string;
  provinceLabel: string;
  referencePages: number;
  listingsSalesPages: number;
  checklists: number;
  forms: number;
  hasTransactionGuide: boolean;
}

export interface AdminProvinceGuidesResponse {
  items: AdminProvinceGuideCoverage[];
}

export interface AdminProvinceGuideImportResult {
  ok: boolean;
  root: string;
  error?: string;
  pages: number;
  checklists: number;
  forms: number;
  conditionalDocs: number;
  provinces: string[];
}

export interface AdminJurisdiction {
  country: string;
  province: string;
  market: string;
  packageKey: string;
}

export interface AdminJurisdictionUpdateRequest {
  country?: string;
  province?: string;
  market?: string;
  packageKey?: string;
}

export type AdminSetupItemStatus = "missing" | "configured" | "connected" | "manual" | "skipped";

export interface AdminSetupProfile {
  id: string;
  realtorLegalName?: string | null;
  licenseName?: string | null;
  brokerageName?: string | null;
  teamName?: string | null;
  country: string;
  province: string;
  market?: string | null;
  boardMemberships: string[];
  emailProvider?: string | null;
  calendarProvider?: string | null;
  driveProvider?: string | null;
  crmProvider?: string | null;
  mlsProvider?: string | null;
  formsProvider?: string | null;
  signingProvider?: string | null;
  complianceProvider?: string | null;
  showingProvider?: string | null;
  fintracProvider?: string | null;
  approvalChannel?: string | null;
  managingBrokerEmail?: string | null;
  defaultFolderPattern?: string | null;
  commissionNotes?: string | null;
  servicesSchedule?: string | null;
  regionalMemory: Record<string, unknown>;
  approvalPolicy: Record<string, unknown>;
  completedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AdminSetupItem {
  key: string;
  category: string;
  label: string;
  description?: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
  sortOrder: number;
  updatedAt: string;
}

export interface AdminSetupReadinessItem {
  key: string;
  label: string;
  category?: string | null;
  status: AdminSetupItemStatus;
  provider?: string | null;
  ready: boolean;
  state: string;
  detail: string;
  action: string;
  hasValue: boolean;
  updatedAt?: string | null;
}

export interface AdminSetupSnapshot {
  profile: AdminSetupProfile;
  items: AdminSetupItem[];
  readiness?: AdminSetupReadinessItem[];
  complete: boolean;
  launchRequired: boolean;
  canStartAdmin: boolean;
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  memory?: {
    path?: string;
    synced?: boolean;
    bytes?: number;
  };
  playbook?: {
    path?: string;
    bytes?: number;
    province?: string | null;
    hasProvinceGuide?: boolean;
  };
  verificationWarnings?: string[];
}

export interface AdminSetupUpdateRequest {
  profile?: Partial<AdminSetupProfile>;
  items?: Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
    notes?: string | null;
  }>;
}

export interface PackOnboardingItem {
  packId: string;
  key: string;
  category: string;
  label: string;
  description?: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider?: string | null;
  envKeys: string[];
  value?: unknown;
  notes?: string | null;
  sortOrder: number;
  updatedAt?: string | null;
  source?: string;
}

export interface PackOnboardingPack {
  packId: string;
  label: string;
  entitlement: string;
  description: string;
  unlocked: boolean;
  status: AdminSetupItemStatus;
  complete: boolean;
  launchRequired: boolean;
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  completedAt?: string | null;
  updatedAt?: string | null;
  items: PackOnboardingItem[];
}

export interface PackOnboardingSnapshot {
  packs: PackOnboardingPack[];
  activeCount: number;
  completedActiveCount: number;
  launchRequiredPacks: string[];
  complete: boolean;
  memory?: {
    path?: string;
    synced?: boolean;
    bytes?: number;
  };
}

export interface PackOnboardingUpdateRequest {
  items?: Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
    notes?: string | null;
  }>;
}

export interface LeadsSetupItem {
  key: string;
  category: string;
  label: string;
  description: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider: string | null;
  value: unknown;
  notes: string | null;
  sortOrder: number;
  updatedAt: string | null;
}

export interface OutreachConnectorRef {
  id: "apple-messages" | "sms-provider" | "android-device" | "rcs";
  label: string;
  state: "connected" | "import_only" | "blocked" | "needs_operator" | "not_configured";
  connected: boolean;
  importOnly: boolean;
  blocked: boolean;
  nextOperatorStep: string | null;
  lastError: string | null;
  ownerAgent: string;
  totalRecords: number;
}

export interface LeadsSetupSnapshot {
  items: LeadsSetupItem[];
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  complete: boolean;
  completedAt: string | null;
  launchRequired: boolean;
  leadSourcesReady: boolean;
  outreachReady: boolean;
  outreachConnectors: OutreachConnectorRef[];
}

export interface LeadsSetupItemUpdate {
  key: string;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
}

export interface AgentSetupItem {
  key: string;
  category: string;
  label: string;
  description: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider: string | null;
  value: unknown;
  notes: string | null;
  sortOrder: number;
  updatedAt: string | null;
}

export interface AgentSetupSnapshot {
  items: AgentSetupItem[];
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  complete: boolean;
  completedAt: string | null;
  launchRequired: boolean;
}

export interface AgentSetupItemUpdate {
  key: string;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
}

export interface AdminDealsResponse {
  items: AdminDeal[];
  count: number;
  jurisdiction?: AdminJurisdiction;
}

export interface AdminContact {
  id: string;
  displayName: string | null;
  primaryEmail: string | null;
  primaryPhone: string | null;
  type: string | null;
  stage: string | null;
  lastActivityAt: string | null;
  ownerNotes?: string | null;
  parkedReason?: string | null;
  hasOpenConflict?: boolean;
  classifiedAt?: string | null;
  sourceKey?: string | null;
  ingestRunId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AdminContactsResponse {
  items: AdminContact[];
  count: number;
  tab: string | null;
  limit: number;
  offset: number;
}

export interface ComposioStatus {
  configured: boolean;
  hasKey: boolean;
  valid: boolean;
  baseUrl?: string;
  error?: string;
  status?: number;
}

export interface AyrshareStatus {
  configured: boolean;
  hasKey: boolean;
  valid: boolean;
  baseUrl?: string;
  error?: string;
  status?: number;
  active_social_accounts?: string[];
  display_names?: Array<{
    platform?: string;
    displayName?: string;
    userImage?: string;
    [key: string]: unknown;
  }>;
  monthly_post_count?: number;
  monthly_post_quota?: number;
}

export interface SocialDerived {
  reach?: number | null;
  impressions?: number | null;
  plays?: number | null;
  likes?: number | null;
  comments?: number | null;
  saves?: number | null;
  shares?: number | null;
  video_views?: number | null;
  engagement_total?: number | null;
  engagement_rate?: number | null;
  save_rate?: number | null;
  hook_rate?: number | null;
  hold_rate?: number | null;
  avg_watch_time_sec?: number | null;
  duration_sec?: number | null;
  [key: string]: unknown;
}

export interface SocialPostSummary {
  platform?: string;
  post_id: string;
  permalink?: string | null;
  caption?: string | null;
  media_type?: string;
  posted_at?: string | null;
  derived: SocialDerived;
}

export interface SocialPlatformBlock {
  post_count: number;
  totals: { reach: number; impressions: number; engagement_total: number };
  averages: {
    engagement_rate: number | null;
    hook_rate: number | null;
    hold_rate: number | null;
    save_rate: number | null;
  };
  top_posts: SocialPostSummary[];
  bottom_posts: SocialPostSummary[];
  account_metrics: Record<string, unknown>;
}

export interface SocialSnapshot {
  exists?: boolean;
  generated_at?: string;
  lookback_days?: number;
  window_start?: string;
  platforms?: Record<string, SocialPlatformBlock>;
  totals?: { post_count: number; reach: number; impressions: number; engagement_total: number };
  top_posts?: SocialPostSummary[];
  bottom_posts?: SocialPostSummary[];
  format_breakdown?: Record<string, Record<string, number>>;
  wow_delta?: {
    post_count_delta: number;
    engagement_rate_delta: number | null;
    hook_rate_delta: number | null;
    hold_rate_delta: number | null;
  };
  account_metrics?: Record<string, Record<string, unknown>>;
  message?: string;
  snapshot_path?: string;
}

export interface SocialIdea {
  source_record_id: string;
  source_id?: string;
  title?: string;
  status?: string;
  task_type?: string;
  approval_required?: boolean;
  timestamp?: string;
  platform: string;
  format: string;
  hook: string;
  concept: string;
  outline?: string[];
  best_post_time?: string | null;
  target_audience?: string | null;
  grounded_in?: { metric?: string; trend?: string; signal?: string };
  reasoning?: string | null;
  suggested_assets?: string[];
  draft_text?: string;
  notes?: Array<{ ts: string; text: string }>;
  last_action_at?: string;
}

export interface SocialMetricRow {
  platform: string;
  post_id: string;
  fetched_at: string;
  posted_at?: string | null;
  media_type?: string;
  permalink?: string | null;
  caption?: string | null;
  metrics: Record<string, unknown>;
  raw?: Record<string, unknown> | null;
}

export interface ComposioApiResult<T> {
  ok: boolean;
  data?: T;
  status?: number;
  error?: string;
  raw?: unknown;
}

export interface ComposioToolkitMeta {
  logo?: string;
  description?: string;
  app_url?: string;
  tools_count?: number;
  triggers_count?: number;
  categories?: { id?: string; name?: string }[];
  [key: string]: unknown;
}

export interface ComposioConnectedAccount {
  id?: string;
  status?: string;
  toolkit?: { slug?: string; name?: string; logo?: string; meta?: ComposioToolkitMeta };
  user_id?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface ComposioToolkit {
  slug?: string;
  name?: string;
  description?: string;
  logo?: string;
  meta?: ComposioToolkitMeta;
  categories?: { slug?: string; id?: string; name?: string }[];
  [key: string]: unknown;
}

export interface ComposioConnectInitResponse {
  redirect_url?: string;
  redirect_uri?: string;
  connected_account_id?: string;
  [key: string]: unknown;
}

export interface ComposioAuthField {
  name: string;
  displayName?: string;
  type?: string;
  description?: string;
  required?: boolean;
  default?: string;
}

export interface ComposioAuthScheme {
  name: string;
  mode: string;
  fields?: {
    auth_config_creation?: {
      required?: ComposioAuthField[];
      optional?: ComposioAuthField[];
    };
    connected_account_initiation?: {
      required?: ComposioAuthField[];
      optional?: ComposioAuthField[];
    };
  };
  auth_hint_url?: string | null;
}

export interface ComposioToolkitDetails {
  name?: string;
  slug?: string;
  composio_managed_auth_schemes?: string[];
  auth_config_details?: ComposioAuthScheme[];
  auth_guide_url?: string | null;
  meta?: ComposioToolkitMeta;
  [key: string]: unknown;
}

export interface ThreadContextMessage {
  id: string;
  direction: "inbound" | "outbound" | string;
  sender: string | null;
  text: string;
  timestamp: string | null;
}

export interface ThreadContextSend {
  id: string;
  channel: string | null;
  status: string | null;
  attempts: number;
  providerMessageId: string | null;
  payload: { text?: string; body?: string; [key: string]: unknown } | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ThreadContextMeta {
  score: number;
  label: string;
  reason: string | null;
  scoredBy: string | null;
  scoredAt: string | null;
  updatedAt: string | null;
}

export interface ThreadContextLead {
  leadId: string | null;
  displayName: string | null;
  stage: string | null;
  leadSource: string | null;
  assignedUser: string | null;
  score: number | null;
  tags: string[];
  summary: string | null;
  emails: string[];
  phones: string[];
  channel: string | null;
  timestamp: string | null;
  lastSeenAt: string | null;
}

export interface ThreadContextActivity {
  id: string;
  type: string;
  subtype?: string | null;
  title: string | null;
  summary: string | null;
  address?: string | null;
  timestamp: string | null;
}

export interface ThreadContextNote {
  id: string;
  title: string;
  summary: string;
  author?: string | null;
  timestamp: string | null;
}

export interface ThreadContextTask {
  id: string;
  title: string;
  summary: string;
  status: string;
  dueAt?: string | null;
  timestamp: string | null;
}

export interface ThreadContextResponse {
  sourceId: string;
  threadId: string;
  source: {
    id?: string;
    label?: string;
    category?: string;
    ownerAgent?: string;
    connected?: boolean;
  };
  personName: string;
  messageCount: number;
  messages: ThreadContextMessage[];
  lastInboundAt?: string | null;
  lastOutboundAt?: string | null;
  pendingDraft: SourceInboxDraft | null;
  sends: ThreadContextSend[];
  meta: ThreadContextMeta | null;
  lead: ThreadContextLead | null;
  notes: ThreadContextNote[];
  tasks: ThreadContextTask[];
  activity: ThreadContextActivity[];
}

export interface BuyerWatchlistEntry {
  id: string;
  contactId?: string | null;
  name: string;
  email?: string;
  phone?: string;
  score?: number | null;
  tier?: string | null;
  days?: number | null;
  lastActivity?: string | null;
  dateEntered?: string | null;
  searches?: string[];
  matchingListings?: string[];
  profileUrl?: string | null;
  source?: string;
  sourceLabel?: string;
  tags?: string[];
  scrapedAt?: string | null;
  leadSectionIds?: string[];
}

export interface LeadSectionSummary {
  id: string;
  label: string;
  source: string;
  count: number;
  contactIds: string[];
  threadIds: string[];
  profileIds: string[];
  draftIds: string[];
  buyerIds: string[];
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
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
  drafts: SourceInboxDraft[];
  skippedDrafts?: SourceInboxDraft[];
  privateSearchBuyers?: BuyerWatchlistEntry[];
  leadSections?: Record<string, LeadSectionSummary>;
}

export interface SourceInboxSentItem {
  id: string;
  idempotencyKey: string;
  sourceId: string;
  threadId: string;
  taskId: string;
  channel: string;
  status: "queued" | "sending" | "sent" | "retrying" | "failed" | string;
  attempts: number;
  nextRetryAt?: string | null;
  lastError?: string | null;
  providerMessageId?: string | null;
  attemptId?: string | null;
  createdAt: string;
  updatedAt: string;
  payload: {
    draft_text?: string;
    recipient?: {
      person_name?: string | null;
      contact_id?: string | null;
      conversation_id?: string | null;
      phone?: string | null;
      email?: string | null;
      social_handle?: string | null;
    };
    channel_meta?: {
      toolkit?: string | null;
      account_id?: string | null;
      [k: string]: unknown;
    };
    source_id?: string;
    thread_id?: string;
    task_id?: string;
    [k: string]: unknown;
  };
}

export interface SourceInboxSentResponse {
  items: SourceInboxSentItem[];
  limit: number;
  includePending: boolean;
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

export interface UpdateStatusResponse {
  ahead: number;
  available: boolean;
  behind: number | null;
  branch: string | null;
  checked_at: number;
  command: string;
  error: string | null;
  local: string | null;
  origin_url: string | null;
  repo_dir: string | null;
  upstream: string | null;
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

export type AgentHandoffStatus =
  | "queued"
  | "running"
  | "waiting_human"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentHandoffMessage {
  id: string;
  handoffId: string;
  fromAgentId: string;
  toAgentId: string | null;
  kind: "request" | "note" | "status" | "result" | "human_prompt" | "error" | string;
  content: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
}

export interface AgentHandoff {
  id: string;
  fromAgentId: string;
  toAgentId: string;
  title: string;
  task: string;
  status: AgentHandoffStatus | string;
  priority: "low" | "normal" | "high" | "urgent" | string;
  dealId: string | null;
  profileId: string | null;
  contactId: string | null;
  conversationId: string | null;
  sourceRunId: string | null;
  parentHandoffId: string | null;
  cronJobId: string | null;
  idempotencyKey: string | null;
  resultIdempotencyKey: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  errorMessage: string | null;
  createdAt: string;
  claimedAt: string | null;
  updatedAt: string;
  completedAt: string | null;
  messages?: AgentHandoffMessage[] | null;
}

export interface AgentHandoffCreateRequest {
  fromAgentId: string;
  toAgentId: string;
  task: string;
  title?: string | null;
  priority?: "low" | "normal" | "high" | "urgent";
  dealId?: string | null;
  profileId?: string | null;
  contactId?: string | null;
  conversationId?: string | null;
  sourceRunId?: string | null;
  parentHandoffId?: string | null;
  payload?: Record<string, unknown> | null;
  idempotencyKey?: string | null;
  runNow?: boolean;
}

export interface AgentHandoffResultRequest {
  status?: Exclude<AgentHandoffStatus, "queued">;
  result?: Record<string, unknown> | null;
  errorMessage?: string | null;
  humanPrompt?: Record<string, unknown> | null;
  idempotencyKey?: string | null;
  actor?: string;
}

export interface AgentHandoffApproveRequest {
  approved?: boolean;
  runNow?: boolean;
  actor?: string;
}

export interface AgentHandoffSummary {
  total: number;
  queued: number;
  running: number;
  waitingHuman: number;
  completed: number;
  failed: number;
  cancelled: number;
  open: number;
  byAgent: Array<{
    agentId: string;
    total: number;
    queued: number;
    running: number;
    waitingHuman: number;
    completed: number;
    failed: number;
  }>;
  recent: AgentHandoff[];
  error: string;
}

export interface AgentWorkerSnapshot {
  enabled: boolean;
  mode?: string;
  state: "idle" | "ok" | "disabled" | "locked" | "error" | string;
  lastReason?: string;
  lastTickAt: string | null;
  lastSuccessAt: string | null;
  lastError: string;
  drained: {
    handoffs: number;
    adminRuns: number;
  };
  recovered?: {
    staleHandoffs: number;
    staleAdminRuns?: number;
  };
  limits: {
    handoffs: number;
    adminRuns: number;
    staleRunningMinutes?: number;
  };
  heartbeat?: {
    enabled: boolean;
    intervalSeconds: number;
    lastBeatAt: string | null;
    nextBeatAt: string | null;
  };
  wake?: {
    enabled: boolean;
    pending: boolean;
    lastWakeAt: string | null;
    lastReason: string;
    count: number;
  };
  loop?: {
    running: boolean;
    startedAt: string | null;
  };
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
  status: "online" | "ready" | "offline" | "disabled" | "needs_model" | "needs_telegram" | string;
  session_count: number;
  active_session_count: number;
  has_prompt: boolean;
  telegramLane?: {
    configured: boolean;
    tokenConfigured: boolean;
    targetConfigured: boolean;
    tokenEnv: string;
    targetEnv: string;
    chatConfigured: boolean;
    topicConfigured: boolean;
    usesSharedBot: boolean;
    duplicateSharedBot?: boolean;
    error?: string;
  } | null;
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
  handoffs: AgentHandoffSummary;
  agentWorker: AgentWorkerSnapshot;
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
    available?: Array<{ name: string; category: string; description: string }>;
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
  schedule: { kind: string; expr?: string; display?: string; run_at?: string; minutes?: number };
  schedule_display: string;
  skill?: string | null;
  skills?: string[];
  workdir?: string | null;
  tier?: string | null;
  agent?: string | null;
  enabled: boolean;
  state: string;
  deliver?: string;
  paused_at?: string | null;
  paused_reason?: string | null;
  alignment_status?: "aligned" | "blocked" | "optional" | "legacy" | string | null;
  alignment_reason?: string | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
  last_status?: string | null;
  last_summary?: string | null;
  last_session_id?: string | null;
}

export interface CronAttention {
  pending_drafts: number;
  errored_jobs: Array<{
    id: string;
    name?: string;
    last_error?: string;
    last_run_at?: string;
  }>;
  stale_jobs: Array<{
    id: string;
    name?: string;
    last_run_at?: string;
    hours_since?: number;
  }>;
  total: number;
}

export interface CronJobCreateRequest {
  prompt: string;
  schedule: string;
  name?: string;
  deliver?: string;
  skill?: string | null;
  skills?: string[];
  agent?: string | null;
  tier?: string | null;
  model?: string | null;
  provider?: string | null;
  base_url?: string | null;
  enabled_toolsets?: string[];
  workdir?: string | null;
  expected_readiness_version?: string | null;
  backfill_pending?: boolean;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export interface SkillTreeNode {
  name: string;
  type: "file" | "dir";
  path: string;
  children?: SkillTreeNode[];
}

export interface SkillTreeResponse {
  name: string;
  root?: string;
  tree: SkillTreeNode[];
  error?: string;
}

export interface SkillFileResponse {
  name: string;
  path: string;
  size?: number;
  content?: string;
  binary?: boolean;
  error?: string;
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

// ── Telegram pairing types ─────────────────────────────────────────────

export interface TelegramPairStartResponse {
  ok: boolean;
  action: string;
  pid: number;
}

export interface TelegramPendingEntry {
  platform: string;
  code: string;
  user_id: string;
  user_name: string;
  age_minutes: number;
}

export interface TelegramApprovedEntry {
  platform: string;
  user_id: string;
  user_name: string;
  approved_at: number;
}

export interface TelegramPairListResponse {
  pending: TelegramPendingEntry[];
  approved: TelegramApprovedEntry[];
}

export interface TelegramPairApproveResponse {
  ok: boolean;
  user_id: string;
  user_name: string;
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

```

---
## `src/lib/dashboard-flags.ts`
```ts
declare global {
  interface Window {
    /** Set true by the server only for `elevate dashboard --tui` (or ELEVATE_DASHBOARD_TUI=1). */
    __ELEVATE_DASHBOARD_EMBEDDED_CHAT__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`elevate dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__ === true;
}

```

---
## `src/lib/gatewayClient.ts`
```ts
/**
 * Browser WebSocket client for the tui_gateway JSON-RPC protocol.
 *
 * Speaks the exact same newline-delimited JSON-RPC dialect that the Ink TUI
 * drives over stdio. The server-side transport abstraction
 * (tui_gateway/transport.py + ws.py) routes the same dispatcher's writes
 * onto either stdout or a WebSocket depending on how the client connected.
 *
 *   const gw = new GatewayClient()
 *   await gw.connect()
 *   const { session_id } = await gw.request<{ session_id: string }>("session.create")
 *   gw.on("message.delta", (ev) => console.log(ev.payload?.text))
 *   await gw.request("prompt.submit", { session_id, text: "hi" })
 */

export type GatewayEventName =
  | "gateway.ready"
  | "session.info"
  | "message.start"
  | "message.delta"
  | "message.complete"
  | "thinking.delta"
  | "reasoning.delta"
  | "reasoning.available"
  | "status.update"
  | "tool.start"
  | "tool.progress"
  | "tool.complete"
  | "tool.generating"
  | "clarify.request"
  | "approval.request"
  | "sudo.request"
  | "secret.request"
  | "background.complete"
  | "btw.complete"
  | "error"
  | "skin.changed"
  | (string & {});

export interface GatewayEvent<P = unknown> {
  type: GatewayEventName;
  session_id?: string;
  payload?: P;
  seq?: number;
  ts?: number;
}

export type ConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "error";

interface Pending {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

const DEFAULT_REQUEST_TIMEOUT_MS = 120_000;

/** Wildcard listener key: subscribe to every event regardless of type. */
const ANY = "*";

export class GatewayClient {
  private ws: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private reqId = 0;
  private pending = new Map<string, Pending>();
  private listeners = new Map<string, Set<(ev: GatewayEvent) => void>>();
  private _state: ConnectionState = "idle";
  private stateListeners = new Set<(s: ConnectionState) => void>();

  get state(): ConnectionState {
    return this._state;
  }

  private setState(s: ConnectionState) {
    if (this._state === s) return;
    this._state = s;
    for (const cb of this.stateListeners) cb(s);
  }

  onState(cb: (s: ConnectionState) => void): () => void {
    this.stateListeners.add(cb);
    cb(this._state);
    return () => this.stateListeners.delete(cb);
  }

  /** Subscribe to a specific event type. Returns an unsubscribe function. */
  on<P = unknown>(
    type: GatewayEventName,
    cb: (ev: GatewayEvent<P>) => void,
  ): () => void {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(cb as (ev: GatewayEvent) => void);
    return () => set!.delete(cb as (ev: GatewayEvent) => void);
  }

  /** Subscribe to every event (fires after type-specific listeners). */
  onAny(cb: (ev: GatewayEvent) => void): () => void {
    return this.on(ANY as GatewayEventName, cb);
  }

  /**
   * Replay a batch of events through the same listener pipeline that
   * live websocket frames use. Used by session.resume to fan out the
   * server-side ring buffer when the client reattaches to a session
   * that kept running while the UI was looking at another chat.
   */
  replayEvents(events: GatewayEvent[]): void {
    for (const ev of events) {
      if (!ev || typeof ev.type !== "string") continue;
      for (const cb of this.listeners.get(ev.type) ?? []) cb(ev);
      for (const cb of this.listeners.get(ANY) ?? []) cb(ev);
    }
  }

  async connect(token?: string): Promise<void> {
    if (this._state === "open") return;
    if (this._state === "connecting" && this.connectPromise) {
      return this.connectPromise;
    }
    this.setState("connecting");

    const resolved = token ?? window.__ELEVATE_SESSION_TOKEN__ ?? "";
    if (!resolved) {
      this.setState("error");
      throw new Error(
        "Session token not available — page must be served by the Elevate dashboard",
      );
    }

    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${scheme}//${location.host}/api/ws?token=${encodeURIComponent(resolved)}`,
    );
    this.ws = ws;

    // Register message + close BEFORE awaiting open — the server emits
    // `gateway.ready` immediately after accept, so a listener attached
    // after the open promise resolves can race past it and drop the
    // initial skin payload.
    ws.addEventListener("message", (ev) => {
      try {
        this.dispatch(JSON.parse(ev.data));
      } catch {
        /* malformed frame — ignore */
      }
    });

    ws.addEventListener("close", () => {
      this.setState("closed");
      this.rejectAllPending(new Error("WebSocket closed"));
    });

    this.connectPromise = new Promise<void>((resolve, reject) => {
      const onOpen = () => {
        ws.removeEventListener("error", onError);
        this.connectPromise = null;
        this.setState("open");
        resolve();
      };
      const onError = () => {
        ws.removeEventListener("open", onOpen);
        this.connectPromise = null;
        this.setState("error");
        reject(new Error("WebSocket connection failed"));
      };
      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onError, { once: true });
    });
    return this.connectPromise;
  }

  close() {
    const ws = this.ws;
    this.ws = null;
    this.connectPromise = null;
    this.rejectAllPending(new Error("WebSocket closed"));
    this.setState("closed");
    if (ws && ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
      ws.close();
    }
  }

  private dispatch(msg: Record<string, unknown>) {
    const id = msg.id as string | undefined;

    if (id !== undefined && this.pending.has(id)) {
      const p = this.pending.get(id)!;
      this.pending.delete(id);
      clearTimeout(p.timer);

      const err = msg.error as { message?: string } | undefined;
      if (err) p.reject(new Error(err.message ?? "request failed"));
      else p.resolve(msg.result);
      return;
    }

    if (msg.method !== "event") return;

    const params = (msg.params ?? {}) as GatewayEvent;
    if (typeof params.type !== "string") return;

    for (const cb of this.listeners.get(params.type) ?? []) cb(params);
    for (const cb of this.listeners.get(ANY) ?? []) cb(params);
  }

  private rejectAllPending(err: Error) {
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    this.pending.clear();
  }

  /** Send a JSON-RPC request. Rejects on error response or timeout. */
  request<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  ): Promise<T> {
    if (!this.ws || this._state !== "open") {
      return Promise.reject(
        new Error(`gateway not connected (state=${this._state})`),
      );
    }

    const id = `w${++this.reqId}`;

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) {
          reject(new Error(`request timed out: ${method}`));
        }
      }, timeoutMs);

      this.pending.set(id, {
        resolve: (v) => resolve(v as T),
        reject,
        timer,
      });

      try {
        this.ws!.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
      } catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }
}

declare global {
  interface Window {
    __ELEVATE_SESSION_TOKEN__?: string;
  }
}

```

---
## `src/lib/slashExec.ts`
```ts
/**
 * Slash command execution pipeline for the web chat.
 *
 * Mirrors the Ink TUI's createSlashHandler.ts:
 *
 *   1. Parse the command into `name` + `arg`.
 *   2. Try `slash.exec` — covers every registry-backed command the terminal
 *      UI knows about (/help, /resume, /compact, /model, …). Output is
 *      rendered into the transcript.
 *   3. If `slash.exec` errors (command rejected, unknown, or needs client
 *      behaviour), fall back to `command.dispatch` which returns a typed
 *      directive: `exec` | `plugin` | `alias` | `skill` | `send`.
 *   4. Each directive is dispatched to the appropriate callback.
 *
 * Keeping the pipeline here (instead of inline in ChatPage) lets future
 * clients (SwiftUI, Android) implement the same logic by reading the same
 * contract.
 */

import type { GatewayClient } from "@/lib/gatewayClient";

export interface SlashExecResponse {
  output?: string;
  warning?: string;
}

export type CommandDispatchResponse =
  | { type: "exec" | "plugin"; output?: string }
  | { type: "alias"; target: string }
  | { type: "skill"; name: string; message?: string }
  | { type: "send"; message: string };

export interface SlashExecCallbacks {
  /** Render a transcript system message. */
  sys(text: string): void;
  /** Submit a user message to the agent (prompt.submit). */
  send(message: string): Promise<void> | void;
  /**
   * Submit a skill payload. The model receives the full SKILL.md `payload`,
   * but the client MUST keep it out of the visible transcript — the leading
   * `/command` bubble is the only thing the user should see. This is what
   * separates `send` (a visible user turn) from a skill load (bulk context
   * that loads quietly on the first slash command).
   */
  sendSkill(
    payload: string,
    commandName: string,
    args?: string,
  ): Promise<void> | void;
}

export interface SlashExecOptions {
  /** Raw command including the leading slash (e.g. "/model opus-4.6"). */
  command: string;
  /** Session id. If empty the call is still issued — some commands are session-less. */
  sessionId: string;
  gw: GatewayClient;
  callbacks: SlashExecCallbacks;
}

export type SlashExecResult = "done" | "sent" | "error";

/**
 * Run a slash command. Returns the terminal state so callers can decide
 * whether to clear the composer, queue retries, etc.
 */
export async function executeSlash({
  command,
  sessionId,
  gw,
  callbacks: { sys, send, sendSkill },
}: SlashExecOptions): Promise<SlashExecResult> {
  const { name, arg } = parseSlash(command);

  if (!name) {
    sys("empty slash command");
    return "error";
  }

  // Primary dispatcher.
  try {
    const r = await gw.request<SlashExecResponse>("slash.exec", {
      command: command.replace(/^\/+/, ""),
      session_id: sessionId,
    });
    const body = r?.output || `/${name}: no output`;
    sys(r?.warning ? `warning: ${r.warning}\n${body}` : body);
    return "done";
  } catch {
    /* fall through to command.dispatch */
  }

  try {
    const d = parseCommandDispatch(
      await gw.request<unknown>("command.dispatch", {
        name,
        arg,
        session_id: sessionId,
      }),
    );

    if (!d) {
      sys("error: invalid response: command.dispatch");
      return "error";
    }

    switch (d.type) {
      case "exec":
      case "plugin":
        sys(d.output ?? "(no output)");
        return "done";

      case "alias":
        return executeSlash({
          command: `/${d.target}${arg ? ` ${arg}` : ""}`,
          sessionId,
          gw,
          callbacks: { sys, send, sendSkill },
        });

      case "skill": {
        const msg = d.message?.trim() ?? "";
        if (!msg) {
          sys(`/${name}: skill payload missing message`);
          return "error";
        }
        // The model gets the full SKILL.md via sendSkill; the transcript
        // should only show the `/command` bubble the user already typed.
        await sendSkill(msg, d.name, arg);
        return "sent";
      }

      case "send": {
        const msg = d.message?.trim() ?? "";
        if (!msg) {
          sys(`/${name}: empty message`);
          return "error";
        }
        await send(msg);
        return "sent";
      }
    }
  } catch (err) {
    sys(`error: ${err instanceof Error ? err.message : String(err)}`);
    return "error";
  }
}

export function parseSlash(command: string): { name: string; arg: string } {
  const m = command.replace(/^\/+/, "").match(/^(\S+)\s*(.*)$/);
  return m ? { name: m[1], arg: m[2].trim() } : { name: "", arg: "" };
}

function parseCommandDispatch(raw: unknown): CommandDispatchResponse | null {
  if (!raw || typeof raw !== "object") return null;

  const r = raw as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);

  switch (r.type) {
    case "exec":
    case "plugin":
      return { type: r.type, output: str(r.output) };

    case "alias":
      return typeof r.target === "string"
        ? { type: "alias", target: r.target }
        : null;

    case "skill":
      return typeof r.name === "string"
        ? { type: "skill", name: r.name, message: str(r.message) }
        : null;

    case "send":
      return typeof r.message === "string"
        ? { type: "send", message: r.message }
        : null;

    default:
      return null;
  }
}

```

---
## `src/plugins/PluginPage.tsx`
```tsx
import { useSyncExternalStore } from "react";
import { Loader2 } from "lucide-react";
import {
  getPluginComponent,
  getPluginLoadError,
  onPluginRegistered,
} from "./registry";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Translations } from "@/i18n/types";

/** Renders a plugin tab once its bundle has called `register()`. */
export function PluginPage({ name }: { name: string }) {
  const { t } = useI18n();
  // Subscribe in render (via useSyncExternalStore) so we never miss
  // `register()` if the script loads before a useEffect would run.
  const Component = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginComponent(name) ?? null,
    () => null,
  );
  const loadError = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginLoadError(name) ?? null,
    () => null,
  );

  if (Component) {
    return <Component />;
  }

  if (loadError) {
    const message = formatPluginError(loadError, t);
    return (
      <div
        className={cn(
          "max-w-lg p-4",
          "font-mondwest text-sm tracking-[0.08em] text-midground/80",
        )}
        role="alert"
      >
        {message}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 p-4",
        "font-mondwest text-sm tracking-[0.1em] text-midground/60",
      )}
    >
      <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
      <span>{t.common.loading}</span>
    </div>
  );
}

function formatPluginError(code: string, t: Translations): string {
  if (code === "LOAD_FAILED") return t.common.pluginLoadFailed;
  if (code === "NO_REGISTER") return t.common.pluginNotRegistered;
  return code;
}

```

---
## `src/plugins/index.ts`
```ts
export { exposePluginSDK, getPluginComponent, onPluginRegistered, getRegisteredCount } from "./registry";
export { PluginPage } from "./PluginPage";
export { usePlugins } from "./usePlugins";
export { PluginSlot, KNOWN_SLOT_NAMES, registerSlot, getSlotEntries, onSlotRegistered, unregisterPluginSlots } from "./slots";
export type { KnownSlotName } from "./slots";
export type { PluginManifest, RegisteredPlugin } from "./types";

```

---
## `src/plugins/registry.ts`
```ts
/**
 * Dashboard Plugin SDK + Registry
 *
 * Exposes React, UI components, hooks, and utilities on the window so
 * that plugin bundles can use them without bundling their own copies.
 *
 * Plugins call window.__ELEVATE_PLUGINS__.register(name, Component)
 * to register their tab component.
 */

import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useContext,
  createContext,
} from "react";
import { api, fetchJSON } from "@/lib/api";
import { cn, timeAgo, isoTimeAgo } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/i18n";
import { registerSlot, PluginSlot } from "./slots";

// ---------------------------------------------------------------------------
// Plugin registry — plugins call register() to add their component.
// ---------------------------------------------------------------------------

type RegistryListener = () => void;

const _registered: Map<string, React.ComponentType> = new Map();
const _loadErrors: Map<string, string> = new Map();
const _listeners: Set<RegistryListener> = new Set();

function _notify() {
  for (const fn of _listeners) {
    try { fn(); } catch { /* ignore */ }
  }
}

/** Re-run registry subscribers (e.g. after a plugin script onload, or dev HMR re-inject). */
export function notifyPluginRegistry() {
  _notify();
}

/** Register a plugin component. Called by plugin JS bundles. */
function registerPlugin(name: string, component: React.ComponentType) {
  _loadErrors.delete(name);
  _registered.set(name, component);
  _notify();
}

/** Get a registered component by plugin name. */
export function getPluginComponent(name: string): React.ComponentType | undefined {
  return _registered.get(name);
}

export function getPluginLoadError(name: string): string | undefined {
  return _loadErrors.get(name);
}

export function setPluginLoadError(name: string, message: string) {
  _loadErrors.set(name, message);
  _notify();
}

/** Subscribe to registry changes (returns unsubscribe fn). */
export function onPluginRegistered(fn: RegistryListener): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

/** Get current count of registered plugins. */
export function getRegisteredCount(): number {
  return _registered.size;
}

// ---------------------------------------------------------------------------
// Expose SDK + registry on window
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    __ELEVATE_PLUGIN_SDK__: unknown;
    __ELEVATE_PLUGINS__: {
      register: typeof registerPlugin;
      registerSlot: typeof registerSlot;
    };
    // Legacy Hermes-era global names. Shipped plugin bundles
    // (example-dashboard, strike-freedom-cockpit) still read these; keep
    // them aliased to the Elevate globals until those bundles are rebuilt.
    __HERMES_PLUGIN_SDK__?: unknown;
    __HERMES_PLUGINS__?: {
      register: typeof registerPlugin;
      registerSlot: typeof registerSlot;
    };
  }
}

export function exposePluginSDK() {
  window.__ELEVATE_PLUGINS__ = {
    register: registerPlugin,
    registerSlot,
  };

  window.__ELEVATE_PLUGIN_SDK__ = {
    // React core — plugins use these instead of importing react
    React,
    hooks: {
      useState,
      useEffect,
      useCallback,
      useMemo,
      useRef,
      useContext,
      createContext,
    },

    // Elevate API client
    api,
    // Raw fetchJSON for plugin-specific endpoints
    fetchJSON,

    // UI components (shadcn/ui primitives)
    components: {
      Card,
      CardHeader,
      CardTitle,
      CardContent,
      Badge,
      Button,
      Input,
      Label,
      Select,
      SelectOption,
      Separator,
      Tabs,
      TabsList,
      TabsTrigger,
      PluginSlot,
    },

    // Utilities
    utils: { cn, timeAgo, isoTimeAgo },

    // Hooks
    useI18n,
  };

  // Backward-compat: shipped plugin bundles still destructure the legacy
  // Hermes globals. Without these aliases every route throws
  // "Cannot destructure property 'React' of 'SDK' as it is undefined"
  // and the plugin system (incl. the strike-freedom-cockpit slot) is dead.
  window.__HERMES_PLUGINS__ = window.__ELEVATE_PLUGINS__;
  window.__HERMES_PLUGIN_SDK__ = window.__ELEVATE_PLUGIN_SDK__;
}

```

---
## `src/plugins/slots.ts`
```ts
/**
 * Plugin slot registry.
 *
 * Plugins can inject components into named locations in the app shell
 * (header-left, sidebar, backdrop, etc.) by calling
 * `window.__ELEVATE_PLUGINS__.registerSlot(pluginName, slotName, Component)`
 * from their JS bundle. Multiple plugins can populate the same slot — they
 * render stacked in registration order.
 *
 * The canonical slot names are documented in `KNOWN_SLOT_NAMES` below. The
 * registry accepts any string so plugin ecosystems can define their own
 * slots; the shell only renders `<PluginSlot name="..." />` for the slots
 * it knows about.
 */

import React, { Fragment, useEffect, useState } from "react";

/** Slot locations the built-in shell renders. Plugins declaring any of
 *  these in their manifest's `slots` field get wired in automatically.
 *
 *  - `backdrop`         — rendered inside `<Backdrop />`, above the noise layer
 *  - `header-left`      — injected before the Elevate brand in the top bar
 *  - `header-right`     — injected before the theme/language switchers
 *  - `header-banner`    — injected below the top nav bar, full-width
 *  - `sidebar`          — the cockpit sidebar rail (only rendered when
 *                         `layoutVariant === "cockpit"`)
 *  - `pre-main`         — rendered above the route outlet (inside `<main>`)
 *  - `post-main`        — rendered below the route outlet (inside `<main>`)
 *  - `footer-left`      — replaces the left footer cell content
 *  - `footer-right`     — replaces the right footer cell content
 *  - `overlay`          — fixed-position layer above everything else;
 *                         useful for chrome (scanlines, vignettes) the
 *                         theme's customCSS can't achieve alone
 */
export const KNOWN_SLOT_NAMES = [
  "backdrop",
  "header-left",
  "header-right",
  "header-banner",
  "sidebar",
  "pre-main",
  "post-main",
  "footer-left",
  "footer-right",
  "overlay",
] as const;

export type KnownSlotName = (typeof KNOWN_SLOT_NAMES)[number];

type SlotListener = () => void;

interface SlotEntry {
  plugin: string;
  component: React.ComponentType;
}

/** Map<slotName, SlotEntry[]>. Entries are appended in registration order. */
const _slotRegistry: Map<string, SlotEntry[]> = new Map();
const _slotListeners: Set<SlotListener> = new Set();

function _notifySlots() {
  for (const fn of _slotListeners) {
    try {
      fn();
    } catch {
      /* ignore */
    }
  }
}

/** Register a component for a slot. Called by plugin bundles via
 *  `window.__ELEVATE_PLUGINS__.registerSlot(...)`.
 *
 *  If the same (plugin, slot) pair is registered twice, the later call
 *  replaces the earlier one — this matches how React HMR expects plugin
 *  re-mounts to behave. */
export function registerSlot(
  plugin: string,
  slot: string,
  component: React.ComponentType,
): void {
  const existing = _slotRegistry.get(slot) ?? [];
  const filtered = existing.filter((e) => e.plugin !== plugin);
  filtered.push({ plugin, component });
  _slotRegistry.set(slot, filtered);
  _notifySlots();
}

/** Read current entries for a slot. Returns a copy so callers can't mutate
 *  registry state. */
export function getSlotEntries(slot: string): SlotEntry[] {
  return (_slotRegistry.get(slot) ?? []).slice();
}

/** Subscribe to registry changes. Returns an unsubscribe function. */
export function onSlotRegistered(fn: SlotListener): () => void {
  _slotListeners.add(fn);
  return () => {
    _slotListeners.delete(fn);
  };
}

/** Clear a specific plugin's slot registrations. Useful for HMR /
 *  plugin reload flows — not wired in by default. */
export function unregisterPluginSlots(plugin: string): void {
  let changed = false;
  for (const [slot, entries] of _slotRegistry.entries()) {
    const kept = entries.filter((e) => e.plugin !== plugin);
    if (kept.length !== entries.length) {
      changed = true;
      if (kept.length === 0) _slotRegistry.delete(slot);
      else _slotRegistry.set(slot, kept);
    }
  }
  if (changed) _notifySlots();
}

interface PluginSlotProps {
  /** Slot identifier (e.g. `"sidebar"`, `"header-left"`). */
  name: string;
  /** Optional content rendered when no plugins have claimed the slot.
   *  Useful for built-in defaults the plugin would replace. */
  fallback?: React.ReactNode;
}

/** Render all components registered for a given slot, stacked in order.
 *
 *  Component re-renders when the slot registry changes so plugins that
 *  arrive after initial mount show up without a manual refresh. */
export function PluginSlot({ name, fallback }: PluginSlotProps) {
  const [entries, setEntries] = useState<SlotEntry[]>(() => getSlotEntries(name));

  useEffect(() => {
    // Pick up anything registered between the initial `useState` call
    // and the first effect tick, then subscribe for future changes.
    setEntries(getSlotEntries(name));
    const unsub = onSlotRegistered(() => setEntries(getSlotEntries(name)));
    return unsub;
  }, [name]);

  if (entries.length === 0) {
    return fallback ? React.createElement(Fragment, null, fallback) : null;
  }

  return React.createElement(
    Fragment,
    null,
    ...entries.map((entry) =>
      React.createElement(entry.component, { key: entry.plugin }),
    ),
  );
}

```

---
## `src/plugins/types.ts`
```ts
/** Types for the dashboard plugin system. */

import type { ComponentType } from "react";

export interface PluginManifest {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    /** "end", "after:<pathSegment>", "before:<pathSegment>" (e.g. "after:skills" → after `/skills`) */
    position?: string;
    /** When set to a built-in route path, this plugin replaces that page instead of adding a new tab. */
    override?: string;
    /** When true, the plugin may register without a sidebar tab (slot-only, etc.). */
    hidden?: boolean;
  };
  /** Declared for discovery; actual slots use registerSlot in the plugin bundle. */
  slots?: string[];
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}

export interface RegisteredPlugin {
  manifest: PluginManifest;
  component: ComponentType;
}

```

---
## `src/plugins/usePlugins.ts`
```ts
/**
 * usePlugins hook — discovers and loads dashboard plugins.
 *
 * 1. Fetches plugin manifests from GET /api/dashboard/plugins
 * 2. Injects CSS <link> tags for plugins that declare css
 * 3. Loads plugin JS bundles via <script> tags
 * 4. Waits for plugins to call register() and resolves them
 */

import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import type { PluginManifest, RegisteredPlugin } from "./types";
import {
  getPluginComponent,
  onPluginRegistered,
  notifyPluginRegistry,
  setPluginLoadError,
} from "./registry";

export function usePlugins() {
  const [manifests, setManifests] = useState<PluginManifest[]>([]);
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const loadedScripts = useRef<Set<string>>(new Set());

  // Fetch manifests on mount.
  useEffect(() => {
    api
      .getPlugins()
      .then((list) => {
        setManifests(list);
        if (list.length === 0) setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // Load plugin assets when manifests arrive.
  useEffect(() => {
    if (manifests.length === 0) return;

    const injectedScripts: HTMLScriptElement[] = [];

    for (const manifest of manifests) {
      // Inject CSS if specified.
      if (manifest.css) {
        const cssUrl = `/dashboard-plugins/${manifest.name}/${manifest.css}`;
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = cssUrl;
          document.head.appendChild(link);
        }
      }

      // Load JS bundle. In dev, cache-bust so Vite HMR can clear the
      // in-memory registry while the browser would otherwise never
      // re-execute a previously cached <script> URL.
      const baseUrl = `/dashboard-plugins/${manifest.name}/${manifest.entry}`;
      const scriptSrc = import.meta.env.DEV
        ? `${baseUrl}?elevate_dv=${Date.now()}`
        : baseUrl;
      if (!import.meta.env.DEV) {
        if (loadedScripts.current.has(baseUrl)) continue;
        loadedScripts.current.add(baseUrl);
      }

      const script = document.createElement("script");
      script.setAttribute("data-elevate-plugin", manifest.name);
      script.src = scriptSrc;
      script.async = true;
      script.onerror = () => {
        setPluginLoadError(manifest.name, "LOAD_FAILED");
        console.warn(
          `[plugins] Failed to load ${manifest.name} from ${scriptSrc} (open Network tab)`,
        );
      };
      script.onload = () => {
        notifyPluginRegistry();
        queueMicrotask(() => {
          if (getPluginComponent(manifest.name)) return;
          setPluginLoadError(manifest.name, "NO_REGISTER");
        });
      };
      document.body.appendChild(script);
      injectedScripts.push(script);
    }

    // Give plugins a moment to load and register, then stop loading state.
    const timeout = setTimeout(() => setLoading(false), 2000);
    return () => {
      clearTimeout(timeout);
      if (import.meta.env.DEV) {
        for (const el of injectedScripts) {
          el.remove();
        }
      }
    };
  }, [manifests]);

  // Listen for plugin registrations and resolve them against manifests.
  useEffect(() => {
    function resolvePlugins() {
      const resolved: RegisteredPlugin[] = [];
      for (const manifest of manifests) {
        const component = getPluginComponent(manifest.name);
        if (component) {
          resolved.push({ manifest, component });
        }
      }
      setPlugins(resolved);
      // If all plugins registered, stop loading early.
      if (resolved.length === manifests.length && manifests.length > 0) {
        setLoading(false);
      }
    }

    resolvePlugins();
    const unsub = onPluginRegistered(resolvePlugins);
    return unsub;
  }, [manifests]);

  return { plugins, manifests, loading };
}

```

---
## `src/i18n/context.tsx`
```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import type { Locale, Translations } from "./types";
import { en } from "./en";
import { zh } from "./zh";

const TRANSLATIONS: Record<Locale, Translations> = { en, zh };
const STORAGE_KEY = "elevate-locale";

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "zh") return stored;
  } catch {
    // SSR or privacy mode
  }
  return "en";
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: Translations;
}

const I18nContext = createContext<I18nContextValue>({
  locale: "en",
  setLocale: () => {},
  t: en,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const value: I18nContextValue = {
    locale,
    setLocale,
    t: TRANSLATIONS[locale],
  };

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

```

---
## `src/i18n/en.ts`
```ts
import type { Translations } from "./types";

export const en: Translations = {
  common: {
    save: "Save",
    saving: "Saving...",
    cancel: "Cancel",
    close: "Close",
    confirm: "Confirm",
    delete: "Delete",
    refresh: "Refresh",
    retry: "Retry",
    search: "Search...",
    loading: "Loading...",
    create: "Create",
    creating: "Creating...",
    set: "Set",
    replace: "Replace",
    clear: "Clear",
    live: "Live",
    off: "Off",
    enabled: "enabled",
    disabled: "disabled",
    active: "active",
    inactive: "inactive",
    unknown: "unknown",
    untitled: "Untitled",
    none: "None",
    form: "Form",
    noResults: "No results",
    of: "of",
    page: "Page",
    msgs: "msgs",
    tools: "tools",
    match: "match",
    other: "Other",
    configured: "configured",
    removed: "removed",
    failedToToggle: "Failed to toggle",
    failedToRemove: "Failed to remove",
    failedToReveal: "Failed to reveal",
    collapse: "Collapse",
    expand: "Expand",
    general: "General",
    messaging: "Messaging",
    pluginLoadFailed:
      "Could not load this plugin’s script. Check the Network tab (dashboard-plugins/…) and the server’s plugin path.",
    pluginNotRegistered:
      "The plugin’s script did not call register(), or the script errored. Open the browser console for details.",
  },

  app: {
    brand: "Elevate",
    brandShort: "HA",
    closeNavigation: "Close navigation",
    closeModelTools: "Close model and tools",
    footer: {
      org: "Elevation Real Estate HQ",
    },
    activeSessionsLabel: "Active Sessions:",
    gatewayStatusLabel: "Gateway Status:",
    gatewayStrip: {
      failed: "Start failed",
      off: "Off",
      running: "Running",
      starting: "Starting",
      stopped: "Stopped",
    },
    nav: {
      analytics: "Analytics",
      chat: "Chat",
      config: "Config",
      cron: "Cron",
      documentation: "Documentation",
      keys: "Keys",
      logs: "Logs",
      project: "Project",
      sessions: "Sessions",
      skills: "Skills",
    },
    modelToolsSheetSubtitle: "& tools",
    modelToolsSheetTitle: "Model",
    navigation: "Navigation",
    openDocumentation: "Open documentation in a new tab",
    openNavigation: "Open navigation",
    sessionsActiveCount: "{count} active",
    statusOverview: "Status overview",
    system: "System",
    webUi: "Web UI",
  },

  status: {
    actionFailed: "Action failed",
    actionFinished: "Finished",
    actions: "Actions",
    agent: "Agent",
    activeSessions: "Active Sessions",
    connected: "Connected",
    connectedPlatforms: "Connected Platforms",
    disconnected: "Disconnected",
    error: "Error",
    failed: "Failed",
    gateway: "Gateway",
    gatewayFailedToStart: "Gateway failed to start",
    lastUpdate: "Last update",
    noneRunning: "None",
    notRunning: "Not running",
    pid: "PID",
    platformDisconnected: "disconnected",
    platformError: "error",
    recentSessions: "Recent Sessions",
    restartGateway: "Restart Gateway",
    restartingGateway: "Restarting gateway…",
    running: "Running",
    runningRemote: "Running (remote)",
    startFailed: "Start failed",
    starting: "Starting",
    startedInBackground: "Started in background — check logs for progress",
    stopped: "Stopped",
    updateElevate: "Update Elevate",
    updatesAvailable: "Updates available",
    updatingElevate: "Updating Elevate…",
    waitingForOutput: "Waiting for output…",
  },

  sessions: {
    title: "Sessions",
    searchPlaceholder: "Search message content...",
    noSessions: "No sessions yet",
    noMatch: "No sessions match your search",
    startConversation: "Start a conversation to see it here",
    noMessages: "No messages",
    untitledSession: "Untitled session",
    deleteSession: "Delete session",
    confirmDeleteTitle: "Delete session?",
    confirmDeleteMessage:
      "This permanently removes the conversation and all of its messages. This cannot be undone.",
    sessionDeleted: "Session deleted",
    failedToDelete: "Failed to delete session",
    resumeInChat: "Resume in Chat",
    previousPage: "Previous page",
    nextPage: "Next page",
    roles: {
      user: "User",
      assistant: "Assistant",
      system: "System",
      tool: "Tool",
    },
  },

  analytics: {
    period: "Period:",
    totalTokens: "Total Tokens",
    totalSessions: "Total Sessions",
    apiCalls: "API Calls",
    dailyTokenUsage: "Daily Token Usage",
    dailyBreakdown: "Daily Breakdown",
    perModelBreakdown: "Per-Model Breakdown",
    topSkills: "Top Skills",
    skill: "Skill",
    loads: "Agent Loaded",
    edits: "Agent Managed",
    lastUsed: "Last Used",
    input: "Input",
    output: "Output",
    total: "Total",
    noUsageData: "No usage data for this period",
    startSession: "Start a session to see analytics here",
    date: "Date",
    model: "Model",
    tokens: "Tokens",
    perDayAvg: "/day avg",
    acrossModels: "across {count} models",
    inOut: "{input} in / {output} out",
  },

  logs: {
    title: "Logs",
    autoRefresh: "Auto-refresh",
    file: "File",
    level: "Level",
    component: "Component",
    lines: "Lines",
    noLogLines: "No log lines found",
  },

  cron: {
    confirmDeleteMessage:
      "This removes the job from the schedule. This cannot be undone.",
    confirmDeleteTitle: "Delete scheduled job?",
    newJob: "New Cron Job",
    nameOptional: "Name (optional)",
    namePlaceholder: "e.g. Daily summary",
    prompt: "Prompt",
    promptPlaceholder: "What should the agent do on each run?",
    schedule: "Schedule",
    schedulePlaceholder: "Custom cron expression",
    deliverTo: "Deliver to",
    scheduledJobs: "Scheduled Jobs",
    noJobs: "No cron jobs configured. Create one above.",
    last: "Last",
    next: "Next",
    pause: "Pause",
    resume: "Resume",
    triggerNow: "Trigger now",
    delivery: {
      local: "Local",
      telegram: "Telegram",
      discord: "Discord",
      slack: "Slack",
      email: "Email",
    },
  },

  skills: {
    title: "Skills",
    searchPlaceholder: "Search skills and toolsets...",
    enabledOf: "{enabled}/{total} enabled",
    all: "All",
    categories: "Categories",
    filters: "Filters",
    noSkills: "No skills found. Skills are loaded from ~/.elevate/skills/",
    noSkillsMatch: "No skills match your search or filter.",
    skillCount: "{count} skill{s}",
    resultCount: "{count} result{s}",
    noDescription: "No description available.",
    toolsets: "Toolsets",
    toolsetLabel: "{name} toolset",
    noToolsetsMatch: "No toolsets match the search.",
    setupNeeded: "Setup needed",
    disabledForCli: "Disabled for CLI",
    more: "+{count} more",
  },

  config: {
    configPath: "~/.elevate/config.yaml",
    filters: "Filters",
    sections: "Sections",
    exportConfig: "Export config as JSON",
    importConfig: "Import config from JSON",
    resetDefaults: "Reset to defaults",
    rawYaml: "Raw YAML Configuration",
    searchResults: "Search Results",
    fields: "field{s}",
    noFieldsMatch: 'No fields match "{query}"',
    configSaved: "Configuration saved",
    yamlConfigSaved: "YAML config saved",
    failedToSave: "Failed to save",
    failedToSaveYaml: "Failed to save YAML",
    failedToLoadRaw: "Failed to load raw config",
    configImported: "Config imported — review and save",
    invalidJson: "Invalid JSON file",
    categories: {
      general: "General",
      agent: "Agent",
      agent_hub: "Agent Hub",
      platforms: "Platforms",
      terminal: "Terminal",
      display: "Display",
      delegation: "Delegation",
      memory: "Memory",
      access: "Access",
      plugins: "Plugins",
      compression: "Compression",
      security: "Security",
      browser: "Browser",
      voice: "Voice",
      tts: "Text-to-Speech",
      stt: "Speech-to-Text",
      logging: "Logging",
      discord: "Discord",
      auxiliary: "Auxiliary",
    },
  },

  env: {
    changesNote: "Changes are saved to disk immediately. Active sessions pick up new keys automatically.",
    confirmClearMessage:
      "The stored value for this variable will be removed from your .env file. This cannot be undone from the UI.",
    confirmClearTitle: "Clear this key?",
    description: "Manage API keys and secrets stored in",
    hideAdvanced: "Hide Advanced",
    showAdvanced: "Show Advanced",
    llmProviders: "LLM Providers",
    providersConfigured: "{configured} of {total} providers configured",
    getKey: "Get key",
    notConfigured: "{count} not configured",
    notSet: "Not set",
    keysCount: "{count} key{s}",
    enterValue: "Enter value...",
    replaceCurrentValue: "Replace current value ({preview})",
    showValue: "Show real value",
    hideValue: "Hide value",
  },

  oauth: {
    title: "Provider Logins (OAuth)",
    providerLogins: "Provider Logins (OAuth)",
    description: "{connected} of {total} OAuth providers connected. Login flows currently run via the CLI; click Copy command and paste into a terminal to set up.",
    connected: "Connected",
    expired: "Expired",
    notConnected: "Not connected. Run {command} in a terminal.",
    runInTerminal: "in a terminal.",
    noProviders: "No OAuth-capable providers detected.",
    login: "Login",
    disconnect: "Disconnect",
    managedExternally: "Managed externally",
    copied: "Copied ✓",
    cli: "CLI",
    copyCliCommand: "Copy CLI command (for external / fallback)",
    connect: "Connect",
    sessionExpires: "Session expires in {time}",
    initiatingLogin: "Initiating login flow…",
    exchangingCode: "Exchanging code for tokens…",
    connectedClosing: "Connected! Closing…",
    loginFailed: "Login failed.",
    sessionExpired: "Session expired. Click Retry to start a new login.",
    reOpenAuth: "Re-open auth page",
    reOpenVerification: "Re-open verification page",
    submitCode: "Submit code",
    pasteCode: "Paste authorization code (with #state suffix is fine)",
    waitingAuth: "Waiting for you to authorize in the browser…",
    enterCodePrompt: "A new tab opened. Enter this code if prompted:",
    pkceStep1: "A new tab opened to claude.ai. Sign in and click Authorize.",
    pkceStep2: "Copy the authorization code shown after authorizing.",
    pkceStep3: "Paste it below and submit.",
    flowLabels: {
      pkce: "Browser login (PKCE)",
      device_code: "Device code",
      external: "External CLI",
    },
    expiresIn: "expires in {time}",
  },

  language: {
    switchTo: "Switch to Chinese",
  },

  theme: {
    title: "Theme",
    switchTheme: "Switch theme",
  },
};

```

---
## `src/i18n/index.ts`
```ts
export { I18nProvider, useI18n } from "./context";
export type { Locale, Translations } from "./types";

```

---
## `src/i18n/types.ts`
```ts
export type Locale = "en" | "zh";

export interface Translations {
  // ── Common ──
  common: {
    save: string;
    saving: string;
    cancel: string;
    close: string;
    confirm: string;
    delete: string;
    refresh: string;
    retry: string;
    search: string;
    loading: string;
    create: string;
    creating: string;
    set: string;
    replace: string;
    clear: string;
    live: string;
    off: string;
    enabled: string;
    disabled: string;
    active: string;
    inactive: string;
    unknown: string;
    untitled: string;
    none: string;
    form: string;
    noResults: string;
    of: string;
    page: string;
    msgs: string;
    tools: string;
    match: string;
    other: string;
    configured: string;
    removed: string;
    failedToToggle: string;
    failedToRemove: string;
    failedToReveal: string;
    collapse: string;
    expand: string;
    general: string;
    messaging: string;
    pluginLoadFailed: string;
    pluginNotRegistered: string;
  };

  // ── App shell ──
  app: {
    brand: string;
    brandShort: string;
    closeNavigation: string;
    closeModelTools: string;
    footer: {
      org: string;
    };
    activeSessionsLabel: string;
    gatewayStatusLabel: string;
    gatewayStrip: {
      failed: string;
      off: string;
      running: string;
      starting: string;
      stopped: string;
    };
    nav: {
      analytics: string;
      chat: string;
      config: string;
      cron: string;
      documentation: string;
      keys: string;
      logs: string;
      project: string;
      sessions: string;
      skills: string;
    };
    modelToolsSheetSubtitle: string;
    modelToolsSheetTitle: string;
    navigation: string;
    openDocumentation: string;
    openNavigation: string;
    sessionsActiveCount: string;
    statusOverview: string;
    system: string;
    webUi: string;
  };

  // ── Status page ──
  status: {
    actionFailed: string;
    actionFinished: string;
    actions: string;
    agent: string;
    connected: string;
    connectedPlatforms: string;
    disconnected: string;
    error: string;
    failed: string;
    gateway: string;
    gatewayFailedToStart: string;
    lastUpdate: string;
    noneRunning: string;
    notRunning: string;
    pid: string;
    platformDisconnected: string;
    platformError: string;
    activeSessions: string;
    recentSessions: string;
    restartGateway: string;
    restartingGateway: string;
    running: string;
    runningRemote: string;
    startFailed: string;
    starting: string;
    startedInBackground: string;
    stopped: string;
    updateElevate: string;
    updatesAvailable: string;
    updatingElevate: string;
    waitingForOutput: string;
  };

  // ── Sessions page ──
  sessions: {
    title: string;
    searchPlaceholder: string;
    noSessions: string;
    noMatch: string;
    startConversation: string;
    noMessages: string;
    untitledSession: string;
    deleteSession: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    sessionDeleted: string;
    failedToDelete: string;
    resumeInChat: string;
    previousPage: string;
    nextPage: string;
    roles: {
      user: string;
      assistant: string;
      system: string;
      tool: string;
    };
  };

  // ── Analytics page ──
  analytics: {
    period: string;
    totalTokens: string;
    totalSessions: string;
    apiCalls: string;
    dailyTokenUsage: string;
    dailyBreakdown: string;
    perModelBreakdown: string;
    topSkills: string;
    skill: string;
    loads: string;
    edits: string;
    lastUsed: string;
    input: string;
    output: string;
    total: string;
    noUsageData: string;
    startSession: string;
    date: string;
    model: string;
    tokens: string;
    perDayAvg: string;
    acrossModels: string;
    inOut: string;
  };

  // ── Logs page ──
  logs: {
    title: string;
    autoRefresh: string;
    file: string;
    level: string;
    component: string;
    lines: string;
    noLogLines: string;
  };

  // ── Cron page ──
  cron: {
    confirmDeleteMessage: string;
    confirmDeleteTitle: string;
    newJob: string;
    nameOptional: string;
    namePlaceholder: string;
    prompt: string;
    promptPlaceholder: string;
    schedule: string;
    schedulePlaceholder: string;
    deliverTo: string;
    scheduledJobs: string;
    noJobs: string;
    last: string;
    next: string;
    pause: string;
    resume: string;
    triggerNow: string;
    delivery: {
      local: string;
      telegram: string;
      discord: string;
      slack: string;
      email: string;
    };
  };

  // ── Skills page ──
  skills: {
    title: string;
    searchPlaceholder: string;
    enabledOf: string;
    all: string;
    categories: string;
    filters: string;
    noSkills: string;
    noSkillsMatch: string;
    skillCount: string;
    resultCount: string;
    noDescription: string;
    toolsets: string;
    toolsetLabel: string;
    noToolsetsMatch: string;
    setupNeeded: string;
    disabledForCli: string;
    more: string;
  };

  // ── Config page ──
  config: {
    configPath: string;
    filters: string;
    sections: string;
    exportConfig: string;
    importConfig: string;
    resetDefaults: string;
    rawYaml: string;
    searchResults: string;
    fields: string;
    noFieldsMatch: string;
    configSaved: string;
    yamlConfigSaved: string;
    failedToSave: string;
    failedToSaveYaml: string;
    failedToLoadRaw: string;
    configImported: string;
    invalidJson: string;
    categories: {
      general: string;
      agent: string;
      agent_hub: string;
      platforms: string;
      terminal: string;
      display: string;
      delegation: string;
      memory: string;
      access: string;
      plugins: string;
      compression: string;
      security: string;
      browser: string;
      voice: string;
      tts: string;
      stt: string;
      logging: string;
      discord: string;
      auxiliary: string;
    };
  };

  // ── Env / Keys page ──
  env: {
    changesNote: string;
    confirmClearMessage: string;
    confirmClearTitle: string;
    description: string;
    enterValue: string;
    getKey: string;
    hideAdvanced: string;
    hideValue: string;
    keysCount: string;
    llmProviders: string;
    notConfigured: string;
    notSet: string;
    providersConfigured: string;
    replaceCurrentValue: string;
    showAdvanced: string;
    showValue: string;
  };

  // ── OAuth ──
  oauth: {
    title: string;
    providerLogins: string;
    description: string;
    connected: string;
    expired: string;
    notConnected: string;
    runInTerminal: string;
    noProviders: string;
    login: string;
    disconnect: string;
    managedExternally: string;
    copied: string;
    cli: string;
    copyCliCommand: string;
    connect: string;
    sessionExpires: string;
    initiatingLogin: string;
    exchangingCode: string;
    connectedClosing: string;
    loginFailed: string;
    sessionExpired: string;
    reOpenAuth: string;
    reOpenVerification: string;
    submitCode: string;
    pasteCode: string;
    waitingAuth: string;
    enterCodePrompt: string;
    pkceStep1: string;
    pkceStep2: string;
    pkceStep3: string;
    flowLabels: {
      pkce: string;
      device_code: string;
      external: string;
    };
    expiresIn: string;
  };

  // ── Language switcher ──
  language: {
    switchTo: string;
  };

  // ── Theme switcher ──
  theme: {
    title: string;
    switchTheme: string;
  };
}

```

---
## `src/i18n/zh.ts`
```ts
import type { Translations } from "./types";

export const zh: Translations = {
  common: {
    save: "保存",
    saving: "保存中...",
    cancel: "取消",
    close: "关闭",
    confirm: "确认",
    delete: "删除",
    refresh: "刷新",
    retry: "重试",
    search: "搜索...",
    loading: "加载中...",
    create: "创建",
    creating: "创建中...",
    set: "设置",
    replace: "替换",
    clear: "清除",
    live: "在线",
    off: "离线",
    enabled: "已启用",
    disabled: "已禁用",
    active: "活跃",
    inactive: "未激活",
    unknown: "未知",
    untitled: "无标题",
    none: "无",
    form: "表单",
    noResults: "无结果",
    of: "/",
    page: "页",
    msgs: "消息",
    tools: "工具",
    match: "匹配",
    other: "其他",
    configured: "已配置",
    removed: "已移除",
    failedToToggle: "切换失败",
    failedToRemove: "移除失败",
    failedToReveal: "显示失败",
    collapse: "折叠",
    expand: "展开",
    general: "通用",
    messaging: "消息平台",
    pluginLoadFailed:
      "无法加载此插件的脚本。请检查网络请求（dashboard-plugins/…）以及服务器上的插件路径。",
    pluginNotRegistered: "插件脚本未调用 register()，或执行出错。请打开浏览器控制台查看详情。",
  },

  app: {
    brand: "Elevate",
    brandShort: "HA",
    closeNavigation: "关闭导航",
    closeModelTools: "关闭模型与工具",
    footer: {
      org: "Elevation Real Estate HQ",
    },
    activeSessionsLabel: "活跃会话：",
    gatewayStatusLabel: "网关状态：",
    gatewayStrip: {
      failed: "启动失败",
      off: "关闭",
      running: "运行中",
      starting: "启动中",
      stopped: "已停止",
    },
    nav: {
      analytics: "分析",
      chat: "对话",
      config: "配置",
      cron: "定时任务",
      documentation: "文档",
      keys: "密钥",
      logs: "日志",
      project: "项目",
      sessions: "会话",
      skills: "技能",
    },
    modelToolsSheetSubtitle: "与工具",
    modelToolsSheetTitle: "模型",
    navigation: "导航",
    openDocumentation: "在新标签页中打开文档",
    openNavigation: "打开导航",
    sessionsActiveCount: "{count} 个活跃",
    statusOverview: "状态概览",
    system: "系统",
    webUi: "管理面板",
  },

  status: {
    actionFailed: "操作失败",
    actionFinished: "已完成",
    actions: "操作",
    agent: "代理",
    activeSessions: "活跃会话",
    connected: "已连接",
    connectedPlatforms: "已连接平台",
    disconnected: "已断开",
    error: "错误",
    failed: "失败",
    gateway: "网关",
    gatewayFailedToStart: "网关启动失败",
    lastUpdate: "最后更新",
    noneRunning: "无",
    notRunning: "未运行",
    pid: "进程",
    platformDisconnected: "已断开",
    platformError: "错误",
    recentSessions: "最近会话",
    restartGateway: "重启网关",
    restartingGateway: "正在重启网关…",
    running: "运行中",
    runningRemote: "运行中（远程）",
    startFailed: "启动失败",
    starting: "启动中",
    startedInBackground: "已在后台启动 — 请查看日志",
    stopped: "已停止",
    updateElevate: "更新 Elevate",
    updatesAvailable: "有可用更新",
    updatingElevate: "正在更新 Elevate…",
    waitingForOutput: "等待输出…",
  },

  sessions: {
    title: "会话",
    searchPlaceholder: "搜索消息内容...",
    noSessions: "暂无会话",
    noMatch: "没有匹配的会话",
    startConversation: "开始对话后将显示在此处",
    noMessages: "暂无消息",
    untitledSession: "无标题会话",
    deleteSession: "删除会话",
    confirmDeleteTitle: "删除会话？",
    confirmDeleteMessage: "此操作将永久删除对话及其所有消息，无法恢复。",
    sessionDeleted: "会话已删除",
    failedToDelete: "删除会话失败",
    resumeInChat: "在对话中继续",
    previousPage: "上一页",
    nextPage: "下一页",
    roles: {
      user: "用户",
      assistant: "助手",
      system: "系统",
      tool: "工具",
    },
  },

  analytics: {
    period: "时间范围：",
    totalTokens: "总 Token 数",
    totalSessions: "总会话数",
    apiCalls: "API 调用",
    dailyTokenUsage: "每日 Token 用量",
    dailyBreakdown: "每日明细",
    perModelBreakdown: "模型用量明细",
    topSkills: "常用技能",
    skill: "技能",
    loads: "代理加载",
    edits: "代理管理",
    lastUsed: "最近使用",
    input: "输入",
    output: "输出",
    total: "总计",
    noUsageData: "该时间段暂无使用数据",
    startSession: "开始会话后将在此显示分析数据",
    date: "日期",
    model: "模型",
    tokens: "Token",
    perDayAvg: "/天 平均",
    acrossModels: "共 {count} 个模型",
    inOut: "输入 {input} / 输出 {output}",
  },

  logs: {
    title: "日志",
    autoRefresh: "自动刷新",
    file: "文件",
    level: "级别",
    component: "组件",
    lines: "行数",
    noLogLines: "未找到日志记录",
  },

  cron: {
    confirmDeleteMessage: "将从此计划移除该任务，此操作无法撤销。",
    confirmDeleteTitle: "删除定时任务？",
    newJob: "新建定时任务",
    nameOptional: "名称（可选）",
    namePlaceholder: "例如：每日总结",
    prompt: "提示词",
    promptPlaceholder: "代理每次运行时应执行什么操作？",
    schedule: "调度",
    schedulePlaceholder: "自定义 cron 表达式",
    deliverTo: "投递至",
    scheduledJobs: "已调度任务",
    noJobs: "暂无定时任务。在上方创建一个。",
    last: "上次",
    next: "下次",
    pause: "暂停",
    resume: "恢复",
    triggerNow: "立即触发",
    delivery: {
      local: "本地",
      telegram: "Telegram",
      discord: "Discord",
      slack: "Slack",
      email: "邮件",
    },
  },

  skills: {
    title: "技能",
    searchPlaceholder: "搜索技能和工具集...",
    enabledOf: "已启用 {enabled}/{total}",
    all: "全部",
    categories: "分类",
    filters: "筛选",
    noSkills: "未找到技能。技能从 ~/.elevate/skills/ 加载",
    noSkillsMatch: "没有匹配的技能。",
    skillCount: "{count} 个技能",
    resultCount: "{count} 个结果",
    noDescription: "暂无描述。",
    toolsets: "工具集",
    toolsetLabel: "{name} 工具集",
    noToolsetsMatch: "没有匹配的工具集。",
    setupNeeded: "需要配置",
    disabledForCli: "CLI 已禁用",
    more: "还有 {count} 个",
  },

  config: {
    configPath: "~/.elevate/config.yaml",
    filters: "筛选",
    sections: "分类",
    exportConfig: "导出配置为 JSON",
    importConfig: "从 JSON 导入配置",
    resetDefaults: "恢复默认值",
    rawYaml: "原始 YAML 配置",
    searchResults: "搜索结果",
    fields: "个字段",
    noFieldsMatch: '没有匹配"{query}"的字段',
    configSaved: "配置已保存",
    yamlConfigSaved: "YAML 配置已保存",
    failedToSave: "保存失败",
    failedToSaveYaml: "YAML 保存失败",
    failedToLoadRaw: "加载原始配置失败",
    configImported: "配置已导入 — 请检查后保存",
    invalidJson: "无效的 JSON 文件",
    categories: {
      general: "通用",
      agent: "代理",
      agent_hub: "代理中心",
      platforms: "平台",
      terminal: "终端",
      display: "显示",
      delegation: "委托",
      memory: "记忆",
      access: "访问",
      plugins: "插件",
      compression: "压缩",
      security: "安全",
      browser: "浏览器",
      voice: "语音",
      tts: "文字转语音",
      stt: "语音转文字",
      logging: "日志",
      discord: "Discord",
      auxiliary: "辅助",
    },
  },

  env: {
    changesNote: "更改会立即保存到磁盘。活跃会话将自动获取新密钥。",
    confirmClearMessage: "该变量的已存值将从 .env 文件中删除。无法在此界面撤销。",
    confirmClearTitle: "清除此密钥？",
    description: "管理存储在以下位置的 API 密钥和凭据",
    hideAdvanced: "隐藏高级选项",
    showAdvanced: "显示高级选项",
    llmProviders: "LLM 提供商",
    providersConfigured: "已配置 {configured}/{total} 个提供商",
    getKey: "获取密钥",
    notConfigured: "{count} 个未配置",
    notSet: "未设置",
    keysCount: "{count} 个密钥",
    enterValue: "输入值...",
    replaceCurrentValue: "替换当前值（{preview}）",
    showValue: "显示实际值",
    hideValue: "隐藏值",
  },

  oauth: {
    title: "提供商登录（OAuth）",
    providerLogins: "提供商登录（OAuth）",
    description: "已连接 {connected}/{total} 个 OAuth 提供商。登录流程目前通过 CLI 运行；点击「复制命令」并粘贴到终端中进行设置。",
    connected: "已连接",
    expired: "已过期",
    notConnected: "未连接。在终端中运行 {command}。",
    runInTerminal: "在终端中。",
    noProviders: "未检测到支持 OAuth 的提供商。",
    login: "登录",
    disconnect: "断开连接",
    managedExternally: "外部管理",
    copied: "已复制 ✓",
    cli: "CLI",
    copyCliCommand: "复制 CLI 命令（用于外部/备用方式）",
    connect: "连接",
    sessionExpires: "会话将在 {time} 后过期",
    initiatingLogin: "正在启动登录流程…",
    exchangingCode: "正在交换令牌…",
    connectedClosing: "已连接！正在关闭…",
    loginFailed: "登录失败。",
    sessionExpired: "会话已过期。点击重试以开始新的登录。",
    reOpenAuth: "重新打开授权页面",
    reOpenVerification: "重新打开验证页面",
    submitCode: "提交代码",
    pasteCode: "粘贴授权代码（包含 #state 后缀也可以）",
    waitingAuth: "等待您在浏览器中授权…",
    enterCodePrompt: "已在新标签页中打开。如果需要，请输入以下代码：",
    pkceStep1: "已在新标签页打开 claude.ai。请登录并点击「授权」。",
    pkceStep2: "复制授权后显示的授权代码。",
    pkceStep3: "将代码粘贴到下方并提交。",
    flowLabels: {
      pkce: "浏览器登录（PKCE）",
      device_code: "设备代码",
      external: "外部 CLI",
    },
    expiresIn: "{time}后过期",
  },

  language: {
    switchTo: "切换到英文",
  },

  theme: {
    title: "主题",
    switchTheme: "切换主题",
  },
};

```

---
## `src/lib/crmPresets.ts`
```ts
import type { CrmIntegrationForm } from "@/lib/api";

export interface CrmPreset {
  slug: string;
  label: string;
  description: string;
  helpUrl: string;
  helpText: string;
  keyLabel: string;
  logo: string;
  notice?: string;
  template: Omit<CrmIntegrationForm, "apiKey" | "hasApiKey" | "apiKeyPreview">;
}

const base = {
  hasApiKey: false as const,
  apiKeyPreview: null,
};

export const CRM_PRESETS: CrmPreset[] = [
  {
    slug: "lofty",
    label: "Lofty",
    description: "Lofty CRM (formerly Chime). Authorization: token <key>.",
    helpUrl: "https://help.lofty.com/hc/en-us/articles/47499531505179",
    helpText: "Settings → Integrations → API on each user account.",
    keyLabel: "Lofty API Key",
    logo: "https://logo.clearbit.com/lofty.com",
    template: {
      provider: "lofty",
      label: "Lofty CRM",
      apiKeyEnv: "LOFTY_API_KEY",
      baseUrl: "https://api.lofty.com",
      authType: "header",
      authHeader: "Authorization",
      authPrefix: "token ",
      authQueryParam: "",
      endpoints: {
        leads: "/v1.0/leads",
        lead: "/v1.0/leads/:id",
        notes: "/v2.0/leads/:id/activities",
      },
      dbColumns: {
        leadId: "id",
        stage: "stage",
        tags: "tags",
      },
    },
  },
  {
    slug: "followupboss",
    label: "Follow Up Boss",
    description: "Basic auth: API key as username, blank password.",
    helpUrl: "https://help.followupboss.com/hc/en-us/articles/360014289393",
    helpText: "Admin → API. Each user has a unique key.",
    keyLabel: "Follow Up Boss API Key",
    logo: "https://logo.clearbit.com/followupboss.com",
    template: {
      provider: "followupboss",
      label: "Follow Up Boss",
      apiKeyEnv: "FUB_API_KEY",
      baseUrl: "https://api.followupboss.com/v1",
      authType: "basic",
      authHeader: "Authorization",
      authPrefix: "",
      authQueryParam: "",
      endpoints: {
        leads: "/people",
        lead: "/people/:id",
        notes: "/notes",
      },
      dbColumns: {
        leadId: "id",
        stage: "stage",
        tags: "tags",
      },
    },
  },
  {
    slug: "sierra",
    label: "Sierra Interactive",
    description: "Custom Sierra-ApiKey header.",
    helpUrl: "https://help.sierrainteractive.com/helpcenter/unlock-new-opportunities-with-the-sierra-api",
    helpText: "Gear icon → Integrations → Sierra Interactive → Copy API Key.",
    keyLabel: "Sierra API Key",
    logo: "https://logo.clearbit.com/sierrainteractive.com",
    template: {
      provider: "sierra",
      label: "Sierra Interactive",
      apiKeyEnv: "SIERRA_API_KEY",
      baseUrl: "https://api.sierrainteractivedev.com",
      authType: "header",
      authHeader: "Sierra-ApiKey",
      authPrefix: "",
      authQueryParam: "",
      endpoints: {
        leads: "/leads/Get",
        lead: "/leads/Get/:id",
        notes: "/leads/AddNote",
      },
      dbColumns: {
        leadId: "id",
        stage: "leadType",
        tags: "tags",
      },
    },
  },
  {
    slug: "boldtrail",
    label: "BoldTrail",
    description: "Bearer token. Tokens expire after 12 months — renew yearly.",
    helpUrl: "https://help.insiderealestate.com/en/articles/4263959-boldtrail-api-tokens",
    helpText: "Lead Engine → Lead Dropbox → choose scope → Generate token. Up to 3 tokens per account.",
    keyLabel: "BoldTrail API Token",
    logo: "https://logo.clearbit.com/boldtrail.com",
    notice: "BoldTrail tokens expire after 12 months. Set a calendar reminder to regenerate.",
    template: {
      provider: "boldtrail",
      label: "BoldTrail",
      apiKeyEnv: "BOLDTRAIL_API_TOKEN",
      baseUrl: "https://api.boldtrail.com",
      authType: "header",
      authHeader: "Authorization",
      authPrefix: "Bearer ",
      authQueryParam: "",
      endpoints: {
        leads: "/v2/contacts",
        lead: "/v2/contacts/:id",
        notes: "/v2/contacts/:id/notes",
      },
      dbColumns: {
        leadId: "id",
        stage: "stage",
        tags: "tags",
      },
    },
  },
  {
    slug: "brivity",
    label: "Brivity",
    description: "Token-based auth, Rails style. Account owners only can generate keys.",
    helpUrl: "https://nvntd.github.io/brivity-core/doc/api/index.html",
    helpText: "Settings → Business. Account owner role required to issue API keys.",
    keyLabel: "Brivity API Key",
    logo: "https://logo.clearbit.com/brivity.com",
    notice: "Brivity API keys can only be generated by the account owner. Team agents need owner help.",
    template: {
      provider: "brivity",
      label: "Brivity",
      apiKeyEnv: "BRIVITY_API_KEY",
      baseUrl: "https://www.brivity.com",
      authType: "header",
      authHeader: "Authorization",
      authPrefix: "Token token=",
      authQueryParam: "",
      endpoints: {
        leads: "/api/v2/leads",
        lead: "/api/people/:id",
        notes: "/api/v2/notes",
      },
      dbColumns: {
        leadId: "id",
        stage: "stage",
        tags: "tags",
      },
    },
  },
];

export function findPresetForForm(form: CrmIntegrationForm | null): CrmPreset | null {
  if (!form) return null;
  return CRM_PRESETS.find((p) => p.template.provider === form.provider) ?? null;
}

export function applyPreset(
  preset: CrmPreset,
  current: CrmIntegrationForm | null,
): CrmIntegrationForm {
  const carry = current ?? ({} as Partial<CrmIntegrationForm>);
  return {
    ...preset.template,
    apiKey: carry.apiKey ?? "",
    hasApiKey: base.hasApiKey,
    apiKeyPreview: base.apiKeyPreview,
  };
}

```

---
## `src/lib/format.ts`
```ts
/**
 * Format a token count as a human-readable string (e.g. 1M, 128K, 4096).
 * Strips trailing ".0" for clean round numbers.
 */
export function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

```

---
## `src/lib/nested.ts`
```ts
export function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split(".");
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}

export function setNestedValue(obj: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const clone = structuredClone(obj);
  const parts = path.split(".");
  let cur: Record<string, unknown> = clone;
  for (let i = 0; i < parts.length - 1; i++) {
    if (cur[parts[i]] == null || typeof cur[parts[i]] !== "object") {
      cur[parts[i]] = {};
    }
    cur = cur[parts[i]] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
  return clone;
}

```

---
## `src/lib/onboarding-sounds.ts`
```ts
/**
 * Web Audio sound cues for the admin onboarding flow.
 *
 * No assets — everything is synthesized via the Web Audio API. Sounds are
 * subtle (peak gain <= 0.06) so they don't startle on default volume.
 *
 * Lazy AudioContext: created on first play, reused thereafter. iOS/macOS
 * Safari require an explicit user gesture before the context can produce
 * sound; calling these from a button click handler satisfies that.
 */

let ctx: AudioContext | null = null;
let muted = false;

function getCtx(): AudioContext | null {
  if (muted) return null;
  if (typeof window === "undefined") return null;
  if (!ctx) {
    try {
      const Ctor = (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
      if (!Ctor) return null;
      ctx = new Ctor();
    } catch {
      return null;
    }
  }
  if (ctx.state === "suspended") {
    void ctx.resume().catch(() => {});
  }
  return ctx;
}

export function setOnboardingSoundsMuted(value: boolean) {
  muted = value;
}

/** Soft ambient swell — used on welcome -> wizard and wizard -> seeding. */
export function playOnboardingSwell() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const master = ac.createGain();
  master.gain.setValueAtTime(0, now);
  master.gain.linearRampToValueAtTime(0.06, now + 0.18);
  master.gain.exponentialRampToValueAtTime(0.0001, now + 1.4);
  master.connect(ac.destination);

  const fundamentals = [196, 261.63, 392];
  fundamentals.forEach((freq, idx) => {
    const osc = ac.createOscillator();
    osc.type = idx === 2 ? "triangle" : "sine";
    osc.frequency.setValueAtTime(freq, now);

    const gain = ac.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(idx === 2 ? 0.35 : 0.5, now + 0.2 + idx * 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.3);

    osc.connect(gain).connect(master);
    osc.start(now);
    osc.stop(now + 1.45);
  });
}

/** Tiny tick — used on Continue button. */
export function playOnboardingClick() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const osc = ac.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, now);
  osc.frequency.exponentialRampToValueAtTime(660, now + 0.08);

  const gain = ac.createGain();
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.04, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.1);

  osc.connect(gain).connect(ac.destination);
  osc.start(now);
  osc.stop(now + 0.12);
}

/**
 * Cinematic whoosh — plays `/sounds/onboarding-whoosh.wav` (Foundation
 * Ocular Whooshes - "Dark Air"). Fired on Start onboarding / Continue
 * transitions to give the welcome -> wizard motion a cinematic edge
 * over the synthesized swell alone.
 */
export function playOnboardingWhoosh() {
  if (muted || typeof window === "undefined") return;
  try {
    const audio = new Audio("/sounds/onboarding-whoosh.wav");
    audio.volume = 0.55;
    void audio.play().catch(() => {});
  } catch {
    // audio unavailable - silent fail
  }
}

/** Two-note chime — used when seeding completes and admin is ready. */
export function playOnboardingChime() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const notes: Array<[number, number]> = [
    [523.25, 0],     // C5
    [659.25, 0.16],  // E5
    [783.99, 0.32],  // G5
  ];

  notes.forEach(([freq, offset]) => {
    const osc = ac.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(freq, now + offset);

    const gain = ac.createGain();
    gain.gain.setValueAtTime(0, now + offset);
    gain.gain.linearRampToValueAtTime(0.05, now + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.5);

    osc.connect(gain).connect(ac.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.55);
  });
}

```

---
## `src/lib/resolve-page-title.ts`
```ts
import type { Translations } from "@/i18n/types";

const BUILTIN: Record<string, keyof Translations["app"]["nav"]> = {
  "/chat": "chat",
  "/project": "project",
  "/sessions": "sessions",
  "/analytics": "analytics",
  "/logs": "logs",
  "/cron": "cron",
  "/skills": "skills",
  "/config": "config",
  "/env": "keys",
  "/docs": "documentation",
};

export function resolvePageTitle(
  pathname: string,
  t: Translations,
  pluginTabs: { path: string; label: string }[],
): string {
  const normalized = pathname.replace(/\/$/, "") || "/";
  if (normalized === "/") {
    return "Today";
  }
  if (normalized === "/today") {
    return "Today";
  }
  if (normalized === "/leads") {
    return "Leads";
  }
  if (normalized === "/admin") {
    return "Admin";
  }
  if (normalized === "/listings") {
    return "Admin";
  }
  if (normalized === "/deals") {
    return "Admin";
  }
  if (normalized === "/social-media") {
    return "Social Media";
  }
  if (normalized === "/marketing") {
    return "Social Media";
  }
  if (normalized === "/tasks") {
    return "Tasks";
  }
  if (normalized === "/approvals") {
    return "Today";
  }
  if (normalized === "/memory") {
    return "Memory";
  }
  if (normalized === "/hub") {
    return "Agent Hub";
  }
  if (normalized === "/desktop-setup") {
    return "Desktop Setup";
  }
  if (normalized === "/config") {
    return "Settings";
  }
  const plugin = pluginTabs.find((p) => p.path === normalized);
  if (plugin) {
    return plugin.label;
  }
  const key = BUILTIN[normalized];
  if (key) {
    return t.app.nav[key];
  }
  return t.app.webUi;
}

```

---
## `src/themes/index.ts`
```ts
export { ThemeProvider, useTheme } from "./context";
export { BUILTIN_THEMES, defaultTheme } from "./presets";
export type { DashboardTheme, ThemeLayer, ThemeListResponse, ThemePalette } from "./types";

```
