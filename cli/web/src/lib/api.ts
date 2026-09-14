const BASE = "";

import type {
  AdminContactDetail,
  AdminContactNote,
  AdminContactNotesResponse,
  AdminContactItem,
  AdminContactItemsResponse,
  ReportingSummary,
  ReportingGoals,
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function itemLabel(item: unknown): string {
  if (!isRecord(item)) return "";
  for (const key of ["label", "field", "kind", "name", "id"]) {
    const value = stringValue(item[key]);
    if (value) return value;
  }
  return "";
}

function compactList(items: unknown, limit = 4): string {
  if (!Array.isArray(items)) return "";
  const labels = items.map(itemLabel).filter(Boolean);
  if (!labels.length) return "";
  const shown = labels.slice(0, limit);
  const hidden = labels.length - shown.length;
  return hidden > 0 ? `${shown.join(", ")}, +${hidden} more` : shown.join(", ");
}

function formatGateError(detail: Record<string, unknown>): string | null {
  const gate = isRecord(detail.gate) ? detail.gate : null;
  if (!gate) return null;

  const message = stringValue(detail.message);
  const stageName = stringValue(gate.stageName) || "This stage";
  const nextStageName = stringValue(gate.nextStageName);

  if (message === "deal must move through the next phase gate") {
    return nextStageName
      ? `Move through ${nextStageName} first.`
      : "Move through the next phase first.";
  }

  const missing = [
    ...(Array.isArray(gate.missingChecklist) ? gate.missingChecklist : []),
    ...(Array.isArray(gate.missingFields) ? gate.missingFields : []),
    ...(Array.isArray(gate.missingDocs) ? gate.missingDocs : []),
  ];
  const needs = compactList(missing);
  const runs = Array.isArray(gate.blockingRuns) ? gate.blockingRuns.filter(isRecord) : [];
  const waiting = compactList(runs.filter((run) => stringValue(run.status) === "waiting_human"), 2);
  const runningCount = runs.filter((run) => stringValue(run.status) !== "waiting_human").length;

  const parts = [`${stageName} is blocked.`];
  if (needs) parts.push(`Need: ${needs}.`);
  if (waiting) parts.push(`Waiting on you: ${waiting}.`);
  if (runningCount > 0) parts.push(`Running: ${runningCount} task${runningCount === 1 ? "" : "s"}.`);
  return parts.join(" ");
}

function formatStructuredErrorDetail(value: unknown): string {
  if (!isRecord(value)) return "";
  const gateMessage = formatGateError(value);
  if (gateMessage) return gateMessage;
  for (const key of ["message", "error", "reason"]) {
    const text = stringValue(value[key]);
    if (text) return text;
  }
  return "";
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
        const formatted = formatStructuredErrorDetail(value);
        if (formatted) return formatted;
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
  // A JSON.stringify'd body with no Content-Type goes out as text/plain (the
  // browser's default for a string), and FastAPI then refuses to parse it into
  // the route's model — a 422 that reads as "couldn't be completed" in the UI
  // and leaves nothing in the logs but a status code. Every call here already
  // sets the header by hand; `sendForSignatures` was the one that didn't, and
  // onboarding signature runs failed for it. Defaulting it removes the whole
  // class rather than the one instance.
  // Guarded on `typeof body === "string"`: FormData must NOT get this, or the
  // browser stops generating its multipart boundary and uploads break.
  if (typeof init?.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
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

  const promise = fetchJSONNetwork<T>(url, init).then((result) => {
    const current = GET_CACHE.get(key);
    if (current?.promise === promise) current.expiresAt = Date.now() + ttlMs;
    return result;
  }).catch((error) => {
    if (GET_CACHE.get(key)?.promise === promise) {
      GET_CACHE.delete(key);
    }
    throw error;
  });
  // Pending requests never expire into duplicate requests. Start the short
  // freshness window only after completion, including on slow machines.
  GET_CACHE.set(key, { expiresAt: Infinity, promise });
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
    fileName: decodeURIComponent(res.headers.get("x-elevate-file-name") ?? ""),
    resolvedPath: res.headers.has("x-elevate-file-path") ? decodeURIComponent(res.headers.get("x-elevate-file-path")!) : undefined,
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

// One row of the CMA search grid. `searchPass` is provenance (pass1-tight,
// pass2-12mo, pass5-crossArea...) and `reason` is the plain-language explanation
// shown when a row was not used. Reason strings follow the CMA language rules:
// they describe the mismatch, never judge the home.
// One comp's (or the subject's) facts as read off the Xposure detail sheet.
// Every field is nullable on purpose: the scraper mispairs keys on some sheets,
// so the reader returns null rather than a garbage string and the UI omits the
// row. `salePrice`/`listPrice`/`taxes` are present on comps and deliberately
// absent on the subject.
export type BrandKit = {
  id: string; name: string; tagline?: string;
  colors: Record<string, { hex: string; label: string; use?: string }>;
  fonts: Record<string, { family: string; google?: string; use?: string }>;
  assets?: Record<string, string>;
  // which referenced assets are actually on disk, so a kit reads as incomplete
  // rather than rendering a broken image
  assetsPresent?: Record<string, boolean>;
  contact?: Record<string, string>;
  rules?: string[];
};

export type CmaBracketRow = {
  mls: string; address: string; price: number;
  position: string | null;
  // "yours" when Skyleigh set it (or her note did), "tool" when it is the
  // tool's own read. The screen says which, so a machine's guess is never
  // mistaken for her judgement.
  source: "yours" | "tool" | null;
  label: string; note?: string | null;
};

// An active listing as COMPETITION. Solds are evidence of value and set the
// bracket; these never do. What matters here is what the market has already done
// to them: days sitting, and any cut it has forced.
export type CmaActiveRow = {
  mls: string; address: string;
  listPrice?: number | null; origPrice?: number | null;
  cut?: number | null; cutPct?: number | null;
  listedOn?: string | null; cutOn?: string | null;
  daysOnMarket?: number | null; daysToCut?: number | null;
  story?: string | null; note?: string | null; position?: string | null;
};

export type CmaFacts = {
  address?: string | null;
  sqft?: number | null; lotSqft?: number | null; lotAcres?: number | null;
  beds?: number | null; baths?: number | null; yearBuilt?: number | null;
  dom?: number | null; cdom?: number | null;
  basement?: string | null; parking?: string | null;
  suitePotential?: string | null; suites?: string | null;
  heating?: string | null; cooling?: string | null; fireplaces?: number | null;
  roof?: string | null; style?: string | null;
  taxes?: number | null; salePrice?: number | null; listPrice?: number | null;
  listPriceOrig?: number | null; soldDate?: string | null; listDate?: string | null;
  statusChanged?: string | null; status?: string | null; subArea?: string | null;
  // The MLS sheet, grouped as she scans it. She decides from this, so it is the
  // whole sheet rather than a chosen subset.
  sheet?: { title: string; rows: { label: string; value: string }[] }[];
};

// One subject number: what we will use, what the record said, what Skyleigh
// corrected it to, and which of those `value` came from.
export type CmaSubjectField = {
  value?: number | null;
  recordValue?: number | null;
  yours?: number | null;
  source?: "record" | "skyleigh" | null;
};

export type CmaCompRow = {
  mls: string; address: string; price: string | number; compNum?: number;
  excluded?: boolean; beds?: number; baths?: number; year?: number;
  soldDate?: string | null; status?: string; carriedOver?: boolean;
  subArea?: string | null; listPrice?: string | number | null; dom?: number | null;
};

export type CmaCandidate = {
  mls: string;
  address: string;
  price: string | number | null;
  soldDate?: string | null;
  status?: string | null;
  beds?: string | number | null;
  baths?: string | number | null;
  year?: string | number | null;
  subtype?: string | null;
  minorArea?: string | null;
  searchPass?: string | null;
  excluded?: boolean;
  reason?: string;
};

export type CmaExpiredListing = {
  mlsNumber?: string | null;
  listPrice?: string | null;
  status?: string | null;
  offMarketDate?: string | null;
  yearBuilt?: string | null;
  bedrooms?: string | null;
  bathrooms?: string | null;
  minorArea?: string | null;
};

export type AdminDeadlineDeal = {
  id: string;
  title: string;
  side: string;
  currentStage: number;
  subjectRemovalDate: string | null;
  completionDate: string | null;
  primaryContactId: string | null;
};

export type CmaExpiredRow = {
  key: string; address: string; attempts: number;
  topAsk: number | null; lowAsk: number | null;
  minorArea?: string | null; bedrooms?: string | null; bathrooms?: string | null;
  yearBuilt?: string | null; hasPhotos?: boolean;
  excluded: boolean; inReport: boolean;
  // Advisory only. Nothing acts on it: she decides.
  outsideBracket?: string | null;
};
export type CmaExpiredList = {
  ok: boolean; available: boolean; reason?: string;
  expired: CmaExpiredRow[]; shownCap?: number;
  floor?: number | null; ceiling?: number | null;
};

export type CmaPricePageQuads = {
  pricingStrategy?: string[];
  valueDrivers?: string[];
  buyerQuestions?: string[];
  prepNextSteps?: string[];
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
  previewFileUrl: (path: string) =>
    `${BASE}/api/files/preview?path=${encodeURIComponent(path)}`,
  previewFile: (path: string, signal?: AbortSignal) =>
    fetchBlob(`/api/files/preview?path=${encodeURIComponent(path)}`, { signal }),
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
  // Create a NEW custom surface from the template (add-agent). Seeds it
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
  // self-improvement track). Mirrors manage-cycle create.
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
  // Convenience: same endpoint as listSurfaceApprovals, optional status filter.
  getSurfaceApprovals: (status?: string) =>
    fetchJSON<{ approvals: import("./api-types").SurfaceApproval[] }>(
      `/api/surface-approvals${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
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
  // Comms — native meeting room and pair channels, projected from the
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
  // Documents panel — list/upload a deal's Drive folder files.
  listDealDocuments: (dealId: string) =>
    fetchJSON<{ ok: boolean; folderId: string | null; folderUrl: string | null; files: { name: string; id: string; url: string; mime: string; modified: string; group: string; tag: string }[] }>(`/api/admin/deals/${encodeURIComponent(dealId)}/documents`),
  uploadDealDocument: (dealId: string, file: File, address?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (address) fd.append("address", address);
    return fetchJSON<{ ok: boolean; url?: string | null }>(`/api/admin/deals/${encodeURIComponent(dealId)}/documents`, { method: "POST", body: fd });
  },
  // Client Onboarding — draft one onboarding doc (agency / dorts / pnc).
  // `fields` carries the manual overrides typed into the card's Edit panel.
  sendOnboardingDoc: (dealId: string, form: string, fields?: Record<string, string>) =>
    fetchJSON<{ ok: boolean; url?: string | null; filePath?: string | null }>(`/api/admin/deals/${encodeURIComponent(dealId)}/onboarding-doc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields && Object.keys(fields).length ? { form, fields } : { form }),
    }),
  // Dispatch the provider-neutral signing run for the onboarding package.
  // `forms` picks which onboarding docs go in the envelope (agency/dorts/pnc).
  // Omitted => the backend's DORTS + PNC default.
  sendForSignatures: (dealId: string, forms?: string[]) =>
    fetchJSON<{ ok: boolean; runId?: string | null }>(`/api/admin/deals/${encodeURIComponent(dealId)}/onboarding-sign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(forms && forms.length ? { forms } : {}),
    }),
  // CMA wizard — checkpointed phase pipeline + comp review.
  getCmaPhases: (dealId: string) =>
    fetchJSON<{ ok: boolean; done: number; total: number; pdfUrl?: string | null; reportReady?: boolean; reportVersion?: string; revision?: number; photosUrl?: string; photosUrlSet?: boolean; phases: { id: string; label: string; browser: boolean; manual: boolean; status: string; attempts: number; error?: string | null }[] }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/phases`),
  runCmaPhase: (dealId: string, phase: string) =>
    fetchJSON<{ ok: boolean; phase?: string; status?: string; error?: string | null }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase }),
    }),
  skipCmaPhotos: (dealId: string) =>
    fetchJSON<{ ok: boolean; skipped?: boolean; note?: string; error?: string | null }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/skip-photos`,
      { method: "POST" },
    ),
  scoreCmaPhotos: (dealId: string) =>
    fetchJSON<{ ok: boolean; started?: boolean; photosUrl?: string; error?: string | null }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/score-photos`,
      { method: "POST" },
    ),
  regenerateCmaComps: (dealId: string, instructions: string) =>
    fetchJSON<{ ok: boolean; started?: boolean; areas?: string | null; anchor?: string | null }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/regenerate-comps`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instructions }) },
    ),
  getCmaPricing: (dealId: string) =>
    fetchJSON<{ ok: boolean; recommendedPrice?: string | null; range?: string | null; strategy?: string | null;
      valueDrivers?: unknown;
      better?: Array<{ address: string; price: string | number; suite?: unknown }>;
      comparable?: Array<{ address: string; price: string | number; suite?: unknown }>;
      worse?: Array<{ address: string; price: string | number; suite?: unknown }> }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/pricing`),
  repriceCma: (dealId: string, price: string, rationale: string) =>
    fetchJSON<{ ok: boolean; started?: boolean; price?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/reprice`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ price, rationale }) },
    ),
  captureCmaProspecting: (dealId: string, mls: string) =>
    fetchJSON<{ ok: boolean; started?: boolean; mls?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/capture-prospecting`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mls }) },
    ),
  getCmaComps: (dealId: string) =>
    fetchJSON<{ ok: boolean; sold: CmaCompRow[]; active: CmaCompRow[];
                // Rides along so the review screen does not need a second call
                // just to pin her own specs above the comps.
                subject?: CmaFacts }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/comps`),
  // `reason` is only meaningful when EXCLUDING; the runner clears it when a comp
  // is put back, so a stale reason can never ride along with a comp in the set.
  toggleCmaComp: (dealId: string, mls: string, kind: "sold" | "active", reason?: string) =>
    fetchJSON<{ ok: boolean; mls: string; kind: string; excluded: boolean; reason?: string | null; reasonText?: string | null }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mls, kind, reason }),
    }),
  // The full pass-A grid behind the comp review: what the search picked, what it
  // saw and didn't pick, and what it dropped with the reason. available:false is a
  // normal answer for a property whose last pull predates the always-write change.
  getCmaCandidates: (dealId: string) =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string; error?: string;
      counts?: { selected: number; worthALook: number; outOfRange: number };
      searchPasses?: Record<string, number>; pulledAt?: string;
      selected: CmaCandidate[]; worthALook: CmaCandidate[]; outOfRange: CmaCandidate[];
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/candidates`),
  // Listings that came off market without selling. Never comps, never in the
  // Address front door for a new evaluation. Two groups: evaluations she already
  // has open (picking one OPENS it, never creates a duplicate card for the same
  // property) and BC's public geocoder for a brand new address. `geocoderOk:false`
  // means the lookup was unreachable, NOT that the address is unknown -- the UI
  // has to say so rather than implying the address does not exist.
  // The subject's own numbers plus WHERE each came from. `source` is the point:
  // a figure off a 1999 sheet and one Skyleigh typed both read "2,016" otherwise,
  // and only one of them should be filtered tightly.
  getCmaSubject: (dealId: string) =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string; address?: string;
      recordAgeYears?: number | null; recordStale?: boolean; recordDate?: string | null;
      yearBuilt?: number | null;
      sqft: CmaSubjectField; lot: CmaSubjectField; beds: CmaSubjectField; baths: CmaSubjectField;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/subject`),
  // Blank CLEARS a field, so there is always a way back to what the MLS says.
  setCmaSubject: (dealId: string, values: Record<string, string>) =>
    fetchJSON<{ ok: boolean; overrides?: Record<string, number>; error?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/subject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      }),
  // Keep a comp across re-pulls. Captures its row and photos as they are now, so
  // a later search that misses it carries it forward instead of losing it.
  toggleCmaKeep: (dealId: string, mls: string, kind: "sold" | "active" = "sold") =>
    fetchJSON<{ ok: boolean; mls: string; kind: string; kept: boolean; photos?: number; error?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-keep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mls, kind }),
      }),
  // Pull the comps from a Saved List she already built in Xposure instead of
  // from the tool's own search. Detached: it is a browser session with MFA.
  cmaFromSavedList: (dealId: string, listName: string) =>
    fetchJSON<{ ok: boolean; started?: boolean; listName?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/from-saved-list`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ listName }),
      }),
  // Did the saved-list pull work? Detached runs fail silently otherwise.
  getCmaSavedListStatus: (dealId: string) =>
    fetchJSON<{ ok: boolean; state: "none" | "running" | "done" | "failed";
                list?: string; error?: string; solds?: number; actives?: number;
                compsPulled?: number }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/saved-list-status`),
  // Her read on the home, beside what the photo scoring found. With photos this
  // is an adjustment; without them it IS the assessment, and the report says so.
  getCmaAssessment: (dealId: string) =>
    fetchJSON<{
      ok: boolean; hasPhotos: boolean; hasMine: boolean; notes?: string; savedAt?: string | null;
      axes: { key: string; label: string; picked?: string | null; scored?: number | null;
              chips: { id: string; label: string }[] }[];
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/assessment`),
  setCmaAssessment: (dealId: string, body: { picks?: Record<string, string>; notes?: string }) =>
    fetchJSON<{
      ok: boolean; error?: string; hasPhotos?: boolean; hasMine?: boolean; notes?: string;
      axes?: { key: string; label: string; picked?: string | null; scored?: number | null;
               chips: { id: string; label: string }[] }[];
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/assessment`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // What the seller's report will include. Everything is on unless she turned it
  // off. `locked` sections are refused by the runner, not just hidden, because
  // the visual QA gate hard-fails without them.
  getCmaSections: (dealId: string) =>
    fetchJSON<{
      ok: boolean; onCount: number; total: number;
      sections: { key: string; label: string; blurb?: string; locked?: boolean; on: boolean }[];
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/sections`),
  setCmaSections: (dealId: string, sections: Record<string, boolean>) =>
    fetchJSON<{
      ok: boolean; error?: string; onCount?: number; total?: number;
      sections?: { key: string; label: string; blurb?: string; locked?: boolean; on: boolean }[];
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/sections`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sections }),
    }),
  // Page images of the report she is about to send. Rendered on demand and
  // re-rendered when the PDF is newer, so she never reviews a previous render.
  getCmaReportPages: (dealId: string) =>
    fetchJSON<{ ok: boolean; available: boolean; pages: number; file?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/report-pages`),
  cmaReportPageUrl: (dealId: string, n: number) =>
    `/api/admin/deals/${encodeURIComponent(dealId)}/cma/report-page/${n}`,
  // The approved CMA design: what the final PDF is judged against. Uploading a
  // new one is not decoration -- cma-visual-qa.py resolves the same pointer, so
  // this sets what every future CMA is proofed against.
  getCmaApprovedTemplate: () =>
    fetchJSON<{
      ok: boolean; available: boolean; file?: string; originalName?: string;
      uploadedAt?: string | null; legacy?: boolean; pages?: number | null;
      bytes?: number; hasPreview?: boolean; pageImages?: number;
    }>("/api/admin/cma/approved-template"),
  // Every page, not just the cover: the layout on the comp pages IS most of the
  // design, so a single thumbnail does not tell her what she is approving.
  cmaApprovedTemplatePageUrl: (n: number) => `/api/admin/cma/approved-template/page/${n}`,
  uploadCmaApprovedTemplate: (filename: string, dataUrl: string) =>
    fetchJSON<{ ok: boolean; file?: string; pages?: number | null; pageImages?: number; hasPreview?: boolean }>(
      "/api/admin/cma/approved-template", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, dataUrl }),
      }),
  // The set-aside reason vocabulary, served from the runner so the chips, the
  // stored value and the report cannot drift apart.
  getCmaSetAsideReasons: () =>
    fetchJSON<{ ok: boolean; reasons: { key: string; text: string }[] }>(
      "/api/admin/cma/set-aside-reasons"),
  getCmaAddressSuggest: (q: string) =>
    fetchJSON<{
      ok: boolean; query: string; geocoderOk: boolean;
      deals: { dealId: string; address: string; side?: string | null; stage?: number | null; status?: string | null; title?: string | null }[];
      geocoded: { address: string; locality?: string | null; score?: number | null; matchPrecision?: string | null }[];
    }>(`/api/admin/cma/address-suggest?q=${encodeURIComponent(q)}`),
  // Everything Xposure holds for ONE comp + the subject's matching facts, so the
  // review pane can draw "theirs vs yours" without a second call. The rail feed
  // (`getCmaComps`) returns 11 fields on purpose; this is the other ~270.
  // NOTE: `subject` carries NO price fields, by rule. The subject's own list or
  // sale price must never appear beside a comp.
  getCmaCompDetail: (dealId: string, num: number, kind: "comp" | "active" = "comp") =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string; num?: number;
      comp?: CmaFacts & { publicRemarks?: string | null; roomTables?: unknown[] };
      subject?: CmaFacts;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-detail/${num}?kind=${kind}`),
  // Buyer demand per price bracket. `cliff` is the biggest jump in newly-matching
  // buyers and is the load-bearing pricing argument ("a $5,000 cut adds 622
  // buyers"), derived server-side so the wizard and the PDF cannot disagree.
  getCmaProspecting: (dealId: string) =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string;
      brackets: { price: number; newSearches: number }[];
      cliff?: { price: number; gain: number; costFromPrice: number; costDollars: number } | null;
      anchorMls?: string | null; anchorAddress?: string | null; anchorPrice?: number | null;
      // Buyers already matching at the anchor price. Each bracket's newSearches is
      // the number ADDED to this, so any display must sum them.
      currentMatched?: number | null;
      recommendation?: number | null; step?: number | null; capturedAt?: string | null;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/prospecting`),
  // anchor. attempts > 1 is the row that carries the overpricing argument.
  getCmaExpired: (dealId: string) =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string;
      byAddress: { address: string; attempts: number; listings: CmaExpiredListing[] }[];
      addressCount?: number; repeatCount?: number; statusesMatched?: string[]; monthsBack?: number;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/expired`),
  // Photo indices are NOT a range: comps are numbered from 1, actives and the
  // subject from 0. Always iterate `indices`, never 0..count-1.
  listCmaCompPhotos: (dealId: string, num: number, kind: "comp" | "active" | "subject" = "comp") =>
    fetchJSON<{ kind: string; num: number; count: number; indices: number[]; captured: number;
                // Room labels per photo index, and room -> index for matching
                // their kitchen to hers. Empty when scoring has not run.
                labels?: Record<string, string>; rooms?: Record<string, number> }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-photos/${num}?kind=${kind}`),
  // Her own words on a comp. The report prints `voiced` in place of the
  // automatic verdict; `raw` is kept only so she can see what she typed and
  // re-run the rewrite without retyping it.
  getCmaNotes: (dealId: string) =>
    fetchJSON<{
      ok: boolean;
      notes: Record<string, { mls: string; kind: string; num?: number; address?: string;
                              raw?: string; voiced?: string; savedAt?: string }>;
      overview: { raw?: string; voiced?: string; savedAt?: string };
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/notes`),
  setCmaNote: (dealId: string, mls: string, kind: "sold" | "active", raw: string, voiced: string, position?: string | null) =>
    fetchJSON<{ ok: boolean; error?: string; num?: number; voiced?: string; position?: string | null; rowsWritten?: number }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/note`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mls, kind, raw, voiced, position }),
      }),
  // Where a comp sits relative to the subject. This is the pricing model: the
  // cheapest comp that beats the home is the ceiling, the dearest it beats is the
  // floor. No arithmetic derives a price from it.
  setCmaPosition: (dealId: string, mls: string, kind: "sold" | "active", position: string | null) =>
    fetchJSON<{ ok: boolean; error?: string; position?: string | null; label?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/position`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mls, kind, position }),
      }),
  // The detached buyer-demand capture writes a status file; this is the only way
  // the wizard can tell a running scrape from a dead button.
  // Puts the finished CMA in front of the seller as a Gmail DRAFT with the PDF
  // attached. It never sends: a market evaluation carries the number they price
  // their home from, so it goes through the same approval gate as every other
  // client-facing message here.
  draftCmaToSeller: (dealId: string) =>
    fetchJSON<{ ok: boolean; error?: string; draftId?: string; to?: string;
                attached?: string; subject?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/draft-to-seller`, { method: "POST" }),
  getCmaProspectingStatus: (dealId: string) =>
    fetchJSON<{ ok: boolean; state: "idle" | "running" | "ok" | "failed";
                message?: string; mls?: string | null; at?: string | null }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/prospecting-status`),
  // ---- Brand kits -------------------------------------------------------
  // A kit is WHOSE a document is (colours, faces, logos, signature, rules); a
  // theme is HOW a page is built. Kept apart so one kit dresses the CMA, the
  // graphics, the emails and the ads.
  getBrandKits: () =>
    fetchJSON<{ ok: boolean; active: string; kits: BrandKit[] }>(`/api/admin/brand/kits`),
  activateBrandKit: (kitId: string) =>
    fetchJSON<{ ok: boolean; error?: string; active?: string }>(
      `/api/admin/brand/kits/${encodeURIComponent(kitId)}/activate`, { method: "POST" }),
  // Reads a design PDF and PROPOSES a kit. Saves nothing: colours are measured
  // off the pixels and typefaces read from the embedded font list, then the human
  // confirms. A design exported as flat images has no fonts to read and says so.
  extractBrandKit: (filename: string, dataBase64: string) =>
    fetchJSON<{
      ok: boolean; error?: string;
      proposed?: BrandKit;
      readFrom?: { pages: number; fontsFound: string[]; textIsImages: boolean; note: string };
    }>(`/api/admin/brand/kits/extract`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, dataBase64 }),
    }),
  saveBrandKit: (kit: BrandKit) =>
    fetchJSON<{ ok: boolean; error?: string; id?: string }>(`/api/admin/brand/kits`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kit }),
    }),
  brandAssetUrl: (relPath: string) =>
    `/api/admin/brand/asset?path=${encodeURIComponent(relPath)}`,
  getCmaBracket: (dealId: string) =>
    fetchJSON<{
      ok: boolean; available: boolean; reason?: string;
      ceiling?: number | null; floor?: number | null; chosen?: string | null;
      above: CmaBracketRow[]; level: CmaBracketRow[]; below: CmaBracketRow[];
      actives?: CmaActiveRow[];
      unpositioned?: number; positions?: Record<string, string>;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/bracket`),
  // Writes the closing summary FROM her comp notes. Saves nothing: she edits it,
  // then setCmaOverview stores what she approved.
  summarizeCmaNotes: (dealId: string) =>
    fetchJSON<{ ok: boolean; error?: string; text: string; fromNotes?: number }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/summarize`, { method: "POST" }),
  // The expired band's set-aside. Sold and active comps have had one since the
  // review screen was built; "what was tried and didn't sell" never did, so every
  // address the search found went into the seller's report whether it sat in her
  // price bracket or not.
  // Deliberately NOT named getCmaExpired: that already exists above and feeds the
  // comp review's candidate list off a different shape. Two client methods on one
  // path is how the backend nearly ended up with two handlers on one route.
  getCmaExpiredSelect: (dealId: string) =>
    fetchJSON<CmaExpiredList>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/expired-select`),
  toggleCmaExpired: (dealId: string, key: string) =>
    fetchJSON<CmaExpiredList & { key?: string; excluded?: boolean }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/expired-select/toggle`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      }),
  // "How We Got to the Price" -- the four boxes of the approved design. The
  // renderer has always been able to print this page; nothing ever wrote it, so
  // it silently dropped out of every wizard-built CMA and the visual check
  // hard-failed A7 without saying so. `inReport` is the honest answer.
  getCmaPricePage: (dealId: string) =>
    fetchJSON<{
      ok: boolean; quads: CmaPricePageQuads; inReport?: boolean;
      sources?: string[]; savedAt?: string | null;
    }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/price-page`),
  // Drafts the four boxes from her notes/picks. Saves nothing, and it runs the
  // headless writer, so callers must show a pending state (up to ~3 min).
  draftCmaPricePage: (dealId: string) =>
    fetchJSON<{ ok: boolean; error?: string; quads: CmaPricePageQuads; sources?: string[] }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/price-page/draft`, { method: "POST" }),
  setCmaPricePage: (dealId: string, quads: CmaPricePageQuads) =>
    fetchJSON<{ ok: boolean; error?: string; quads?: CmaPricePageQuads; inReport?: boolean }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/price-page`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(quads),
      }),
  setCmaOverview: (dealId: string, raw: string, voiced: string) =>
    fetchJSON<{ ok: boolean; error?: string; voiced?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/overview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw, voiced }),
      }),
  // Shorthand in, her voice out. Saves nothing. ~12s, so callers must show a
  // pending state. On failure it still returns her original text.
  cmaVoiceRewrite: (dealId: string, text: string, kind: "comp" | "overview", mls?: string) =>
    fetchJSON<{ ok: boolean; error?: string; text: string; original?: string;
                // which way the note points, for the better/worse toggle
                position?: string | null; positionLabel?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/voice`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, kind, mls }),
      }),
  // Save-first rewrite. Returns as soon as HER RAW TEXT is on disk, then the
  // rewrite runs detached. The old cmaVoiceRewrite above saves nothing and blocks
  // for up to 2 minutes, so leaving the page mid-rewrite lost the note outright.
  cmaRewriteNote: (dealId: string, mls: string, kind: "sold" | "active", text: string, position?: string | null) =>
    fetchJSON<{ ok: boolean; saved?: boolean; rewrite?: string; error?: string; note?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/rewrite-note`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mls, kind, text, position: position ?? null }),
      }),
  // Persists ONLY what she typed. Fired on a debounce while she writes, so the
  // words can never live in the browser alone. `keepalive` lets the pagehide
  // flush outlive a closing tab -- a normal fetch is aborted with the page and
  // the last debounce window of typing dies with it.
  cmaSaveNoteDraft: (dealId: string, mls: string, kind: "sold" | "active", text: string,
                     opts?: { keepalive?: boolean }) =>
    fetchJSON<{ ok: boolean; saved?: boolean; error?: string; rowMissing?: boolean; warning?: string }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/save-draft`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mls, kind, text }),
        ...(opts?.keepalive ? { keepalive: true } : {}),
      }),
  cmaRewriteStatus: (dealId: string, mls: string, kind: "sold" | "active" = "sold") =>
    fetchJSON<{ ok: boolean; rewrite?: string; raw?: string; voiced?: string; rewriteError?: string | null }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/rewrite-status?mls=${encodeURIComponent(mls)}&kind=${kind}`),
  cmaFinishGrid: (dealId: string) =>
    fetchJSON<{ ok: boolean; verdicts: string[]; rows: { compNum: number; mls: string; address: string; suite?: string | null;
                cells: { key: string; label: string; auto: string | null; override: string | null; value: string | null; edited: boolean }[] }[] }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/finish-grid`),
  cmaSetFinishFlip: (dealId: string, comp: string, category: string, verdict: string) =>
    fetchJSON<{ ok: boolean; error?: string; rows?: unknown[] }>(
      `/api/admin/deals/${encodeURIComponent(dealId)}/cma/finish-flip`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comp, category, verdict }),
      }),
  cmaCompPhotoUrl: (dealId: string, num: number, idx: number, kind: "comp" | "active" | "subject" = "comp") =>
    `/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-photo/${num}/${idx}?kind=${kind}`,
  // Subject photos can arrive two ways: a pasted Drive link (existing path) or
  // dropped files. Dropped files post ONE AT A TIME as base64 so payloads stay
  // small and the UI can show real progress. Both paths end up as
  // subject-photo-NN.jpg, which is what the scorer reads when no folder is given.
  clearCmaPhotos: (dealId: string) =>
    fetchJSON<{ ok: boolean; removed: number }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/clear-photos`, { method: "POST" }),
  uploadCmaPhoto: (dealId: string, index: number, dataBase64: string, filename?: string) =>
    fetchJSON<{ ok: boolean; index: number; bytes: number }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/upload-photo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index, dataBase64, filename }),
    }),
  getCmaStagedPhotos: (dealId: string) =>
    fetchJSON<{ ok: boolean; count: number; names: string[] }>(`/api/admin/deals/${encodeURIComponent(dealId)}/cma/staged-photos`),
  gatherCpsPackage: (mls: string, dealId?: string, dryRun?: boolean) =>
    fetchJSON<{ ok: boolean; started: boolean; mls: string; dryRun: boolean }>(`/api/admin/offer-prep/gather`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mls, deal_id: dealId ?? null, dry_run: !!dryRun }),
    }),
  generateCpsDraft: (payload: { umbrella: string; clauses: string[]; customClauses: { wording: string }[]; vars: Record<string, any>; address?: string; dealId?: string }) =>
    fetchJSON<{ ok: boolean; address: string; saved: boolean; url?: string | null }>(`/api/admin/offer-prep/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ umbrella: payload.umbrella, clauses: payload.clauses, customClauses: payload.customClauses, vars: payload.vars, address: payload.address ?? null, deal_id: payload.dealId ?? null, dry_run: false }),
    }),
  generateOfferForm: (form: "pnc" | "dorts" | "disclosure-rem", dealId?: string, address?: string) =>
    fetchJSON<{ ok: boolean; form: string; address: string; saved: boolean; url?: string | null }>(`/api/admin/offer-prep/form`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ form, deal_id: dealId ?? null, address: address ?? null, dry_run: false }),
    }),
  buildOfferPackage: (payload: { umbrella: string; clauses: string[]; customClauses: { wording: string }[]; vars: Record<string, any>; address?: string; dealId?: string; forms?: string[] }) =>
    fetchJSON<{ ok: boolean; address: string; count: number; url?: string | null }>(`/api/admin/offer-prep/package`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ umbrella: payload.umbrella, clauses: payload.clauses, customClauses: payload.customClauses, vars: payload.vars, address: payload.address ?? null, deal_id: payload.dealId ?? null, dry_run: false, forms: payload.forms ?? null }),
    }),
  setAdminDealStatus: (dealId: string, status: "active" | "closed" | "archived") =>
    fetchJSON<AdminDeal>(`/api/admin/deals/${encodeURIComponent(dealId)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
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
  sendDealSellerUpdate: (dealId: string) =>
    fetchJSON<{ ok: boolean; sentAt: string }>(
      `/api/deals/${encodeURIComponent(dealId)}/send-seller-update`,
      { method: "POST" },
    ),
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
  approveAdminActionRun: (runId: string, body: { approved?: boolean; runNow?: boolean; expectedTitleOrderHash?: string } = {}) =>
    fetchJSON<AdminActionRun>(`/api/admin/action-runs/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  answerAdminActionRun: (
    runId: string,
    body: { answers: Record<string, string>; runNow?: boolean; expectedTitleOrderHash?: string },
  ) =>
    fetchJSON<AdminActionRun>(`/api/admin/action-runs/${encodeURIComponent(runId)}/answer`, {
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
  getSourceInbox: (limit = 16, options?: { debug?: boolean }) =>
    cachedFetchJSON<SourceInboxResponse>(
      `/api/source-inbox?limit=${limit}${options?.debug ? "&debug=1" : ""}`,
      5_000,
    ),
  getThreadContext: (sourceId: string, threadId: string, limit = 200) =>
    fetchJSON<ThreadContextResponse>(
      `/api/source-inbox/thread/${encodeURIComponent(sourceId)}/${encodeURIComponent(threadId)}?limit=${limit}`,
    ),

  // ── CRM contact card ─────────────────────────────────────────────────
  getAdminContact: (contactId: string) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}`,
    ),
  getAdminContactNotes: (contactId: string, limit = 50) =>
    fetchJSON<AdminContactNotesResponse>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/notes?limit=${limit}`,
    ),
  deleteContact: (contactId: string) =>
    fetchJSON<{ ok: boolean; deletedContactId: string; name: string; deleted: Record<string, number> }>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}`,
      { method: "DELETE" },
    ),
  saveAdminContactTags: (contactId: string, tags: string[]) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/tags`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      },
    ),
  saveAdminContactSegments: (contactId: string, segments: string[]) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/segments`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segments }),
      },
    ),
  setAdminContactPipeline: (contactId: string, status: string | null) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/pipeline`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      },
    ),
  setAdminContactConsent: (
    contactId: string,
    consent: { call: boolean; text: boolean; email: boolean },
  ) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/consent`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(consent),
      },
    ),
  addAdminContactNote: (contactId: string, body: string, pinned = false) =>
    fetchJSON<AdminContactNote>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/notes`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, pinned }),
      },
    ),
  pinAdminContactNote: (contactId: string, noteId: string, pinned: boolean) =>
    fetchJSON<{ id: string; pinned: boolean }>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/notes/${encodeURIComponent(noteId)}/pin`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned }),
      },
    ),
  setAdminContactTop25: (contactId: string, on: boolean) =>
    fetchJSON<{ contactId: string; top25: boolean }>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/top25`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on }),
      },
    ),
  // All manual temperature overrides, keyed by contact id (for the leads list).
  getAdminContactTemperatures: () =>
    fetchJSON<{ overrides: Record<string, string> }>(
      `/api/admin/contact-temperatures`,
    ),
  // Persist a manual lead-temperature override (empty string clears it, so the
  // contact falls back to the derived recency/tag temperature).
  setAdminContactTemperature: (contactId: string, temperature: string) =>
    fetchJSON<{ contactId: string; temperature: string | null }>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/temperature`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ temperature }),
      },
    ),
  patchAdminContact: (
    contactId: string,
    fields: Partial<{
      displayName: string;
      primaryEmail: string;
      primaryPhone: string;
      buyingTimeFrame: string;
      preQualStatus: string;
      address: string;
      birthday: string;
    }>,
  ) =>
    fetchJSON<AdminContactDetail>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      },
    ),
  // Contact items: Tasks / Appointments / Family on the card's right rail.
  getContactItems: (
    contactId: string,
    kind?: "task" | "appointment" | "family",
  ) =>
    fetchJSON<AdminContactItemsResponse>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/items${
        kind ? `?kind=${encodeURIComponent(kind)}` : ""
      }`,
    ),
  addContactItem: (
    contactId: string,
    body: {
      kind: "task" | "appointment" | "family";
      title: string;
      subtitle?: string;
      whenAt?: string;
    },
  ) =>
    fetchJSON<AdminContactItem>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/items`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  updateContactItem: (
    contactId: string,
    itemId: string,
    body: Partial<{
      title: string;
      subtitle: string;
      whenAt: string;
      done: boolean;
    }>,
  ) =>
    fetchJSON<AdminContactItem>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/items/${encodeURIComponent(itemId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  deleteContactItem: (contactId: string, itemId: string) =>
    fetchJSON<{ deleted: boolean; id: string }>(
      `/api/admin/contacts/${encodeURIComponent(contactId)}/items/${encodeURIComponent(itemId)}`,
      { method: "DELETE" },
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
    action: "approve" | "edit" | "skip" | "restore" | "open" | "channel",
    draftText = "",
    options?: { returnInbox?: boolean; scheduledAt?: string; channel?: string },
  ) =>
    fetchJSON<SourceInboxResponse>("/api/source-inbox/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceId,
        taskId,
        action,
        draftText,
        channel: options?.channel ?? null,
        scheduledAt: options?.scheduledAt ?? null,
        returnInbox: options?.returnInbox ?? true,
      }),
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
    // Accepts the AI's 6 legacy slugs, Skyleigh's 9 operator slugs, or null to
    // clear. Widened from SourceInboxProfileStatus so operator picks persist.
    status: string | null,
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
  // Bulk update many contacts at once from the /leads redesigned table
  // selection bar. action picks the dimension; mode is the set-op for
  // tags/segments (ignored for pipeline). Returns {updated, failed[]}.
  bulkUpdateContacts: (
    contactIds: string[],
    action: "tags" | "segments" | "pipeline",
    value: unknown,
    mode?: "add" | "replace" | "remove",
  ) =>
    fetchJSON<{ updated: number; failed: Array<{ contactId: string; error: string }> }>(
      "/api/admin/contacts/bulk",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contactIds, action, value, mode: mode ?? "add" }),
      },
    ),
  // Sent-messages list for the /leads "Sent" tab. Reads outreach.db.send_queue
  // (status=sent by default). Set includePending=true to also see queued /
  // sending / retrying / failed for debugging mid-flight rows.
  getSourceInboxSent: (limit = 100, includePending = false) =>
    fetchJSON<SourceInboxSentResponse>(
      `/api/source-inbox/sent?limit=${limit}&include_pending=${includePending ? "true" : "false"}`,
    ),
  getSourceInboxNotSent: (limit = 100) =>
    fetchJSON<SourceInboxSentResponse>(`/api/source-inbox/not-sent?limit=${limit}`),
  retrySourceInboxSend: (queueId: string) =>
    fetchJSON<{ requeued: boolean; phone?: string | null }>(
      `/api/source-inbox/retry-send/${encodeURIComponent(queueId)}`,
      { method: "POST" },
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

  // ── Reporting page ───────────────────────────────────────────────────
  getReportingSummary: (window = 30) =>
    fetchJSON<ReportingSummary>(
      `/api/admin/reporting/summary?window=${encodeURIComponent(window)}`,
    ),
  getReportingGoals: () =>
    fetchJSON<ReportingGoals>("/api/admin/reporting/goals"),
  saveReportingGoals: (body: Partial<ReportingGoals>) =>
    fetchJSON<ReportingGoals>("/api/admin/reporting/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export const __apiTestables = {
  extractErrorDetail,
};

export type * from "./api-types";
