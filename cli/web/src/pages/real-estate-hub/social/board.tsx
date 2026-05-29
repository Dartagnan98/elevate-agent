// Social Media board — content engine analytics.
// Ported verbatim from the standalone prototype (Hero · AI idea queue ·
// platform-filtered posts with rankings/grid · YouTube channel view), rewired
// to consume the live view-model instead of window.SOCIAL_* globals.

import { useEffect, useMemo, useState, type SVGProps, type SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import type { SocialIdea } from "@/lib/api";
import type {
  AnalyticsVM,
  DesignPost,
  Gran,
  KpiTile,
  SeriesPoint,
  SocialVM,
  YtStat,
} from "./view-model";

// ── ranking definitions (static, as in the prototype) ───────────────
interface RankDef {
  id: string;
  label: string;
  metric: keyof DesignPost | "ints";
  order: "asc" | "desc";
  fmt: "num" | "pct" | "ints";
}
const RANKINGS_ALL: RankDef[] = [
  { id: "views", label: "Most views", metric: "views", order: "desc", fmt: "num" },
  { id: "likes", label: "Most likes", metric: "likes", order: "desc", fmt: "num" },
  { id: "cmts", label: "Most comments", metric: "comments", order: "desc", fmt: "num" },
  { id: "shares", label: "Most shares", metric: "shares", order: "desc", fmt: "num" },
  { id: "saves", label: "Most saves", metric: "saves", order: "desc", fmt: "num" },
  { id: "eng", label: "Most engagement", metric: "eng", order: "desc", fmt: "pct" },
  { id: "least", label: "Least performing", metric: "ints", order: "asc", fmt: "ints" },
];
const RANKINGS_YT: RankDef[] = [
  { id: "views", label: "Most views", metric: "views", order: "desc", fmt: "num" },
  { id: "likes", label: "Most likes", metric: "likes", order: "desc", fmt: "num" },
  { id: "cmts", label: "Most comments", metric: "comments", order: "desc", fmt: "num" },
  { id: "eng", label: "Most engagement", metric: "eng", order: "desc", fmt: "pct" },
  { id: "lviews", label: "Least views", metric: "views", order: "asc", fmt: "num" },
];

// ── helpers ─────────────────────────────────────────────────────────
type PostWithInts = DesignPost & { ints: number };

function fmtViews(n: number): string {
  if (n >= 1000) {
    const v = n / 1000;
    return (v >= 10 ? Math.round(v) : Number(v.toFixed(1))) + "k";
  }
  return String(n);
}
function withInts(p: DesignPost): PostWithInts {
  return { ...p, ints: p.likes + p.comments + p.shares + p.saves };
}
function rankValue(p: PostWithInts, r: RankDef): number {
  if (r.metric === "ints") return p.ints;
  return Number(p[r.metric] ?? 0);
}
function fmtMetric(p: PostWithInts, r: RankDef): string {
  if (r.fmt === "pct") return p.eng.toFixed(2) + "%";
  if (r.fmt === "ints") return p.ints + " int" + (p.ints === 1 ? "" : "s");
  return fmtViews(rankValue(p, r));
}

// ── tiny svg icons (inline, matches Today's stroke style) ───────────
const ico =
  (paths: string[], sw = 1.6) =>
  (props: SVGProps<SVGSVGElement>) => (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      width="14"
      height="14"
      {...props}
    >
      {paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
const IcoActivity = ico(["M22 12h-4l-3 9L9 3l-3 9H2"]);
const IcoRefresh = ico(["M3 12a9 9 0 0 1 15.5-6.3L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-15.5 6.3L3 16", "M3 21v-5h5"]);
const IcoSparkles = ico(["M12 3l1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6z", "M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"]);
const IcoEye = ico(["M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"]);
const IcoHeart = ico(["M19.5 4.6a5 5 0 0 0-7 .2L12 5.3l-.5-.5a5 5 0 0 0-7.1 7l.6.6L12 20l7-7.1.6-.6a5 5 0 0 0-.1-7.7z"]);
const IcoComment = ico(["M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.9-.9L3 21l1.9-5A8.4 8.4 0 1 1 21 11.5z"]);
const IcoPlay = ico(["M5 3.5v17l14-8.5z"], 1.4);
const IcoImage = ico(["M3 5h18v14H3z", "M3 16l5-5 4 4 3-3 6 6", "M9 9a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0z"], 1.5);
const IcoChevDown = ico(["M6 9l6 6 6-6"]);
const IcoBars = ico(["M3 21V10", "M9 21V4", "M15 21V14", "M21 21V8"]);

const PLAT_LABEL: Record<string, string> = { instagram: "Instagram", youtube: "YouTube" };

// Header lives in the app breadcrumb bar (title + gateway status + job count +
// Refresh), wired via useHubHeader — no separate in-page hero, matching Memory
// and the other hub pages.

// ─────────────────────────────────────────────────────────────────
// AI IDEA APPROVAL QUEUE
// ─────────────────────────────────────────────────────────────────
function IdeaItem({
  idea,
  busy,
  onAction,
}: {
  idea: SocialIdea;
  busy: boolean;
  onAction: (id: string, action: "approve" | "reject") => void;
}) {
  const platform = (idea.platform || "").toLowerCase();
  return (
    <article className="sm-idea">
      <div className="sm-idea-head">
        {(platform === "instagram" || platform === "youtube") && <span className={"sm-dot " + platform} />}
        <span className="sm-idea-format mono">{idea.format || idea.platform}</span>
        {idea.best_post_time && <span className="sm-idea-time mono">{idea.best_post_time}</span>}
      </div>
      <div className="sm-idea-hook">{idea.hook || idea.title || "Untitled idea"}</div>
      {idea.concept && <div className="sm-idea-concept">{idea.concept}</div>}
      {idea.grounded_in?.signal && (
        <div className="sm-idea-ground mono">Grounded in: {idea.grounded_in.signal}</div>
      )}
      <div className="sm-idea-actions">
        <button className="ab-btn ghost" type="button" disabled={busy} onClick={() => onAction(idea.source_record_id, "reject")}>
          Reject
        </button>
        <button className="ab-btn primary" type="button" disabled={busy} onClick={() => onAction(idea.source_record_id, "approve")}>
          Approve
        </button>
      </div>
    </article>
  );
}

function IdeaQueue({
  items,
  onRefresh,
  onAction,
  actingId,
  loading,
}: {
  items: SocialIdea[];
  onRefresh: () => void;
  onAction: (id: string, action: "approve" | "reject") => void;
  actingId: string | null;
  loading: boolean;
}) {
  return (
    <section className="ab-card sm-card">
      <div className="ab-card-head">
        <span className="sm-card-icon">
          <IcoSparkles width="13" height="13" />
        </span>
        <span className="ab-card-title">AI idea approval queue</span>
        <div className="ab-card-actions">
          <span className={"sm-count" + (items.length ? " hot" : "")}>{items.length}</span>
          <button className="sm-icon-btn" title="Refresh queue" onClick={onRefresh}>
            <IcoRefresh width="13" height="13" />
          </button>
        </div>
      </div>
      <div className="sm-queue-body">
        {items.length === 0 ? (
          <div className="sm-empty">
            <div className="sm-empty-mark">
              <IcoSparkles width="15" height="15" />
            </div>
            <div className="sm-empty-text">
              <div className="sm-empty-title">{loading ? "Loading ideas…" : "No ideas waiting"}</div>
              <div className="sm-empty-sub">The engine queues 5–10 fresh concepts every Monday morning.</div>
            </div>
            <button className="ab-btn ghost" type="button" onClick={onRefresh}>
              <IcoSparkles width="13" height="13" />
              Generate now
            </button>
          </div>
        ) : (
          <div className="sm-queue-list">
            {items.map((idea) => (
              <IdeaItem
                key={idea.source_record_id}
                idea={idea}
                busy={actingId === idea.source_record_id}
                onAction={onAction}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// ANALYTICS — KPI tiles + bar charts
// ─────────────────────────────────────────────────────────────────
function MiniSpark({ values, dir }: { values: number[]; dir: string }) {
  const w = 88;
  const h = 26;
  const safe = values && values.length ? values : [0];
  const min = Math.min(...safe);
  const max = Math.max(...safe);
  const span = max - min || 1;
  const stepX = safe.length > 1 ? w / (safe.length - 1) : w;
  const pts = safe.map((v, i) => {
    const x = safe.length === 1 ? w / 2 : i * stepX;
    const y = h - ((v - min) / span) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = dir === "down" ? "var(--status-error)" : dir === "flat" ? "var(--fg-faint)" : "var(--status-done)";
  return (
    <svg className="sm-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polygon fill={color} opacity="0.1" points={`0,${h} ${pts.join(" ")} ${w},${h}`} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" points={pts.join(" ")} />
    </svg>
  );
}

function AnalyticsKpi({ k }: { k: KpiTile }) {
  return (
    <div className="sm-an-kpi">
      <div className="sm-an-kpi-top">
        <span className="sm-an-kpi-label mono">{k.label}</span>
        <span className={"sm-an-kpi-delta mono " + k.dir}>{k.delta}</span>
      </div>
      <div className="sm-an-kpi-mid">
        <span className="sm-an-kpi-value">{k.value}</span>
        <MiniSpark values={k.spark} dir={k.dir} />
      </div>
      <div className="sm-an-kpi-sub mono">{k.sub}</div>
    </div>
  );
}

const GRANS: { id: Gran; short: string; noun: string }[] = [
  { id: "month", short: "M", noun: "month" },
  { id: "week", short: "W", noun: "week" },
  { id: "day", short: "D", noun: "day" },
];

function GranToggle({ gran, setGran }: { gran: Gran; setGran: (g: Gran) => void }) {
  return (
    <div className="sm-gran" role="group" aria-label="Granularity">
      {GRANS.map((g) => (
        <button
          key={g.id}
          className={gran === g.id ? "active" : ""}
          aria-pressed={gran === g.id}
          title={"By " + g.noun}
          onClick={() => setGran(g.id)}
        >
          {g.short}
        </button>
      ))}
    </div>
  );
}

function ViewsChart({ data, channel }: { data: Record<Gran, SeriesPoint[]>; channel: string }) {
  const H = 150;
  const [gran, setGran] = useState<Gran>("month");
  const noun = (GRANS.find((g) => g.id === gran) || GRANS[0]).noun;
  const series = useMemo(
    () =>
      (data[gran] || []).map((d) => ({
        m: d.m,
        ig: channel === "youtube" ? 0 : d.ig,
        yt: channel === "instagram" ? 0 : d.yt,
      })),
    [data, gran, channel],
  );
  const max = useMemo(() => Math.max(1, ...series.map((d) => d.ig + d.yt)), [series]);
  const stacked = channel === "all";
  return (
    <div className="sm-chart">
      <div className="sm-chart-head">
        <div className="sm-chart-title">Views by {noun}</div>
        <div className="sm-chart-controls">
          {stacked ? (
            <div className="sm-legend">
              <span className="sm-legend-item mono">
                <span className="sm-dot instagram" />
                Instagram
              </span>
              <span className="sm-legend-item mono">
                <span className="sm-dot youtube" />
                YouTube
              </span>
            </div>
          ) : (
            <div className="sm-legend">
              <span className="sm-legend-item mono">
                <span className={"sm-dot " + channel} />
                {PLAT_LABEL[channel]}
              </span>
            </div>
          )}
          <GranToggle gran={gran} setGran={setGran} />
        </div>
      </div>
      <div className="sm-bars" style={{ height: H + 28 + "px" }}>
        {series.map((d, i) => {
          const total = d.ig + d.yt;
          const colH = Math.max(2, (total / max) * H);
          const igH = total ? (d.ig / total) * colH : 0;
          const ytH = total ? (d.yt / total) * colH : 0;
          return (
            <div className="sm-bar-col" key={d.m + i}>
              <span className="sm-bar-val mono">{fmtViews(total)}</span>
              <div
                className={"sm-bar-stack" + (channel === "youtube" ? " solo-yt" : "")}
                style={{ height: colH + "px" }}
                title={`${d.m}: ${fmtViews(total)} views`}
              >
                {ytH > 0 && <div className="sm-bar-seg yt" style={{ height: ytH + "px" }} />}
                {igH > 0 && <div className="sm-bar-seg ig" style={{ height: igH + "px" }} />}
              </div>
              <span className={"sm-bar-label mono" + (i === series.length - 1 ? " now" : "")}>{d.m}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FollowersChart({
  data,
  channel,
  available,
}: {
  data: Record<Gran, SeriesPoint[]>;
  channel: string;
  available: boolean;
}) {
  const H = 150;
  const [gran, setGran] = useState<Gran>("month");
  const series = useMemo(
    () =>
      (data[gran] || []).map((d) => ({
        m: d.m,
        n: channel === "instagram" ? d.ig : channel === "youtube" ? d.yt : d.ig + d.yt,
      })),
    [data, gran, channel],
  );
  const max = useMemo(() => Math.max(1, ...series.map((d) => d.n)), [series]);
  const total = useMemo(() => series.reduce((s, d) => s + d.n, 0), [series]);
  const title = channel === "youtube" ? "New subscribers" : "New followers";
  const range = gran === "month" ? "this year" : gran === "week" ? "last 10 wks" : "last 14 days";
  return (
    <div className="sm-chart">
      <div className="sm-chart-head">
        <div className="sm-chart-title">{title}</div>
        <div className="sm-chart-controls">
          {available && <div className="sm-chart-sub mono">+{total.toLocaleString()} {range}</div>}
          <GranToggle gran={gran} setGran={setGran} />
        </div>
      </div>
      {available ? (
        <div className="sm-bars" style={{ height: H + 28 + "px" }}>
          {series.map((d, i) => {
            const colH = Math.max(2, (d.n / max) * H);
            const isNow = i === series.length - 1;
            return (
              <div className="sm-bar-col" key={d.m + i}>
                <span className="sm-bar-val mono">{d.n}</span>
                <div
                  className={"sm-bar-single" + (isNow ? " now" : "") + (channel === "youtube" ? " yt" : "")}
                  style={{ height: colH + "px" }}
                  title={`${d.m}: +${d.n}`}
                />
                <span className={"sm-bar-label mono" + (isNow ? " now" : "")}>{d.m}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="sm-chart-empty" style={{ height: H + 28 + "px" }}>
          <span className="sm-chart-empty-text mono">
            Follower history populates after the weekly gateway pull.
          </span>
        </div>
      )}
    </div>
  );
}

function Analytics({ data }: { data: AnalyticsVM }) {
  const [channel, setChannel] = useState<"all" | "instagram" | "youtube">("all");
  const kpis = data.kpis[channel] || data.kpis.all;
  const scopes: { id: "all" | "instagram" | "youtube"; label: string }[] = [
    { id: "all", label: "All channels" },
    { id: "instagram", label: "Instagram" },
    { id: "youtube", label: "YouTube" },
  ];
  const meta =
    channel === "all"
      ? "Aggregated across all channels"
      : channel === "instagram"
        ? "Instagram channel"
        : "YouTube channel";
  return (
    <section className="sm-section sm-an">
      <div className="sm-section-head">
        <div className="sm-section-title">
          <span className="sm-section-icon">
            <IcoBars width="14" height="14" />
          </span>
          <div>
            <div className="sm-section-name">Performance</div>
            <div className="sm-section-meta mono">{meta}</div>
          </div>
        </div>
        <div className="sm-section-actions">
          <span className="sm-select">
            {data.range}
            <IcoChevDown width="11" height="11" />
          </span>
        </div>
      </div>

      <div className="sm-tabs" role="tablist">
        {scopes.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={channel === s.id}
            className={"sm-tab" + (channel === s.id ? " active" : "")}
            onClick={() => setChannel(s.id)}
          >
            {s.id !== "all" && <span className={"sm-dot " + s.id} />}
            <span>{s.label}</span>
          </button>
        ))}
      </div>

      <div className="sm-an-kpis">
        {kpis.map((k) => (
          <AnalyticsKpi key={k.id} k={k} />
        ))}
      </div>

      <div className="sm-an-grid">
        <ViewsChart data={data.views} channel={channel} />
        <FollowersChart data={data.followers} channel={channel} available={data.followersAvailable} />
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// RANKINGS
// ─────────────────────────────────────────────────────────────────
function RankCard({ rank, posts }: { rank: RankDef; posts: PostWithInts[] }) {
  const ranked = useMemo(() => {
    const arr = [...posts].sort((a, b) =>
      rank.order === "asc" ? rankValue(a, rank) - rankValue(b, rank) : rankValue(b, rank) - rankValue(a, rank),
    );
    return arr.slice(0, 3);
  }, [posts, rank]);
  return (
    <div className="sm-rank">
      <div className="sm-rank-label mono">{rank.label}</div>
      <ol className="sm-rank-list">
        {ranked.map((p, i) => (
          <li className="sm-rank-row" key={p.id}>
            <span className="sm-rank-n mono">{i + 1}</span>
            <span className="sm-rank-cap">{p.caption}</span>
            <span className="sm-rank-val mono">{fmtMetric(p, rank)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Rankings({ defs, posts }: { defs: RankDef[]; posts: PostWithInts[] }) {
  return (
    <div className="sm-block">
      <div className="sm-block-label mono">Rankings</div>
      <div className="sm-rank-grid">
        {defs.map((r) => (
          <RankCard key={r.id} rank={r} posts={posts} />
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// POST CARD (instagram / mixed grid)
// ─────────────────────────────────────────────────────────────────
function hideOnError(e: SyntheticEvent<HTMLImageElement>) {
  e.currentTarget.style.display = "none";
}

function PostMedia({ post }: { post: DesignPost }) {
  const isVideo = post.kind !== "photo";
  return (
    <div className="sm-media" data-platform={post.platform}>
      <span className="sm-media-glyph">{isVideo ? <IcoPlay width="22" height="22" /> : <IcoImage width="20" height="20" />}</span>
      {post.thumbnail && (
        <img className="sm-media-img" src={post.thumbnail} alt="" loading="lazy" onError={hideOnError} />
      )}
      <span className={"sm-dot " + post.platform} title={PLAT_LABEL[post.platform]} />
      {post.duration && <span className="sm-dur mono">{post.duration}</span>}
    </div>
  );
}

function PostCard({ post, onSelect }: { post: DesignPost; onSelect: (p: DesignPost) => void }) {
  return (
    <article
      className="sm-post"
      role="button"
      tabIndex={0}
      onClick={() => onSelect(post)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(post);
        }
      }}
    >
      <PostMedia post={post} />
      <div className="sm-post-cap">{post.caption}</div>
      <div className="sm-post-metrics mono">
        <span>
          <IcoEye width="11" height="11" />
          {fmtViews(post.views)}
        </span>
        <span>
          <IcoHeart width="11" height="11" />
          {post.likes}
        </span>
        {post.comments > 0 && (
          <span>
            <IcoComment width="11" height="11" />
            {post.comments}
          </span>
        )}
      </div>
      <div className="sm-post-foot mono">
        <span>{post.ageDays}d ago</span>
        <span className="sm-hook">{post.hook != null ? post.hook.toFixed(0) + "% hook" : ""}</span>
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────────────
// YOUTUBE VIDEO CARD
// ─────────────────────────────────────────────────────────────────
function VideoCard({ post, onSelect }: { post: DesignPost; onSelect: (p: DesignPost) => void }) {
  return (
    <article
      className="sm-video"
      role="button"
      tabIndex={0}
      onClick={() => onSelect(post)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(post);
        }
      }}
    >
      <div className="sm-video-media">
        {post.thumbnail ? (
          <img className="sm-media-img" src={post.thumbnail} alt="" loading="lazy" onError={hideOnError} />
        ) : (
          <span className="sm-video-watermark">POV</span>
        )}
        <span className="sm-video-tag mono">
          <span className="sm-dot youtube" />
          Video
        </span>
        <span className="sm-video-eng mono">{post.eng.toFixed(2)}% eng</span>
        {post.duration && <span className="sm-dur mono">{post.duration}</span>}
        <span className="sm-video-play">
          <IcoPlay width="18" height="18" />
        </span>
      </div>
      <div className="sm-video-body">
        <div className="sm-video-title">{post.caption}</div>
        <div className="sm-video-age mono">{post.ageDays}d ago</div>
        <div className="sm-video-stats">
          <div className="sm-vstat">
            <span className="sm-vstat-label mono">Views</span>
            <span className="sm-vstat-val">{post.views}</span>
          </div>
          <div className="sm-vstat">
            <span className="sm-vstat-label mono">Likes</span>
            <span className="sm-vstat-val">{post.likes}</span>
          </div>
          <div className="sm-vstat">
            <span className="sm-vstat-label mono">Comments</span>
            <span className="sm-vstat-val">{post.comments}</span>
          </div>
        </div>
        <div className="sm-video-foot mono">
          {post.dislikes} dislikes · {post.favorites} favorites
        </div>
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────────────
// YOUTUBE CHANNEL STAT TILES
// ─────────────────────────────────────────────────────────────────
function ChannelStats({ stats }: { stats: YtStat[] }) {
  return (
    <div className="sm-yt-stats">
      {stats.map((s) => (
        <div className="sm-stat" key={s.id}>
          <div className="sm-stat-label mono">{s.label}</div>
          <div className={"sm-stat-value" + (s.value === "—" ? " dim" : "")}>{s.value}</div>
          <div className="sm-stat-sub mono">{s.sub}</div>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// YOUR POSTS SECTION (tabs + body)
// ─────────────────────────────────────────────────────────────────
function YourPosts({
  posts,
  ytStats,
  lookbackDays,
  onLookback,
  onRefreshAll,
  refreshing,
  onSelect,
}: {
  posts: DesignPost[];
  ytStats: YtStat[];
  lookbackDays: number;
  onLookback: (days: number) => void;
  onRefreshAll: () => void;
  refreshing: boolean;
  onSelect: (p: DesignPost) => void;
}) {
  // Lookback actually filters the view (posts within the last N days), not just
  // the label. The Refresh pill re-pulls the same window from the gateway.
  const all = useMemo(
    () => posts.filter((p) => p.ageDays <= lookbackDays).map(withInts),
    [posts, lookbackDays],
  );
  const counts = useMemo(
    () => ({
      all: all.length,
      instagram: all.filter((p) => p.platform === "instagram").length,
      youtube: all.filter((p) => p.platform === "youtube").length,
    }),
    [all],
  );

  const [tab, setTab] = useState<"all" | "instagram" | "youtube">("all");
  const visible = useMemo(() => (tab === "all" ? all : all.filter((p) => p.platform === tab)), [all, tab]);

  const tabs: { id: "all" | "instagram" | "youtube"; label: string; n: number }[] = [
    { id: "all", label: "All", n: counts.all },
    { id: "instagram", label: "Instagram", n: counts.instagram },
    { id: "youtube", label: "YouTube", n: counts.youtube },
  ];

  const isYT = tab === "youtube";
  const rankDefs = isYT ? RANKINGS_YT : RANKINGS_ALL;

  return (
    <section className="sm-section">
      <div className="sm-section-head">
        <div className="sm-section-title">
          <span className="sm-section-icon">
            <IcoActivity width="14" height="14" />
          </span>
          <div>
            <div className="sm-section-name">Your posts</div>
            <div className="sm-section-meta mono">
              {visible.length} pulled · last {lookbackDays} days
            </div>
          </div>
        </div>
        <div className="sm-section-actions">
          <label className="sm-lookback mono">
            Lookback
            <span className="sm-select sm-select-native">
              <select value={lookbackDays} onChange={(e) => onLookback(Number(e.target.value))} aria-label="Lookback period">
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
                <option value={180}>180 days</option>
                <option value={365}>1 year</option>
                <option value={730}>2 years</option>
              </select>
              <IcoChevDown width="11" height="11" />
            </span>
          </label>
          <button type="button" className="ab-pill" onClick={onRefreshAll} disabled={refreshing}>
            <IcoRefresh width="12" height="12" />
            {refreshing ? "Pulling…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="sm-tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={"sm-tab" + (tab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.id !== "all" && <span className={"sm-dot " + t.id} />}
            <span>{t.label}</span>
            <span className="sm-tab-n mono">{t.n}</span>
          </button>
        ))}
      </div>

      {isYT && <ChannelStats stats={ytStats} />}

      {visible.length > 0 && <Rankings defs={rankDefs} posts={visible} />}

      <div className="sm-block">
        <div className="sm-block-head">
          <div className="sm-block-label mono">{isYT ? "Videos" : "All posts"}</div>
          <div className="sm-block-count mono">
            {visible.length} of {counts.all}
          </div>
        </div>
        {visible.length === 0 ? (
          <p className="sm-block-empty mono">
            No {tab === "all" ? "" : tab + " "}posts in the last {lookbackDays} days. Connect a channel or extend the lookback, then Refresh.
          </p>
        ) : isYT ? (
          <div className="sm-video-grid">
            {visible.map((p) => (
              <VideoCard key={p.id} post={p} onSelect={onSelect} />
            ))}
          </div>
        ) : (
          <div className="sm-post-grid">
            {visible.map((p) => (
              <PostCard key={p.id} post={p} onSelect={onSelect} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// POST DETAIL MODAL (opens on card click)
// ─────────────────────────────────────────────────────────────────
function ModalStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="sm-modal-stat">
      <span className="sm-modal-stat-label mono">{label}</span>
      <span className="sm-modal-stat-val">{value}</span>
    </div>
  );
}

function PostDetailModal({ post, onClose }: { post: DesignPost; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isVideo = post.kind !== "photo";
  const label = PLAT_LABEL[post.platform] || post.platform;
  // Portal to <body> so the overlay escapes .elevate-route-transition's transform
  // (a transformed ancestor makes position:fixed anchor to it, not the viewport,
  // which is why the modal drifted with scroll). The .sm-root wrapper re-applies
  // the scoped design tokens + styles outside the page subtree.
  return createPortal(
    <div className="sm-root">
      <div className="sm-modal-overlay" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="sm-modal" onClick={(e) => e.stopPropagation()}>
        <button className="sm-modal-close" type="button" onClick={onClose} aria-label="Close">
          ×
        </button>
        <div className="sm-modal-media" data-platform={post.platform}>
          <span className="sm-media-glyph">{isVideo ? <IcoPlay width="30" height="30" /> : <IcoImage width="26" height="26" />}</span>
          {post.thumbnail && <img className="sm-media-img" src={post.thumbnail} alt="" onError={hideOnError} />}
          {post.duration && <span className="sm-dur mono">{post.duration}</span>}
        </div>
        <div className="sm-modal-body">
          <div className="sm-modal-head">
            <span className={"sm-dot " + post.platform} />
            <span className="mono">{label}</span>
            <span className="sm-modal-age mono">{post.ageDays}d ago</span>
          </div>
          <p className="sm-modal-cap">{post.caption}</p>
          <div className="sm-modal-stats">
            <ModalStat label="Views" value={fmtViews(post.views)} />
            <ModalStat label="Reach" value={fmtViews(post.reach)} />
            <ModalStat label="Likes" value={String(post.likes)} />
            <ModalStat label="Comments" value={String(post.comments)} />
            <ModalStat label="Shares" value={String(post.shares)} />
            <ModalStat label="Saves" value={String(post.saves)} />
            <ModalStat label="Engagement" value={post.eng.toFixed(2) + "%"} />
            {post.platform === "youtube" && <ModalStat label="Favorites" value={String(post.favorites)} />}
          </div>
          {post.permalink && (
            <a className="ab-btn primary sm-modal-link" href={post.permalink} target="_blank" rel="noreferrer">
              View on {label}
            </a>
          )}
        </div>
      </div>
      </div>
    </div>,
    document.body,
  );
}

// ─────────────────────────────────────────────────────────────────
// MAIN BOARD
// ─────────────────────────────────────────────────────────────────
export function SocialBoard({
  vm,
  refreshing,
  loadingIdeas,
  actingId,
  lookbackDays,
  onRefresh,
  onRefreshAll,
  onLookback,
  onIdeaAction,
}: {
  vm: SocialVM;
  refreshing: boolean;
  loadingIdeas: boolean;
  actingId: string | null;
  lookbackDays: number;
  onRefresh: () => void;
  onRefreshAll: () => void;
  onLookback: (days: number) => void;
  onIdeaAction: (id: string, action: "approve" | "reject") => void;
}) {
  const [selected, setSelected] = useState<DesignPost | null>(null);
  return (
    <main className="admin-board sm-board">
      <div className="sm-board-body">
        <p className="sm-sub">
          Weekly content engine runs <strong>Monday 7am Pacific</strong>. Connect a social platform in Channels to expand this view.
        </p>
        <IdeaQueue items={vm.queue} onRefresh={onRefresh} onAction={onIdeaAction} actingId={actingId} loading={loadingIdeas} />
        <Analytics data={vm.analytics} />
        <YourPosts
          posts={vm.posts}
          ytStats={vm.ytStats}
          lookbackDays={lookbackDays}
          onLookback={onLookback}
          onRefreshAll={onRefreshAll}
          refreshing={refreshing}
          onSelect={setSelected}
        />
      </div>
      {selected && <PostDetailModal post={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
