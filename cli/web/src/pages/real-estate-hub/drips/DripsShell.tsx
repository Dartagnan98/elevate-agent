import { useEffect, useState } from "react";
import { Droplets, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { DripCampaign, DripVideo } from "@/lib/api";
import { LoadingState } from "@/pages/real-estate-hub/_shared";
import { cn } from "@/lib/utils";
import { BoardView } from "./components/board-view";
import { CampaignDetail } from "./components/campaign-detail";
import { CampaignsView } from "./components/campaigns-view";
import { EnrollDialog } from "./components/enroll-dialog";
import { SegmentsView } from "./components/segments-view";
import { SettingsView } from "./components/settings-view";
import { Note, Stat } from "./components/shared";
import { TemplatesView } from "./components/templates-view";
import { VideosView } from "./components/videos-view";
import { errorMessage } from "./drips-helpers";
import { useDripsData } from "./use-drips-data";

type Tab = "campaigns" | "board" | "segments" | "templates" | "videos" | "settings";

export function DripsShell() {
  const { overview, board, loading, refreshing, error, refresh } = useDripsData();
  const [selectedCampaign, setSelectedCampaign] = useState<string | null>(null);
  const [enrollFor, setEnrollFor] = useState<DripCampaign | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [videos, setVideos] = useState<DripVideo[]>([]);

  useEffect(() => {
    api
      .getDripVideos()
      .then((res) => setVideos(res.videos))
      .catch(() => setVideos([]));
  }, [overview]);

  if (loading && !overview) return <LoadingState />;

  const segments = overview?.segments ?? [];
  const campaigns = overview?.campaigns ?? [];
  const counts = overview?.counts;

  const toggleCampaign = async (campaign: DripCampaign, enabled: boolean) => {
    setBusyId(campaign.id);
    setActionError(null);
    try {
      await api.setDripCampaignEnabled(campaign.id, enabled);
      await refresh();
    } catch (err) {
      setActionError(errorMessage(err, "Could not update the campaign."));
    } finally {
      setBusyId(null);
    }
  };

  const createCampaign = async () => {
    setBusyId("new");
    setActionError(null);
    try {
      const res = await api.createDripCampaign({ name: "New campaign", kind: "custom", role: "primary", enabled: false });
      await refresh();
      setSelectedCampaign(res.campaign.id);
    } catch (err) {
      setActionError(errorMessage(err, "Could not create a campaign."));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Tabs defaultValue="campaigns">
      {(active, setActive) => {
        const tab = active as Tab;
        const openCampaign = (id: string) => {
          setSelectedCampaign(id);
          setActive("campaigns");
        };
        return (
          <div className="real-estate-hub flex flex-col gap-4 pb-6">
            <section className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
                  <Droplets className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <div className="font-mono-ui text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Leads pack</div>
                  <h1 className="text-xl font-semibold leading-tight text-foreground sm:text-[1.6rem]">Drip campaigns</h1>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {counts && (
                  <>
                    <Stat label="Due today" value={counts.dueToday} hint={counts.overdue ? `${counts.overdue} overdue` : undefined} />
                    <Stat label="On campaigns" value={counts.liveEnrollments} hint={`${counts.contactsInSegments} contacts in segments`} />
                    <Stat label="Videos" value={`${counts.videosRecorded}/${counts.videosTotal}`} hint="recorded" />
                  </>
                )}
                <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing} aria-label="Refresh">
                  <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} aria-hidden="true" />
                  Refresh
                </Button>
              </div>
            </section>

            {error && (
              <Note tone="error" className="flex items-center justify-between gap-3">
                <span>{error}</span>
                <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
                  Retry
                </Button>
              </Note>
            )}
            {actionError && <Note tone="error">{actionError}</Note>}

            <TabsList className="h-auto flex-wrap gap-1 py-1">
              {(
                [
                  ["campaigns", "Campaigns"],
                  ["board", `Due board${counts ? ` (${counts.dueToday + counts.overdue})` : ""}`],
                  ["segments", "Segments"],
                  ["templates", "Elevation templates"],
                  ["videos", "Videos"],
                  ["settings", "Settings"],
                ] as Array<[Tab, string]>
              ).map(([value, label]) => (
                <TabsTrigger key={value} value={value} active={tab === value} onClick={() => { setActive(value); if (value !== "campaigns") setSelectedCampaign(null); }}>
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>

            {tab === "campaigns" &&
              (selectedCampaign ? (
                <CampaignDetail
                  campaignId={selectedCampaign}
                  segments={segments}
                  videos={videos}
                  onBack={() => setSelectedCampaign(null)}
                  onChanged={refresh}
                />
              ) : (
                <CampaignsView
                  campaigns={campaigns}
                  segments={segments}
                  busyId={busyId}
                  onOpen={openCampaign}
                  onToggle={toggleCampaign}
                  onEnroll={setEnrollFor}
                  onCreate={() => void createCampaign()}
                  onBrowseTemplates={() => setActive("templates")}
                />
              ))}
            {tab === "board" && <BoardView board={board} segments={segments} onChanged={refresh} />}
            {tab === "segments" && <SegmentsView segments={segments} onChanged={refresh} />}
            {tab === "templates" && <TemplatesView segments={segments} onInstalled={refresh} onOpen={openCampaign} />}
            {tab === "videos" && <VideosView onChanged={refresh} />}
            {tab === "settings" && overview && <SettingsView settings={overview.settings} onChanged={refresh} />}

            {enrollFor && (
              <EnrollDialog campaign={enrollFor} segments={segments} onClose={() => setEnrollFor(null)} onEnrolled={refresh} />
            )}
          </div>
        );
      }}
    </Tabs>
  );
}

export default DripsShell;
