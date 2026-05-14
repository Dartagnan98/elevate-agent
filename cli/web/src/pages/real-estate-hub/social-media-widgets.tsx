import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Activity,
  Clock,
  ExternalLink,
  Loader2,
  PencilLine,
  ThumbsDown,
  ThumbsUp,
  Video,
} from "lucide-react";
import type { SocialIdea, SocialMetricRow, SocialPlatformBlock } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, isoTimeAgo } from "@/lib/utils";

export function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function formatPct(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

// Total/cumulative time fields — show as hours. Returned in ms unless noted.
const MS_TOTAL_TIME_KEYS = new Set([
  "ig_reels_video_view_total_time",
  "post_video_view_time_organic",
]);
const MIN_TOTAL_TIME_KEYS = new Set([
  "estimated_minutes_watched", // YouTube — minutes
]);
// Per-view averages — show as seconds (hours would be too small to read).
const MS_AVG_TIME_KEYS = new Set([
  "ig_reels_avg_watch_time",
  "post_video_avg_time_watched",
]);
const SEC_AVG_TIME_KEYS = new Set([
  "avg_view_duration_sec",
]);
const PCT_KEYS = new Set([
  "engagement_rate",
  "hook_rate",
  "hold_rate",
  "avg_view_percentage",
]);

function formatHours(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0h";
  const h = ms / 3_600_000;
  if (h >= 100) return `${h.toFixed(0)}h`;
  if (h >= 10) return `${h.toFixed(1)}h`;
  if (h >= 1) return `${h.toFixed(2)}h`;
  // Sub-hour totals — degrade gracefully so we never claim "0h" on a real value.
  const m = ms / 60_000;
  if (m >= 1) return `${m.toFixed(1)}m`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatSeconds(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

function formatIsoDuration(iso: string): string {
  // PT#H#M#S → "1h 23m 4s"
  const re = /PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?/;
  const m = iso.match(re);
  if (!m) return iso;
  const [, h, mm, s] = m;
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (mm) parts.push(`${mm}m`);
  if (s) parts.push(`${Math.round(Number(s))}s`);
  return parts.join(" ") || "0s";
}

function prettifyMetricKey(key: string): string {
  const map: Record<string, string> = {
    likes: "likes",
    comments: "comments",
    shares: "shares",
    saved: "saves",
    views: "views",
    reach: "reach",
    plays: "plays",
    impressions: "impressions",
    total_interactions: "total interactions",
    profile_visits: "profile visits",
    profile_activity: "profile activity",
    follows: "follows",
    navigation: "navigation",
    replies: "replies",
    ig_reels_video_view_total_time: "total watch time",
    ig_reels_avg_watch_time: "avg watch time",
    post_video_view_time_organic: "total watch time",
    post_video_avg_time_watched: "avg watch time",
    avg_view_duration_sec: "avg watch time",
    avg_view_percentage: "avg view %",
    estimated_minutes_watched: "total watch time",
    duration_iso: "duration",
    view_count: "views",
    like_count: "likes",
    comment_count: "comments",
    dislike_count: "dislikes",
    favorite_count: "favorites",
    engagement_rate: "engagement rate",
    hook_rate: "hook rate",
    hold_rate: "hold rate",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function formatMetricValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") {
    if (key === "duration_iso" && value.startsWith("PT")) return formatIsoDuration(value);
    return value;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (PCT_KEYS.has(key)) return `${(value * 100).toFixed(1)}%`;
  if (MS_TOTAL_TIME_KEYS.has(key)) return formatHours(value);
  if (MIN_TOTAL_TIME_KEYS.has(key)) return formatHours(value * 60_000);
  if (MS_AVG_TIME_KEYS.has(key)) return formatSeconds(value);
  if (SEC_AVG_TIME_KEYS.has(key)) return formatSeconds(value * 1000);
  return formatCompact(value);
}

function platformDot(platform: string): string {
  const map: Record<string, string> = {
    instagram: "bg-[oklch(0.62_0.14_350)]",
    tiktok: "bg-[oklch(0.65_0.13_15)]",
    youtube: "bg-[oklch(0.58_0.16_30)]",
    facebook: "bg-[oklch(0.58_0.13_245)]",
    linkedin: "bg-[oklch(0.55_0.13_240)]",
  };
  return map[platform.toLowerCase()] ?? "bg-muted-foreground";
}

export function IdeaCard({
  idea,
  onAction,
  busy,
}: {
  idea: SocialIdea;
  onAction: (action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => Promise<void>;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Partial<SocialIdea>>({
    hook: idea.hook,
    concept: idea.concept,
    best_post_time: idea.best_post_time ?? "",
    target_audience: idea.target_audience ?? "",
  });

  const grounded = idea.grounded_in || {};
  const chipTone = "bg-background text-foreground border-border";
  const groundedChips = [
    grounded.metric ? { label: "metric", text: grounded.metric, tone: chipTone } : null,
    grounded.trend ? { label: "trend", text: grounded.trend, tone: chipTone } : null,
    grounded.signal ? { label: "signal", text: grounded.signal, tone: chipTone } : null,
  ].filter((x): x is { label: string; text: string; tone: string } => !!x);

  return (
    <div className="space-y-3 border-b border-border/40 pb-5 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", platformDot(idea.platform))} />
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {idea.platform} · {idea.format}
        </span>
        {idea.best_post_time && (
          <Badge variant="outline" className="text-[0.65rem]">
            <Clock className="mr-1 h-3 w-3" />
            {idea.best_post_time}
          </Badge>
        )}
      </div>

      {editing ? (
        <div className="space-y-2">
          <input
            value={draft.hook ?? ""}
            onChange={(e) => setDraft({ ...draft, hook: e.target.value })}
            placeholder="Hook (first 3 seconds)"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium"
          />
          <textarea
            value={draft.concept ?? ""}
            onChange={(e) => setDraft({ ...draft, concept: e.target.value })}
            placeholder="Concept"
            rows={3}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              value={(draft.best_post_time as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, best_post_time: e.target.value })}
              placeholder="Best post time"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
            <input
              value={(draft.target_audience as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, target_audience: e.target.value })}
              placeholder="Target audience"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
        </div>
      ) : (
        <>
          <div className="text-sm font-semibold leading-snug text-foreground">{idea.hook}</div>
          <p className="text-xs leading-5 text-muted-foreground">{idea.concept}</p>
          {idea.outline && idea.outline.length > 0 && (
            <ol className="text-xs leading-5 text-muted-foreground space-y-0.5 pl-4 list-decimal">
              {idea.outline.slice(0, 4).map((beat, i) => (
                <li key={i}>{beat}</li>
              ))}
            </ol>
          )}
        </>
      )}

      {groundedChips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {groundedChips.map((chip) => (
            <span
              key={chip.label}
              className={cn(
                "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-[0.65rem] font-medium",
                chip.tone,
              )}
              title={chip.text}
            >
              <span className="font-mono-ui uppercase tracking-wider">{chip.label}</span>
              <span className="max-w-[16rem] truncate">{chip.text}</span>
            </span>
          ))}
        </div>
      )}

      {idea.reasoning && !editing && (
        <p className="text-[0.75rem] italic leading-5 text-muted-foreground">
          {idea.reasoning}
        </p>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {idea.timestamp ? isoTimeAgo(idea.timestamp) : ""}
        </div>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={async () => {
                  await onAction("edit", draft);
                  setEditing(false);
                }}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save edit"}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(true)}
                disabled={busy}
                aria-label="Edit idea"
                className="min-h-[44px] min-w-[44px]"
              >
                <PencilLine className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onAction("reject")}
                disabled={busy}
                aria-label="Reject idea"
                className="min-h-[44px] min-w-[44px] text-destructive hover:text-destructive"
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                onClick={() => onAction("approve")}
                disabled={busy}
                aria-label="Approve idea"
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
                <span className="ml-1">Approve</span>
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
function ytNum(row: SocialMetricRow, key: string): number {
  const v = (row.metrics as Record<string, unknown>)?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function ytEngagementScore(row: SocialMetricRow): number {
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const views = ytNum(row, "view_count");
  if (views <= 0) return 0;
  return (likes + comments * 2) / views;
}

export function YouTubeTabView({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  const ytAll = useMemo(
    () => posts.filter((p) => (p.platform || "").toLowerCase() === "youtube"),
    [posts],
  );
  const channelRow = useMemo(
    () => ytAll.find((p) => (p.media_type || "").toUpperCase() === "ACCOUNT"),
    [ytAll],
  );
  const videos = useMemo(
    () => ytAll.filter((p) => (p.media_type || "").toUpperCase() !== "ACCOUNT"),
    [ytAll],
  );
  const sumComments = useMemo(
    () => videos.reduce((a, r) => a + ytNum(r, "comment_count"), 0),
    [videos],
  );

  const channelMetrics = (channelRow?.metrics ?? {}) as Record<string, unknown>;
  const subCount =
    typeof channelMetrics.subscriber_count === "number" ? channelMetrics.subscriber_count : null;
  const channelViews =
    typeof channelMetrics.view_count === "number" ? channelMetrics.view_count : null;
  const videoCount =
    typeof channelMetrics.video_count === "number" ? channelMetrics.video_count : null;

  const rankings = useMemo(() => {
    const top = (key: string) =>
      [...videos]
        .sort((a, b) => ytNum(b, key) - ytNum(a, key))
        .filter((r) => ytNum(r, key) > 0)
        .slice(0, 3);
    const eng = [...videos]
      .map((r) => ({ row: r, score: ytEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...videos]
      .filter((r) => ytNum(r, "view_count") > 0)
      .sort((a, b) => ytNum(a, "view_count") - ytNum(b, "view_count"))
      .slice(0, 3);
    return {
      views: top("view_count"),
      likes: top("like_count"),
      comments: top("comment_count"),
      engagement: eng,
      least,
    };
  }, [videos]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <YouTubeStatTile label="Subscribers" value={formatCompact(subCount)} hint="lifetime" />
        <YouTubeStatTile label="Channel views" value={formatCompact(channelViews)} hint="lifetime" />
        <YouTubeStatTile label="Videos" value={formatCompact(videoCount)} hint="published" />
        <YouTubeStatTile
          label="Comments (pulled)"
          value={formatCompact(sumComments)}
          hint={`across ${videos.length} videos`}
        />
      </div>

      {videos.length > 0 && (
        <section aria-labelledby="yt-rankings-heading" className="space-y-3">
          <div className="flex items-center gap-2">
            <h3
              id="yt-rankings-heading"
              className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
            >
              Rankings
            </h3>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
            <RankPanel
              title="Most views"
              rows={rankings.views}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most likes"
              rows={rankings.likes}
              formatValue={(r) => formatCompact(ytNum(r, "like_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most comments"
              rows={rankings.comments}
              formatValue={(r) => formatCompact(ytNum(r, "comment_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most engagement"
              rows={rankings.engagement}
              formatValue={(r) => `${(ytEngagementScore(r) * 100).toFixed(2)}%`}
              onSelect={onSelect}
            />
            <RankPanel
              title="Least views"
              rows={rankings.least}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
              tone="muted"
            />
          </div>
        </section>
      )}

      {videos.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No YouTube videos pulled yet. Click "refresh from platforms" above to pull the channel.
        </p>
      ) : (
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
          {videos
            .slice()
            .sort((a, b) => ytNum(b, "view_count") - ytNum(a, "view_count"))
            .map((row) => (
              <YouTubeVideoCard
                key={`${row.platform}:${row.post_id}`}
                row={row}
                onClick={() => onSelect(row)}
              />
            ))}
        </div>
      )}
    </div>
  );
}

function YouTubeStatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <div className="font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-foreground tabular-nums">{value}</div>
      {hint && (
        <div className="mt-0.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground/70">
          {hint}
        </div>
      )}
    </div>
  );
}

function RankPanel({
  title,
  rows,
  formatValue,
  onSelect,
  tone,
}: {
  title: string;
  rows: SocialMetricRow[];
  formatValue: (row: SocialMetricRow) => string;
  onSelect: (row: SocialMetricRow) => void;
  tone?: "muted";
}) {
  return (
    <div className="rounded-md bg-card p-3 space-y-2">
      <div
        className={cn(
          "font-mono-ui text-[0.7rem] uppercase tracking-wider",
          tone === "muted" ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {title}
      </div>
      {rows.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">No data yet</p>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((row, idx) => (
            <li key={`${row.post_id}-${idx}`}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                aria-label={`Rank ${idx + 1}: ${row.caption || "untitled"}, ${formatValue(row)}`}
                className="group flex min-h-[44px] w-full items-center gap-2 rounded-sm border border-border bg-card px-2.5 py-2 text-left transition hover:border-ring focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
              >
                <span className="font-mono-ui w-4 text-center text-[0.7rem] text-muted-foreground">
                  {idx + 1}
                </span>
                <span className="flex-1 truncate text-[0.8rem] text-foreground">
                  {row.caption || "(untitled)"}
                </span>
                <span className="font-mono-ui text-[0.75rem] tabular-nums text-foreground">
                  {formatValue(row)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-platform metric resolver. Each platform names the same concept
// differently — IG uses `likes`/`saved`/`shares`, FB uses `like_count`/
// `reaction_count`/`comments_count`, TikTok uses `digg_count`/`play_count`/
// `share_count`/`save_count`. Read in priority order; first hit wins.
// ---------------------------------------------------------------------------
const METRIC_LOOKUP: Record<string, string[]> = {
  views: [
    "views", "view_count", "plays", "play_count", "video_views",
    "post_video_views", "post_impressions",
  ],
  likes: ["likes", "like_count", "reaction_count", "digg_count"],
  comments: ["comments", "comment_count", "comments_count"],
  shares: ["shares", "share_count"],
  saves: ["saved", "saves", "save_count"],
  reach: ["reach"],
};

function readMetric(row: SocialMetricRow, logical: string): number {
  const m = (row.metrics || {}) as Record<string, unknown>;
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  for (const key of METRIC_LOOKUP[logical] || []) {
    for (const src of [m, raw, fbPost]) {
      const v = src[key];
      if (typeof v === "number" && Number.isFinite(v)) return v;
      if (typeof v === "string") {
        const n = Number(v);
        if (Number.isFinite(n)) return n;
      }
    }
  }
  return 0;
}

function genericEngagement(row: SocialMetricRow): number {
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const saves = readMetric(row, "saves");
  const views = readMetric(row, "views");
  const total = likes + comments * 2 + shares * 3 + saves * 2;
  if (views > 0) return total / views;
  return 0;
}

function totalActivity(row: SocialMetricRow): number {
  return (
    readMetric(row, "likes") +
    readMetric(row, "comments") +
    readMetric(row, "shares") +
    readMetric(row, "saves")
  );
}

// Hook rate = % of people who watched after seeing the post.
// IG: views / reach. FB: post_video_views / post_impressions.
// TikTok Display API and YouTube Data API don't expose impressions/reach.
function derivedHookRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hook_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const views = readMetric(row, "views");
    const reach = readMetric(row, "reach");
    if (views > 0 && reach > 0) return Math.min(views / reach, 1);
    return null;
  }
  if (platform === "facebook") {
    const videoViews = Number(m.post_video_views) || 0;
    const impressions =
      Number(m.post_impressions) || Number(m.post_impressions_unique) || 0;
    if (videoViews > 0 && impressions > 0) return Math.min(videoViews / impressions, 1);
    return null;
  }
  return null;
}

// Hold rate = % of the video the average viewer watched.
// IG: ig_reels_avg_watch_time (ms) / duration_sec. Requires `duration` in fetcher.
// FB needs a separate /video?fields=length lookup (not yet wired).
// TikTok Display API has no avg_watch_time. YouTube Analytics API not exposed.
function derivedHoldRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hold_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const avgMs = Number(m.ig_reels_avg_watch_time) || 0;
    const durSec = Number(m.duration_sec ?? m.duration) || 0;
    if (avgMs > 0 && durSec > 0) return Math.min(avgMs / (durSec * 1000), 1);
    return null;
  }
  if (platform === "facebook") {
    // post_video_avg_time_watched is in milliseconds; need video length to ratio.
    const avgMs = Number(m.post_video_avg_time_watched) || 0;
    const raw = (row.raw || {}) as Record<string, unknown>;
    const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
    const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)
      ?.data as Array<Record<string, unknown>> | undefined)?.[0];
    const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
    const fbSrc = fbMedia.source as string | undefined;
    const lengthSec =
      Number((fbAttach as Record<string, unknown> | undefined)?.video_length) ||
      Number(fbMedia.length) ||
      0;
    if (avgMs > 0 && lengthSec > 0 && fbSrc) {
      return Math.min(avgMs / (lengthSec * 1000), 1);
    }
    return null;
  }
  return null;
}

export function PlatformRankingsBlock({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  // YouTube has its own block; ACCOUNT rows aren't posts.
  const eligible = useMemo(
    () =>
      posts.filter(
        (p) =>
          (p.platform || "").toLowerCase() !== "youtube" &&
          (p.media_type || "").toUpperCase() !== "ACCOUNT",
      ),
    [posts],
  );

  const panels = useMemo(() => {
    const top = (logical: string) =>
      [...eligible]
        .sort((a, b) => readMetric(b, logical) - readMetric(a, logical))
        .filter((r) => readMetric(r, logical) > 0)
        .slice(0, 3);
    const eng = [...eligible]
      .map((r) => ({ row: r, score: genericEngagement(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...eligible]
      .filter((r) => totalActivity(r) > 0)
      .sort((a, b) => totalActivity(a) - totalActivity(b))
      .slice(0, 3);

    const fmtCount = (key: string) => (r: SocialMetricRow) => formatCompact(readMetric(r, key));
    return [
      { title: "Most views", rows: top("views"), format: fmtCount("views") },
      { title: "Most likes", rows: top("likes"), format: fmtCount("likes") },
      { title: "Most comments", rows: top("comments"), format: fmtCount("comments") },
      { title: "Most shares", rows: top("shares"), format: fmtCount("shares") },
      { title: "Most saves", rows: top("saves"), format: fmtCount("saves") },
      {
        title: "Most engagement",
        rows: eng,
        format: (r: SocialMetricRow) => `${(genericEngagement(r) * 100).toFixed(2)}%`,
      },
      {
        title: "Least performing",
        rows: least,
        format: (r: SocialMetricRow) => `${formatCompact(totalActivity(r))} ints`,
        tone: "muted" as const,
      },
    ].filter((p) => p.rows.length > 0);
  }, [eligible]);

  if (!panels.length) return null;

  return (
    <section aria-labelledby="rankings-heading" className="space-y-3">
      <h3
        id="rankings-heading"
        className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
      >
        Rankings
      </h3>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {panels.map((panel) => (
          <RankPanel
            key={panel.title}
            title={panel.title}
            rows={panel.rows}
            formatValue={panel.format}
            onSelect={onSelect}
            tone={panel.tone}
          />
        ))}
      </div>
    </section>
  );
}

function YouTubeVideoCard({
  row,
  onClick,
}: {
  row: SocialMetricRow;
  onClick: () => void;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb;
  const m = (row.metrics || {}) as Record<string, unknown>;
  const caption = row.caption || "";
  const isShort = (row.media_type || "").toUpperCase() === "SHORT";
  const duration = m.duration_iso as string | undefined;

  const views = ytNum(row, "view_count");
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const engagement = ytEngagementScore(row);

  const skipKeys = new Set([
    "view_count",
    "like_count",
    "comment_count",
    "duration_iso",
    "avg_view_duration_sec",
    "avg_view_percentage",
  ]);
  const extraChips: Array<{ label: string; value: string }> = [];
  for (const [k, v] of Object.entries(m)) {
    if (k.startsWith("_") || skipKeys.has(k)) continue;
    if (v == null) continue;
    if (typeof v !== "number" && typeof v !== "string") continue;
    extraChips.push({ label: prettifyMetricKey(k), value: formatMetricValue(k, v) });
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col text-left rounded-md border border-border bg-card overflow-hidden transition hover:border-ring"
    >
      <div className="relative aspect-video w-full bg-card">
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Video className="h-8 w-8" />
          </div>
        )}
        <div className="absolute top-1.5 left-1.5 flex items-center gap-1 rounded-sm bg-card border border-border px-2 py-0.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", platformDot("youtube"))} />
          <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground">
            {isShort ? "short" : "video"}
          </span>
        </div>
        {duration && (
          <div className="absolute bottom-1.5 right-1.5 rounded bg-card border border-border/60 px-1.5 py-0.5 font-mono-ui text-[0.7rem] tabular-nums text-foreground">
            {formatIsoDuration(duration)}
          </div>
        )}
        {engagement > 0 && (
          <div
            className="absolute top-1.5 right-1.5 rounded bg-primary px-1.5 py-0.5 font-mono-ui text-[0.7rem] uppercase tracking-wider text-primary-foreground"
            aria-label={`Engagement ${(engagement * 100).toFixed(2)} percent`}
          >
            {(engagement * 100).toFixed(2)}% eng
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
          {caption || "(untitled)"}
        </h3>
        <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
        </div>
        <div className="grid grid-cols-3 gap-1.5 pt-1">
          <YouTubeMetricCell label="views" value={formatCompact(views)} />
          <YouTubeMetricCell label="likes" value={formatCompact(likes)} />
          <YouTubeMetricCell label="comments" value={formatCompact(comments)} />
        </div>
        {extraChips.length > 0 && (
          <div className="font-mono-ui flex flex-wrap gap-x-2 gap-y-0.5 pt-1 text-[0.7rem] text-muted-foreground">
            {extraChips.map((chip, i) => (
              <span key={`${chip.label}-${i}`} className="whitespace-nowrap">
                {chip.value}
                <span className="ml-0.5 text-muted-foreground">{chip.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

function YouTubeMetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/40 bg-card px-2 py-1">
      <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

export function PlatformTablist({
  tabs,
  active,
  onChange,
  idPrefix,
  panelId,
}: {
  tabs: Array<{ label: string; count: number }>;
  active: string;
  onChange: (label: string) => void;
  idPrefix: string;
  panelId: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const handleKey = (idx: number) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End")
      return;
    e.preventDefault();
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    onChange(tabs[next].label);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="Filter posts by platform" className="flex flex-wrap items-center gap-1.5 pt-1">
      {tabs.map((t, i) => (
        <PlatformTab
          key={t.label}
          ref={(el) => {
            refs.current[i] = el;
          }}
          id={`${idPrefix}-tab-${t.label}`}
          label={t.label}
          count={t.count}
          active={active === t.label}
          onClick={() => onChange(t.label)}
          onKeyDown={handleKey(i)}
          controlsId={panelId}
        />
      ))}
    </div>
  );
}

const PlatformTab = forwardRef<HTMLButtonElement, {
  id: string;
  label: string;
  active: boolean;
  count: number;
  onClick: () => void;
  onKeyDown?: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  controlsId?: string;
}>(function PlatformTab({ id, label, active, count, onClick, onKeyDown, controlsId }, ref) {
  return (
    <button
      ref={ref}
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={controlsId}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex min-h-[44px] items-center gap-1.5 rounded-sm border px-3 py-2 font-mono-ui text-[0.75rem] uppercase tracking-wider transition focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring",
        active
          ? "border-primary bg-muted text-foreground"
          : "border-border bg-card text-muted-foreground hover:border-ring hover:text-foreground",
      )}
    >
      {label !== "all" && (
        <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", platformDot(label))} />
      )}
      <span>{label}</span>
      <span className="text-muted-foreground">{count}</span>
    </button>
  );
});

// Single source of truth — delegates to the cross-platform readers so IG/FB/TT/YT
// rank consistently. Adds a tiny activity tiebreaker so two posts with identical
// rates don't shuffle randomly.
export function computeEngagementScore(row: SocialMetricRow): number {
  const score = genericEngagement(row);
  const activity = totalActivity(row);
  if (score > 0) return score * 100 + activity * 0.001;
  return activity;
}

export function PostDetailModal({ row, onClose }: { row: SocialMetricRow; onClose: () => void }) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const m = (row.metrics || {}) as Record<string, unknown>;
  const page = (m._page as string | undefined) || "";
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  // Hook/hold render as their own row above the grid; drop the raw fields
  // from the grid so we don't show them twice.
  const metricEntries = Object.entries(m).filter(
    ([k]) => !k.startsWith("_") && k !== "hook_rate" && k !== "hold_rate",
  );

  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (root) {
      const first = root.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      (first ?? root).focus();
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && root) {
        const focusable = Array.from(
          root.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => !el.hasAttribute("aria-hidden"));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocused.current?.focus?.();
    };
  }, [onClose]);

  const headingText = caption
    ? caption.split("\n")[0].slice(0, 120)
    : `${row.platform || "Post"} detail`;
  const platformLabel = (row.platform || "").toString();
  const isFbLandscape = platformLabel.toLowerCase() === "facebook";
  const [linkCopied, setLinkCopied] = useState(false);
  const handleCopyLink = useCallback(async () => {
    if (!row.permalink) return;
    try {
      await navigator.clipboard.writeText(row.permalink);
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 1600);
    } catch {
      // clipboard blocked; ignore
    }
  }, [row.permalink]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/85 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-md border border-border bg-card outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close post detail"
          className="absolute right-3 top-3 z-10 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-sm bg-background px-3 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
        >
          close
        </button>
        <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div
            className={cn(
              "relative bg-card md:aspect-auto md:min-h-[480px]",
              isFbLandscape ? "aspect-[4/5]" : "aspect-[9/16]",
            )}
          >
            {thumb ? (
              <img
                src={thumb}
                alt={caption ? caption.slice(0, 100) : ""}
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div
                aria-hidden="true"
                className="absolute inset-0 flex items-center justify-center text-muted-foreground/40"
              >
                <Activity className="h-8 w-8" />
              </div>
            )}
            <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-sm bg-card border border-border px-2.5 py-1">
              <span
                aria-hidden="true"
                className={cn("h-2 w-2 rounded-full", platformDot(row.platform))}
              />
              <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground">
                {platformLabel || "post"}
              </span>
            </div>
          </div>
          <div className="space-y-4 p-5">
            <div>
              <h2
                id={titleId}
                className="text-base font-semibold leading-snug text-foreground"
              >
                {headingText}
              </h2>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {page && <span>{page}</span>}
                <span>
                  {row.posted_at ? new Date(row.posted_at).toLocaleString() : "—"}
                </span>
              </div>
              {row.permalink && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <a
                    href={row.permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="Open original post in new tab"
                    className="font-mono-ui inline-flex min-h-[44px] items-center px-3 text-[0.7rem] uppercase tracking-wider text-primary hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
                  >
                    open ↗
                  </a>
                  <button
                    type="button"
                    onClick={handleCopyLink}
                    aria-label="Copy post link to clipboard"
                    aria-live="polite"
                    className="font-mono-ui inline-flex min-h-[44px] items-center rounded-md border border-border bg-background px-3 text-[0.7rem] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
                  >
                    {linkCopied ? "copied" : "copy link"}
                  </button>
                </div>
              )}
            </div>
            {caption && caption !== headingText && (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {caption}
              </p>
            )}
            {(engagementRate != null || hookRate != null || holdRate != null) && (
              <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-t border-border pt-3 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {engagementRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(engagementRate * 100).toFixed(2)}%
                    </span>{" "}
                    engagement
                  </span>
                )}
                {hookRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(hookRate * 100).toFixed(1)}%
                    </span>{" "}
                    hook
                  </span>
                )}
                {holdRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(holdRate * 100).toFixed(1)}%
                    </span>{" "}
                    hold
                  </span>
                )}
              </div>
            )}
            {metricEntries.length > 0 ? (
              <div>
                <div className="mb-2 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                  Metrics
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {metricEntries.map(([k, v]) => (
                    <div key={k} className="rounded-sm border border-border bg-card px-3 py-2">
                      <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                        {prettifyMetricKey(k)}
                      </div>
                      <div className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
                        {formatMetricValue(k, v)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="px-1 py-1 text-xs text-muted-foreground/80">No metrics returned for this post yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function RealVideoCard({
  row,
  onClick,
  highlight,
}: {
  row: SocialMetricRow;
  onClick?: () => void;
  highlight?: boolean;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const m = (row.metrics || {}) as Record<string, unknown>;
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const captionDisplay = caption.trim() || "Untitled post";

  // Two metrics max — pick the most meaningful for this row.
  // Video: views + likes. Static: likes + comments. Story: reach + replies.
  const views = readMetric(row, "views");
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const candidates: Array<[string, number]> = [
    ["views", views],
    ["likes", likes],
    ["comments", comments],
    ["shares", shares],
  ];
  const topMetrics = candidates.filter(([, v]) => v > 0).slice(0, 2);

  // Pick a single rate to show — hold > hook > engagement (descending priority of insight value).
  const primaryRate: { label: string; value: number } | null =
    holdRate != null
      ? { label: "hold", value: holdRate }
      : hookRate != null
        ? { label: "hook", value: hookRate }
        : engagementRate != null
          ? { label: "eng", value: engagementRate }
          : null;

  const handleClick = (e: ReactMouseEvent) => {
    if (onClick) {
      e.preventDefault();
      onClick();
    }
  };

  const platform = (row.platform || "").toLowerCase();
  const mediaType = (row.media_type || "").toUpperCase();
  // Vertical for Reels/Shorts/TikTok; square for static FB/IG photo posts.
  const isVertical =
    platform === "tiktok" ||
    mediaType === "REEL" ||
    mediaType === "REELS" ||
    mediaType === "VIDEO" ||
    mediaType === "SHORT" ||
    mediaType === "STORY";
  const aspectClass = isVertical ? "aspect-[9/16]" : "aspect-square";

  const Inner = (
    <div className="space-y-2">
      <div
        className={cn(
          "relative overflow-hidden rounded-md bg-card border transition",
          aspectClass,
          highlight ? "border-primary" : "border-border group-hover:border-ring",
        )}
      >
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Activity className="h-6 w-6" />
          </div>
        )}
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-2 left-2 h-2 w-2 rounded-full ring-2 ring-background",
            platformDot(row.platform),
          )}
          title={row.platform}
        />
      </div>
      <div className="space-y-1">
        <p className="line-clamp-2 text-[0.8rem] leading-snug text-foreground">
          {captionDisplay}
        </p>
        {topMetrics.length > 0 && (
          <div className="flex items-baseline gap-3 text-[0.72rem] text-muted-foreground">
            {topMetrics.map(([label, value]) => (
              <span key={label} className="whitespace-nowrap">
                <span className="font-medium tabular-nums text-foreground">
                  {formatCompact(value)}
                </span>{" "}
                {label}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between text-[0.7rem] text-muted-foreground">
          <span className="font-mono-ui uppercase tracking-wider">
            {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
          </span>
          {primaryRate && (
            <span className="font-mono-ui tabular-nums uppercase tracking-wider text-foreground">
              {(primaryRate.value * 100).toFixed(1)}% {primaryRate.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="group block w-full text-left focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ring rounded-md"
      >
        {Inner}
      </button>
    );
  }
  return row.permalink ? (
    <a
      href={row.permalink}
      target="_blank"
      rel="noopener noreferrer"
      className="group block focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ring rounded-md"
    >
      {Inner}
    </a>
  ) : (
    <div>{Inner}</div>
  );
}

export function PlatformBlockCard({
  platform,
  block,
}: {
  platform: string;
  block: SocialPlatformBlock;
}) {
  const { totals, averages, top_posts, post_count } = block;
  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", platformDot(platform))} />
          <span className="font-mono-ui text-[0.8rem] uppercase tracking-wider text-foreground">
            {platform}
          </span>
        </div>
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {post_count} posts
        </span>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatCompact(totals?.reach)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Reach
          </div>
        </div>
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatPct(averages?.engagement_rate, 2)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Engagement
          </div>
        </div>
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatPct(averages?.hook_rate ?? averages?.hold_rate, 2)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            {averages?.hook_rate != null ? "Hook" : "Hold"}
          </div>
        </div>
      </div>

      {top_posts && top_posts.length > 0 && (
        <div className="space-y-1">
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Top performers
          </div>
          <ul className="space-y-0.5">
            {top_posts.slice(0, 3).map((p) => (
              <li key={p.post_id}>
                <a
                  href={p.permalink ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-1 py-1 text-[0.8rem] text-foreground hover:text-primary"
                >
                  <span className="flex-1 truncate">{p.caption || "(no caption)"}</span>
                  <span className="font-mono-ui text-[0.7rem] tabular-nums text-muted-foreground">
                    {formatPct(p.derived?.engagement_rate, 1)}
                  </span>
                  {p.permalink && <ExternalLink className="h-3 w-3 text-muted-foreground" />}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
