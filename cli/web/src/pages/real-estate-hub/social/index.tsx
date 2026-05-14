import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Activity,
  Award,
  Loader2,
  Megaphone,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SocialIdea, SocialMetricRow, SocialSnapshot } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  HubShell,
  useHubHeader,
  useRealEstateHubData,
  WorkflowStrip,
} from "@/pages/real-estate-hub/_shared";
import {
  IdeaCard,
  PlatformBlockCard,
  PlatformRankingsBlock,
  PlatformTablist,
  PostDetailModal,
  RealVideoCard,
  YouTubeTabView,
  computeEngagementScore,
  formatCompact,
  formatPct,
} from "@/pages/real-estate-hub/social-media-widgets";

export function RealEstateSocialMediaPage() {
  const data = useRealEstateHubData();
  useHubHeader("Social Media", data);

  const [snapshot, setSnapshot] = useState<SocialSnapshot | null>(null);
  const [ideas, setIdeas] = useState<SocialIdea[]>([]);
  const [recentPosts, setRecentPosts] = useState<SocialMetricRow[]>([]);
  const [loadingSocial, setLoadingSocial] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [socialError, setSocialError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [selectedPost, setSelectedPost] = useState<SocialMetricRow | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [postLimit, setPostLimit] = useState<number>(100);
  const [lookbackDays, setLookbackDays] = useState<number>(730);
  const tabIdPrefix = useId();
  const panelId = useId();
  const activeTabId = `${tabIdPrefix}-tab-${platformFilter}`;
  const refreshAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    const { signal } = controller;
    setLoadingSocial(true);
    setSocialError(null);
    try {
      const [snapRes, ideaRes, recentRes] = await Promise.allSettled([
        api.getSocialSnapshot(signal),
        api.getSocialIdeas("pending", signal),
        api.getSocialRecentPosts(1000, signal),
      ]);
      if (signal.aborted) return;
      if (snapRes.status === "fulfilled") setSnapshot(snapRes.value);
      if (ideaRes.status === "fulfilled") setIdeas(ideaRes.value.items || []);
      if (recentRes.status === "fulfilled") setRecentPosts(recentRes.value.items || []);
    } catch (e) {
      if (signal.aborted) return;
      setSocialError(e instanceof Error ? e.message : "Failed to load social data");
    } finally {
      if (!signal.aborted) setLoadingSocial(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      refreshAbortRef.current?.abort();
    };
  }, [refresh]);

  useEffect(() => {
    setPostLimit(100);
  }, [platformFilter]);

  const handleIdeaAction = useCallback(
    async (recordId: string, action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => {
      setActingOn(recordId);
      try {
        await api.socialIdeaAction(recordId, { action, ...(edit ? { edit } : {}) });
        await refresh();
      } catch (e) {
        setSocialError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActingOn(null);
      }
    },
    [refresh],
  );

  const totals = snapshot?.totals;
  const platforms = snapshot?.platforms || {};
  const platformList = Object.entries(platforms);

  const avgEngagement = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.engagement_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const avgHook = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.hook_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const wow = snapshot?.wow_delta;

  const platformCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of recentPosts) {
      const p = (r.platform || "").toLowerCase();
      if (!p) continue;
      counts[p] = (counts[p] || 0) + 1;
    }
    return counts;
  }, [recentPosts]);

  const filteredPosts = useMemo(() => {
    const base = recentPosts.filter(
      (r) => (r.media_type || "").toUpperCase() !== "ACCOUNT",
    );
    if (platformFilter === "all") return base;
    return base.filter((r) => (r.platform || "").toLowerCase() === platformFilter);
  }, [recentPosts, platformFilter]);

  const topPerformers = useMemo(() => {
    const scored = recentPosts
      .map((r) => ({ row: r, score: computeEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3);
    return scored.map((x) => x.row);
  }, [recentPosts]);

  const handleRefreshAll = useCallback(async () => {
    setRefreshing("all");
    setSocialError(null);
    try {
      await api.refreshSocialMetrics({ lookbackDays, maxPosts: 200 });
      await refresh();
    } catch (e) {
      setSocialError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(null);
    }
  }, [refresh, lookbackDays]);

  const summaryStats: Array<{ label: string; value: string | number }> = [
    { label: "Posts", value: totals?.post_count ?? 0 },
    { label: "Reach", value: formatCompact(totals?.reach) },
    ...(avgEngagement != null
      ? [{ label: "Avg engagement", value: formatPct(avgEngagement, 2) }]
      : []),
    ...(avgHook != null
      ? [{ label: "Avg hook rate", value: formatPct(avgHook, 2) }]
      : []),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      icon={Megaphone}
      title="Social Media · weekly content engine"
    >
      <WorkflowStrip items={summaryStats} />

      {socialError && (
        <div className="rounded-sm border border-border border-l-2 border-l-destructive bg-card px-3 py-2 text-xs text-destructive">
          {socialError}
        </div>
      )}

      {snapshot && snapshot.exists === false && (
        <Card className="border-dashed">
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            <Sparkles className="mx-auto mb-2 h-5 w-5 text-muted-foreground/60" />
            No snapshot yet. The weekly content engine runs Mondays at 7am Pacific —
            once it pulls metrics from your connected platforms, this page comes alive.
            <div className="mt-2 text-[0.7rem] text-muted-foreground/70">
              {snapshot.message ?? "Connect at least one social platform in Channels to begin."}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              AI idea approval queue
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={ideas.length ? "warning" : "success"}>{ideas.length}</Badge>
              <Button
                size="sm"
                variant="ghost"
                onClick={refresh}
                disabled={loadingSocial}
                aria-label="Refresh idea queue"
                className="min-h-[44px] min-w-[44px]"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", loadingSocial && "animate-spin")} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {loadingSocial && !ideas.length ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : ideas.length === 0 ? (
            <div className="rounded-md border border-dashed border-border bg-card px-6 py-12 text-center">
              <div className="mx-auto max-w-sm space-y-1.5">
                <h3 className="text-sm font-semibold text-foreground">No ideas waiting</h3>
                <p className="text-sm text-muted-foreground">
                  The engine queues 5–10 every Monday morning.
                </p>
              </div>
            </div>
          ) : (
            ideas.map((idea) => (
              <IdeaCard
                key={idea.source_record_id}
                idea={idea}
                busy={actingOn === idea.source_record_id}
                onAction={(action, edit) => handleIdeaAction(idea.source_record_id, action, edit)}
              />
            ))
          )}
        </CardContent>
      </Card>

      {platformList.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Award className="h-4 w-4" />
                Per-platform performance
              </CardTitle>
              {wow && (
                <div className="font-mono-ui flex items-center gap-3 text-[0.7rem] text-muted-foreground">
                  <span>
                    Posts WoW{" "}
                    <span className={wow.post_count_delta >= 0 ? "text-success" : "text-destructive"}>
                      {wow.post_count_delta >= 0 ? "+" : ""}
                      {wow.post_count_delta}
                    </span>
                  </span>
                  {wow.engagement_rate_delta != null && (
                    <span>
                      Eng WoW{" "}
                      <span className={wow.engagement_rate_delta >= 0 ? "text-success" : "text-destructive"}>
                        {wow.engagement_rate_delta >= 0 ? "+" : ""}
                        {(wow.engagement_rate_delta * 100).toFixed(2)}pp
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {platformList.map(([platform, block]) => (
                <PlatformBlockCard key={platform} platform={platform} block={block} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="space-y-1">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Activity className="h-4 w-4" />
                Your posts
              </CardTitle>
              <p className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {recentPosts.length === 0
                  ? "Nothing pulled yet"
                  : `${recentPosts.length} pulled · last ${lookbackDays} days`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="font-mono-ui flex items-center gap-1.5 text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                <span>Lookback</span>
                <select
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value))}
                  disabled={refreshing !== null}
                  aria-label="Lookback period"
                  className="font-mono-ui min-h-[44px] rounded-md border border-border bg-background px-2 text-[0.75rem] uppercase tracking-wider text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={180}>180 days</option>
                  <option value={365}>1 year</option>
                  <option value={730}>2 years</option>
                </select>
              </label>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefreshAll}
                disabled={refreshing !== null}
                className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
              >
                {refreshing ? "pulling…" : "refresh from platforms"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-8">
          {recentPosts.length > 0 && (
            <div className="border-b border-border/40 pb-4">
              <PlatformTablist
                tabs={[
                  { label: "all", count: recentPosts.length },
                  ...Object.entries(platformCounts)
                    .sort(([, a], [, b]) => b - a)
                    .map(([p, c]) => ({ label: p, count: c })),
                ]}
                active={platformFilter}
                onChange={setPlatformFilter}
                idPrefix={tabIdPrefix}
                panelId={panelId}
              />
            </div>
          )}
          <div
            id={panelId}
            role="tabpanel"
            aria-labelledby={activeTabId}
            tabIndex={0}
            className="space-y-10 focus:outline-none"
          >
            {platformFilter === "youtube" ? (
              <YouTubeTabView posts={recentPosts} onSelect={setSelectedPost} />
            ) : (
              <>
                {(["instagram", "facebook", "tiktok"].includes(platformFilter) ||
                  platformFilter === "all") && (
                  <PlatformRankingsBlock posts={filteredPosts} onSelect={setSelectedPost} />
                )}
                {filteredPosts.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border bg-card px-6 py-16 text-center">
                    <div className="mx-auto max-w-md space-y-2">
                      <h3 className="text-base font-semibold text-foreground">
                        {recentPosts.length === 0 ? "No posts pulled yet" : "Nothing here"}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {recentPosts.length === 0
                          ? "Click refresh from platforms above to pull live from every connected account."
                          : `No ${platformFilter} posts in the last ${lookbackDays} days. Connect ${platformFilter} or extend the lookback.`}
                      </p>
                    </div>
                  </div>
                ) : (
                  <section className="space-y-4" aria-labelledby="all-posts-heading">
                    <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <h3
                        id="all-posts-heading"
                        className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
                      >
                        All posts
                      </h3>
                      <span
                        className="font-mono-ui text-[0.7rem] uppercase tracking-wider tabular-nums text-muted-foreground"
                        aria-live="polite"
                      >
                        {Math.min(postLimit, filteredPosts.length)} of {filteredPosts.length}
                      </span>
                    </header>
                    <div className="grid gap-4 items-start grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
                      {(() => {
                        const topKeys = new Set(
                          platformFilter === "all"
                            ? topPerformers.map((r) => `${r.platform}:${r.post_id}`)
                            : [],
                        );
                        const ordered = [
                          ...filteredPosts.filter((r) => topKeys.has(`${r.platform}:${r.post_id}`)),
                          ...filteredPosts.filter((r) => !topKeys.has(`${r.platform}:${r.post_id}`)),
                        ];
                        return ordered.slice(0, postLimit).map((row) => (
                          <RealVideoCard
                            key={`${row.platform}:${row.post_id}`}
                            row={row}
                            onClick={() => setSelectedPost(row)}
                            highlight={topKeys.has(`${row.platform}:${row.post_id}`)}
                          />
                        ));
                      })()}
                    </div>
                    {filteredPosts.length > postLimit && (
                      <div className="mt-2 flex flex-wrap justify-center gap-2 border-t border-border/40 pt-6">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit((n) => n + 100)}
                          className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
                        >
                          Show 100 more ({filteredPosts.length - postLimit} remaining)
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit(filteredPosts.length)}
                          className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
                        >
                          Show all ({filteredPosts.length})
                        </Button>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {selectedPost && (
        <PostDetailModal row={selectedPost} onClose={() => setSelectedPost(null)} />
      )}
    </HubShell>
  );
}
