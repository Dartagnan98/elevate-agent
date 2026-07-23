/**
 * Omnibox logic for the embedded browser panel's address bar.
 *
 * Pure functions only — the BrowserPanel component owns React state and
 * localStorage IO. Every suggestion is derived from the operator's input or
 * from real recorded navigations (the pane's tab events); nothing is invented.
 *
 * Navigation policy (also the Google bot-wall fix): host-shaped input like
 * "youtube" navigates directly to https://youtube.com. Only input that cannot
 * be a host (spaces, punctuation, bare numbers) falls back to a plain
 * https://www.google.com/search?q= URL. Routing every bare word through
 * /search on a cold profile is what tripped Google's "unusual traffic"
 * interstitial.
 */

export type OmniboxHistoryEntry = {
  /** Full http(s) URL as last visited. */
  url: string;
  /** Last known page title ("" until the page reports one). */
  title: string;
  /** How many times this (normalized) URL was visited. */
  count: number;
  /** Epoch ms of the most recent visit. */
  lastVisited: number;
};

export type OmniboxSuggestion = {
  id: string;
  kind: "navigate" | "search" | "history";
  /** Primary display line — page title, host, or the search phrasing. */
  title: string;
  /** Secondary display line — the destination URL (omitted for search rows). */
  detail?: string;
  /** Where selecting this row navigates. */
  url: string;
};

export const BROWSER_HISTORY_STORAGE_KEY = "elevate.browser.history.v1";
export const BROWSER_HISTORY_CAP = 200;

const HTTP_RE = /^https?:\/\//i;

/** Plain Google search URL — standard params only, nothing appended. */
export function searchUrl(query: string): string {
  return `https://www.google.com/search?q=${encodeURIComponent(query.trim())}`;
}

/**
 * True when the input already reads as a navigable location: an explicit
 * http(s) URL, a dotted hostname ("youtube.com/watch"), an IPv4 address, or
 * localhost — optionally with port/path. Never true for input with spaces.
 */
