// Adapter: maps the live gateway data (SocialSnapshot + SocialMetricRow[] + SocialIdea[])
// into the shape the ported standalone board consumes. Keeps the board components
// verbatim from the prototype; all real-vs-mock reconciliation happens here.

import type { SocialIdea, SocialMetricRow, SocialSnapshot } from "@/lib/api";

export type Gran = "month" | "week" | "day";
export type Dir = "up" | "down" | "flat";

export interface DesignPost {
  id: string;
  platform: string; // "instagram" | "youtube" | ...
  kind: "reel" | "photo" | "video";
  caption: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  reach: number;
  eng: number; // engagement rate, percent
  hook: number | null; // percent, null when unknown
  ageDays: number;
  duration?: string;
  dislikes: number;
  favorites: number;
  permalink?: string | null;
  thumbnail?: string;
  postedAt?: string | null;
}

export interface KpiTile {
  id: string;
  label: string;
  value: string;
  delta: string;
  dir: Dir;
  sub: string;
  spark: number[];
}

export interface SeriesPoint {
  m: string;
  ig: number;
  yt: number;
}

export interface AnalyticsVM {
  range: string;
  kpis: Record<"all" | "instagram" | "youtube", KpiTile[]>;
  views: Record<Gran, SeriesPoint[]>;
  followers: Record<Gran, SeriesPoint[]>;
  followersAvailable: boolean;
}

export interface YtStat {
  id: string;
  label: string;
  value: string;
  sub: string;
}

