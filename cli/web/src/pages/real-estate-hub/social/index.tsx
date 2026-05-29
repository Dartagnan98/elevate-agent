import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { SocialIdea, SocialMetricRow, SocialSnapshot } from "@/lib/api";
import { useHubHeader, useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { SocialBoard } from "./board";
import { buildSocialViewModel } from "./view-model";
import "./social.css";

export function RealEstateSocialMediaPage() {
  const data = useRealEstateHubData();

  const [snapshot, setSnapshot] = useState<SocialSnapshot | null>(null);
  const [ideas, setIdeas] = useState<SocialIdea[]>([]);
  const [recentPosts, setRecentPosts] = useState<SocialMetricRow[]>([]);
  const [loadingSocial, setLoadingSocial] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [socialError, setSocialError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lookbackDays, setLookbackDays] = useState<number>(730);
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
      // allSettled never rejects, so surface a banner when every source failed.
      if (
        snapRes.status === "rejected" &&
        ideaRes.status === "rejected" &&
        recentRes.status === "rejected"
      ) {
        const reason = snapRes.reason;
        setSocialError(reason instanceof Error ? reason.message : "Failed to load social data");
      }
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

  const handleIdeaAction = useCallback(
    async (recordId: string, action: "approve" | "reject") => {
      setActingOn(recordId);
      setSocialError(null);
      try {
        await api.socialIdeaAction(recordId, { action });
        await refresh();
      } catch (e) {
        setSocialError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActingOn(null);
      }
    },
    [refresh],
  );

  const handleRefreshAll = useCallback(async () => {
    setRefreshing(true);
    setSocialError(null);
    try {
      await api.refreshSocialMetrics({ lookbackDays, maxPosts: 200 });
      await refresh();
    } catch (e) {
      setSocialError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }, [refresh, lookbackDays]);

  const vm = useMemo(
    () => buildSocialViewModel(snapshot, ideas, recentPosts, lookbackDays, Date.now()),
    [snapshot, ideas, recentPosts, lookbackDays],
  );

  // Title + gateway status + job count + Refresh all live in the breadcrumb bar
  // (no separate in-page hero), matching Memory and the other hub pages.
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;
  useHubHeader("Social Media", data, {
    onRefresh: refresh,
    refreshing: loadingSocial,
    afterExtra: (
      <>
        <span className="text-muted-foreground/45">·</span>
        <span>
          {activeJobs} job{activeJobs === 1 ? "" : "s"}
        </span>
      </>
    ),
  });

  return (
    <div className="sm-root">
      {socialError && <div className="sm-error mono">{socialError}</div>}
      <SocialBoard
        vm={vm}
        refreshing={refreshing}
        loadingIdeas={loadingSocial}
        actingId={actingOn}
        lookbackDays={lookbackDays}
        onRefresh={refresh}
        onRefreshAll={handleRefreshAll}
        onLookback={setLookbackDays}
        onIdeaAction={handleIdeaAction}
      />
    </div>
  );
}