export function isUrlShaped(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s/.test(trimmed)) return false;
  if (HTTP_RE.test(trimmed)) return true;
  // Reject other schemes (mailto:, file:, chrome:) — but "host:1234" is a
  // port, not a scheme.
  const scheme = trimmed.match(/^([a-z][a-z0-9+.-]*):(.*)$/i);
  if (scheme && !/^\d+([/?#]|$)/.test(scheme[2])) return false;
  const host = trimmed.split(/[/?#]/, 1)[0];
  if (/^localhost(:\d+)?$/i.test(host)) return true;
  if (/^\d{1,3}(\.\d{1,3}){3}(:\d+)?$/.test(host)) return true;
  return /^[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+(:\d+)?$/i.test(host);
}

/**
 * True for a single bare DNS-label token ("youtube", "web-app") that reads as
 * a site name rather than a phrase. Bare numbers are treated as searches.
 */
export function isHostShaped(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || isUrlShaped(trimmed)) return false;
  if (!/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/i.test(trimmed)) return false;
  return /[a-z]/i.test(trimmed);
}

/**
 * Resolve raw address-bar input to a navigation target.
 *
 * - explicit URL / dotted host / localhost / IP → navigate as typed
 * - single bare word ("youtube") → https://youtube.com (never Google search)
 * - everything else → plain Google search URL
 */
export function browserTarget(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === "about:blank") return "about:blank";
  if (HTTP_RE.test(trimmed)) return trimmed;
  if (isUrlShaped(trimmed)) return `https://${trimmed}`;
  if (isHostShaped(trimmed)) return `https://${trimmed.toLowerCase()}.com`;
  return searchUrl(trimmed);
}

/**
 * Canonical dedupe key: scheme/hash dropped, host lowercased without "www.",
 * trailing slashes trimmed, query kept (distinct searches stay distinct).
 */
export function normalizeUrlKey(url: string): string {
  const raw = String(url || "").trim();
  try {
    const parsed = new URL(raw.includes("://") ? raw : `https://${raw}`);
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const path = parsed.pathname.replace(/\/+$/, "");
    return `${host}${path}${parsed.search}`;
  } catch {
    return raw.toLowerCase();
  }
}

/** Keep head and tail, elide the middle — hostnames and filenames survive. */
export function middleTruncate(value: string, max = 64): string {
  const text = String(value ?? "");
  if (max <= 1 || text.length <= max) return text.length <= max ? text : text.slice(0, max);
  const head = Math.ceil((max - 1) * 0.6);
  const tail = max - 1 - head;
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`;
}

/** Display form of a URL for the secondary line: no scheme, no trailing slash. */
export function displayUrl(url: string, max = 72): string {
  const stripped = String(url || "")
    .replace(HTTP_RE, "")
    .replace(/\/+$/, "");
  return middleTruncate(stripped, max);
}

/** Primary line for a history row: title, else hostname+path, middle-truncated. */
export function suggestionTitle(
  entry: { title?: string | null; url: string },
  max = 64,
): string {
  const title = String(entry.title || "").trim();
  if (title) return middleTruncate(title, max);
  try {
    const parsed = new URL(entry.url);
    const host = parsed.hostname.replace(/^www\./, "");
    const path = parsed.pathname !== "/" ? parsed.pathname.replace(/\/+$/, "") : "";
    return middleTruncate(`${host}${path}`, max);
  } catch {
    return middleTruncate(String(entry.url || ""), max);
  }
}

/** Frequency weighted by recency: a visit decays with age in days. */
export function historyScore(entry: OmniboxHistoryEntry, now: number): number {
  const ageDays = Math.max(0, now - entry.lastVisited) / 86_400_000;
  return entry.count / (1 + ageDays);
}

/** Record one real completed navigation. Non-http(s) URLs are ignored. */
export function recordVisit(
  entries: OmniboxHistoryEntry[],
  visit: { url: string; title?: string | null; now: number },
  cap = BROWSER_HISTORY_CAP,
): OmniboxHistoryEntry[] {
  const url = String(visit.url || "").trim();
  if (!HTTP_RE.test(url)) return entries;
  const key = normalizeUrlKey(url);
  const title = String(visit.title || "").trim();
  let found = false;
  const next = entries.map((entry) => {
    if (normalizeUrlKey(entry.url) !== key) return entry;
    found = true;
    return {
      url,
      title: title || entry.title,
      count: entry.count + 1,
      lastVisited: visit.now,
    };
  });
  if (!found) next.push({ url, title, count: 1, lastVisited: visit.now });
  if (next.length <= cap) return next;
  return next
    .sort((a, b) => historyScore(b, visit.now) - historyScore(a, visit.now))
    .slice(0, cap);
}

/** Late title arrival (page-title-updated) — update in place, no count bump. */
export function retitleVisit(
  entries: OmniboxHistoryEntry[],
  url: string,
  title: string,
): OmniboxHistoryEntry[] {
  const trimmed = String(title || "").trim();
  if (!trimmed) return entries;
  const key = normalizeUrlKey(url);
  let changed = false;
  const next = entries.map((entry) => {
    if (normalizeUrlKey(entry.url) !== key || entry.title === trimmed) return entry;
    changed = true;
    return { ...entry, title: trimmed };
  });
  return changed ? next : entries;
}

/** Validate persisted history (localStorage) — drop anything malformed. */
export function parseHistory(raw: unknown): OmniboxHistoryEntry[] {
  if (!Array.isArray(raw)) return [];
  const out: OmniboxHistoryEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const candidate = item as Record<string, unknown>;
    const url = typeof candidate.url === "string" ? candidate.url : "";
    if (!HTTP_RE.test(url)) continue;
    const count = Number(candidate.count);
    const lastVisited = Number(candidate.lastVisited);
    out.push({
      url,
      title: typeof candidate.title === "string" ? candidate.title : "",
      count: Number.isFinite(count) && count >= 1 ? Math.floor(count) : 1,
      lastVisited: Number.isFinite(lastVisited) && lastVisited > 0 ? lastVisited : 0,
    });
  }
  return out;
}

/**
 * Build the dropdown rows for the current input.
 *
 * Row order: the primary action first (direct navigation for URL- or
 * host-shaped input, otherwise the Google search row; host-shaped input also
 * gets the search row second), then real history matches ranked by
 * recency/frequency. Rows are deduped by normalized URL. Empty input yields
 * the top-ranked history (recents) so the dropdown never fabricates entries.
 */
export function buildSuggestions(
  input: string,
  history: OmniboxHistoryEntry[],
  options: { now?: number; limit?: number } = {},
): OmniboxSuggestion[] {
  const now = options.now ?? Date.now();
  const limit = Math.max(1, options.limit ?? 6);
  const trimmed = input.trim();
  const rows: OmniboxSuggestion[] = [];
  const seen = new Set<string>();
  const push = (row: OmniboxSuggestion) => {
    const key = row.kind === "search" ? `search:${row.url}` : normalizeUrlKey(row.url);
    if (seen.has(key)) return;
    seen.add(key);
    rows.push(row);
  };

  if (trimmed && trimmed.toLowerCase() !== "about:blank") {
    if (isUrlShaped(trimmed)) {
      push({
        id: "navigate",
        kind: "navigate",
        title: middleTruncate(trimmed, 64),
        detail: displayUrl(browserTarget(trimmed)),
        url: browserTarget(trimmed),
      });
    } else if (isHostShaped(trimmed)) {
      const host = `${trimmed.toLowerCase()}.com`;
      push({
        id: "navigate",
        kind: "navigate",
        title: host,
        detail: host,
        url: `https://${host}`,
      });
      push({
        id: "search",
        kind: "search",
        title: `Search Google for "${trimmed}"`,
        url: searchUrl(trimmed),
      });
    } else {
      push({
        id: "search",
        kind: "search",
        title: `Search Google for "${trimmed}"`,
        url: searchUrl(trimmed),
      });
    }
  }

  const query = trimmed.toLowerCase();
  const matches = history
    .filter(
      (entry) =>
        !query ||
        entry.url.toLowerCase().includes(query) ||
        entry.title.toLowerCase().includes(query),
    )
    .sort(
      (a, b) =>
        historyScore(b, now) - historyScore(a, now) || b.lastVisited - a.lastVisited,
    );
  for (const entry of matches) {
    if (rows.length >= limit) break;
    push({
      id: `history:${normalizeUrlKey(entry.url)}`,
      kind: "history",
      title: suggestionTitle(entry),
      detail: displayUrl(entry.url),
      url: entry.url,
    });
  }
  return rows.slice(0, limit);
}