export interface SocialVM {
  posts: DesignPost[];
  queue: SocialIdea[];
  analytics: AnalyticsVM;
  ytStats: YtStat[];
  postCount: number;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

function num(v: unknown): number {
  if (typeof v === "number") return Number.isFinite(v) ? v : 0;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function metric(m: Record<string, unknown> | undefined, ...keys: string[]): number {
  if (!m) return 0;
  for (const k of keys) {
    if (m[k] != null) return num(m[k]);
  }
  return 0;
}

function fmtDuration(sec: number): string {
  if (sec <= 0) return "";
  const mm = Math.floor(sec / 60);
  const ss = Math.round(sec % 60);
  return mm > 0 ? `${mm}m ${ss}s` : `${ss}s`;
}

function postViews(m: Record<string, unknown> | undefined): number {
  return metric(m, "views", "video_views", "plays", "reach", "impressions");
}

// Mirror the old widget's thumbnail resolution: IG/YT/FB fields, falling back to
// the media URL. These are signed CDN URLs that can expire — the <img onError>
// in the board swaps to the glyph placeholder when they 404.
function resolveThumbnail(raw: Record<string, unknown> | null | undefined): string | undefined {
  const r = (raw || {}) as Record<string, unknown>;
  const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);
  const fbPost = (r.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbImage = ((fbAttach?.media as Record<string, unknown> | undefined)?.image as { src?: string } | undefined)?.src;
  const yt = r.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    str(yt?.thumbnail) ||
    str((yt?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url);
  return (
    str(r.thumbnail_url) ||
    str(r.thumbnail) ||
    ytThumb ||
    str(fbPost.full_picture) ||
    str(fbImage) ||
    str(r.full_picture) ||
    str(r.media_url)
  );
}

export function toDesignPost(r: SocialMetricRow, nowMs: number): DesignPost {
  const m = r.metrics || {};
  const platform = (r.platform || "").toLowerCase();
  const mt = (r.media_type || "").toUpperCase();
  const kind: DesignPost["kind"] =
    platform === "youtube"
      ? "video"
      : mt === "IMAGE" || mt === "CAROUSEL_ALBUM"
        ? "photo"
        : "reel";

  const views = postViews(m);
  const likes = metric(m, "likes", "like_count");
  const comments = metric(m, "comments", "comments_count");
  const shares = metric(m, "shares");
  const saves = metric(m, "saved", "saves");
  const reach = metric(m, "reach", "impressions", "views", "plays");
  const ints = metric(m, "total_interactions") || likes + comments + shares + saves;
  const eng = reach > 0 ? (ints / reach) * 100 : 0;

  const postedMs = r.posted_at ? Date.parse(r.posted_at) : NaN;
  const ageDays = Number.isFinite(postedMs)
    ? Math.max(0, Math.round((nowMs - postedMs) / DAY_MS))
    : 0;

  const durSec = metric(m, "duration_sec", "video_duration");

  return {
    id: r.post_id,
    platform,
    kind,
    caption: (r.caption || "").trim() || "Untitled post",
    views,
    likes,
    comments,
    shares,
    saves,
    reach,
    eng,
    hook: null, // per-post hook rate is not exposed by the gateway; avg lives on the snapshot
    ageDays,
    duration: durSec > 0 ? fmtDuration(durSec) : undefined,
    dislikes: metric(m, "dislikes"),
    favorites: metric(m, "favorites"),
    permalink: r.permalink,
    thumbnail: resolveThumbnail(r.raw),
    postedAt: r.posted_at ?? null,
  };
}

// ── time-series bucketing (derived from real posts) ────────────────────────
interface Bucket {
  key: string;
  m: string;
  ig: number;
  yt: number;
}

function fill(
  buckets: Bucket[],
  posts: SocialMetricRow[],
  resolve: (ms: number) => string | null,
): SeriesPoint[] {
  const idx = new Map(buckets.map((b, i) => [b.key, i]));
  for (const p of posts) {
    if (!p.posted_at) continue;
    const ms = Date.parse(p.posted_at);
    if (!Number.isFinite(ms)) continue;
    const key = resolve(ms);
    const i = key == null ? undefined : idx.get(key);
    if (i == null) continue;
    const v = postViews(p.metrics);
    if ((p.platform || "").toLowerCase() === "youtube") buckets[i].yt += v;
    else buckets[i].ig += v;
  }
  return buckets.map(({ m, ig, yt }) => ({ m, ig, yt }));
}

function monthSeries(posts: SocialMetricRow[], nowMs: number): SeriesPoint[] {
  const now = new Date(nowMs);
  const buckets: Bucket[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    buckets.push({ key: `${d.getFullYear()}-${d.getMonth()}`, m: MONTHS[d.getMonth()], ig: 0, yt: 0 });
  }
  return fill(buckets, posts, (ms) => {
    const d = new Date(ms);
    return `${d.getFullYear()}-${d.getMonth()}`;
  });
}

function weekSeries(posts: SocialMetricRow[], nowMs: number): SeriesPoint[] {
  // last 10 weeks, week-ending boundaries
  const buckets: Bucket[] = [];
  const ends: number[] = [];
  for (let i = 9; i >= 0; i--) {
    const end = nowMs - i * 7 * DAY_MS;
    ends.push(end);
    const d = new Date(end);
    buckets.push({ key: `w${9 - i}`, m: `${d.getMonth() + 1}/${d.getDate()}`, ig: 0, yt: 0 });
  }
  return fill(buckets, posts, (ms) => {
    for (let i = 0; i < ends.length; i++) {
      const start = ends[i] - 7 * DAY_MS;
      if (ms > start && ms <= ends[i]) return `w${i}`;
    }
    return null;
  });
}

function daySeries(posts: SocialMetricRow[], nowMs: number): SeriesPoint[] {
  const buckets: Bucket[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(nowMs - i * DAY_MS);
    buckets.push({ key: `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`, m: String(d.getDate()), ig: 0, yt: 0 });
  }
  return fill(buckets, posts, (ms) => {
    const d = new Date(ms);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  });
}

// ── KPI tiles (derived from real posts, enriched by snapshot when present) ──
function compactNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1000) {
    const v = n / 1000;
    return (v >= 10 ? Math.round(v) : v.toFixed(1).replace(/\.0$/, "")) + "k";
  }
  return String(Math.round(n));
}

// Account-level insights arrive in mixed shapes: a scalar (YouTube subscriber_count),
// or a Graph API time-series array like [{ value, end_time }] (Instagram follower_count).
// Unwrap to the most recent numeric value.
function coerceMetricValue(v: unknown): number {
  if (Array.isArray(v)) {
    const last = v[v.length - 1];
    if (last && typeof last === "object" && "value" in last) return num((last as { value: unknown }).value);
    return num(last);
  }
  if (v && typeof v === "object" && "value" in (v as object)) return num((v as { value: unknown }).value);
  return num(v);
}

function accountMetricValue(
  snapshot: SocialSnapshot | null,
  platform: string,
  keys: string[],
): number | null {
  const am = snapshot?.account_metrics?.[platform];
  if (!am) return null;
  for (const k of keys) {
    if (am[k] != null) {
      const n = coerceMetricValue(am[k]);
      if (n > 0) return n;
    }
  }
  return null;
}

function buildKpis(
  scope: "all" | "instagram" | "youtube",
  posts: DesignPost[],
  rawPosts: SocialMetricRow[],
  snapshot: SocialSnapshot | null,
  nowMs: number,
): KpiTile[] {
  const isYt = scope === "youtube";
  const totalViews = posts.reduce((s, p) => s + p.views, 0);
  const totalReach = rawPosts.reduce((s, p) => s + metric(p.metrics, "reach", "impressions", "views"), 0);
  const totalInts = posts.reduce((s, p) => s + p.likes + p.comments + p.shares + p.saves, 0);
  const eng = totalReach > 0 ? (totalInts / totalReach) * 100 : 0;

  const monthly = monthSeries(rawPosts, nowMs);
  const viewSpark = monthly.map((d) => (isYt ? d.yt : scope === "instagram" ? d.ig : d.ig + d.yt));

  const wow = snapshot?.wow_delta;
  const engDelta =
    wow?.engagement_rate_delta != null
      ? { delta: `${wow.engagement_rate_delta >= 0 ? "+" : ""}${(wow.engagement_rate_delta * 100).toFixed(2)}pt`, dir: (wow.engagement_rate_delta >= 0 ? "up" : "down") as Dir }
      : { delta: "—", dir: "flat" as Dir };
  const postDelta =
    wow?.post_count_delta != null
      ? { delta: `${wow.post_count_delta >= 0 ? "+" : ""}${wow.post_count_delta}`, dir: (wow.post_count_delta >= 0 ? "up" : "down") as Dir }
      : { delta: "—", dir: "flat" as Dir };

  const follow = isYt
    ? accountMetricValue(snapshot, "youtube", ["subscribers", "subscriber_count", "subscribers_count"])
    : accountMetricValue(snapshot, "instagram", ["followers", "followers_count", "follower_count"]);

  const lifeViews = isYt ? accountMetricValue(snapshot, "youtube", ["channel_views", "views", "view_count"]) : null;

  return [
    {
      id: "posts",
      label: "Posts pulled",
      value: String(posts.length),
      delta: postDelta.delta,
      dir: postDelta.dir,
      sub: scope === "all" ? "Across all channels" : isYt ? "YouTube" : "Instagram",
      spark: monthly.map((d) => (isYt ? d.yt : scope === "instagram" ? d.ig : d.ig + d.yt) > 0 ? 1 : 0),
    },
    {
      id: "views",
      label: "Total views",
      value: compactNum(totalViews),
      delta: lifeViews != null ? compactNum(lifeViews) + " life" : "—",
      dir: "flat",
      sub: "Reels + feed plays",
      spark: viewSpark,
    },
    {
      id: "eng",
      label: "Engagement rate",
      value: eng.toFixed(2) + "%",
      delta: engDelta.delta,
      dir: engDelta.dir,
      sub: "Interactions / reach",
      spark: monthly.map((d, i) => {
        const v = isYt ? d.yt : scope === "instagram" ? d.ig : d.ig + d.yt;
        return v > 0 ? eng * (0.85 + (i / monthly.length) * 0.3) : 0;
      }),
    },
    {
      id: isYt ? "subs" : "followers",
      label: isYt ? "Subscribers" : "Followers",
      value: follow != null ? compactNum(follow) : "—",
      delta: "—",
      dir: "flat",
      sub: follow != null ? "Lifetime" : "Connect account",
      spark: follow != null ? [follow] : [0],
    },
  ];
}

function buildYtStats(snapshot: SocialSnapshot | null, ytPosts: DesignPost[]): YtStat[] {
  const subs = accountMetricValue(snapshot, "youtube", ["subscribers", "subscriber_count"]);
  const cviews = accountMetricValue(snapshot, "youtube", ["channel_views", "views", "view_count"]);
  const vids = accountMetricValue(snapshot, "youtube", ["video_count", "videos"]);
  const comments = ytPosts.reduce((s, p) => s + p.comments, 0);
  return [
    { id: "subs", label: "Subscribers", value: subs != null ? compactNum(subs) : "—", sub: "Lifetime" },
    { id: "cviews", label: "Channel views", value: cviews != null ? compactNum(cviews) : "—", sub: "Lifetime" },
    { id: "vids", label: "Videos", value: vids != null ? String(vids) : ytPosts.length ? String(ytPosts.length) : "—", sub: "Published" },
    {
      id: "cmts",
      label: "Comments pulled",
      value: comments > 0 ? String(comments) : "—",
      sub: ytPosts.length ? `Across ${ytPosts.length} video${ytPosts.length === 1 ? "" : "s"}` : "No videos yet",
    },
  ];
}

export function buildSocialViewModel(
  snapshot: SocialSnapshot | null,
  ideas: SocialIdea[],
  rawPosts: SocialMetricRow[],
  lookbackDays: number,
  nowMs: number,
): SocialVM {
  const realPosts = rawPosts.filter((r) => (r.media_type || "").toUpperCase() !== "ACCOUNT");
  const posts = realPosts.map((r) => toDesignPost(r, nowMs));
  const ytPosts = posts.filter((p) => p.platform === "youtube");

  const followers = {
    month: monthSeries(realPosts, nowMs).map((d) => ({ m: d.m, ig: 0, yt: 0 })),
    week: weekSeries(realPosts, nowMs).map((d) => ({ m: d.m, ig: 0, yt: 0 })),
    day: daySeries(realPosts, nowMs).map((d) => ({ m: d.m, ig: 0, yt: 0 })),
  };

  const analytics: AnalyticsVM = {
    range: `Last ${lookbackDays >= 365 ? Math.round(lookbackDays / 365) + "y" : lookbackDays + "d"}`,
    kpis: {
      all: buildKpis("all", posts, realPosts, snapshot, nowMs),
      instagram: buildKpis("instagram", posts.filter((p) => p.platform === "instagram"), realPosts.filter((r) => (r.platform || "").toLowerCase() === "instagram"), snapshot, nowMs),
      youtube: buildKpis("youtube", ytPosts, realPosts.filter((r) => (r.platform || "").toLowerCase() === "youtube"), snapshot, nowMs),
    },
    views: {
      month: monthSeries(realPosts, nowMs),
      week: weekSeries(realPosts, nowMs),
      day: daySeries(realPosts, nowMs),
    },
    followers,
    followersAvailable: false, // gateway does not pull follower history yet
  };

  return {
    posts,
    queue: ideas,
    analytics,
    ytStats: buildYtStats(snapshot, ytPosts),
    postCount: posts.length,
  };
}
