import { useCallback, useEffect, useMemo, useState } from "react";
import LeadsBoard from "./components/leads-board";
import { useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { api } from "@/lib/api";
import type {
  OutreachTemplate,
  SourceInboxProfileStatus,
  SourceInboxResponse,
  SourceInboxSentItem,
} from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "./leads-data";
import {
  computeLeadsKpis,
  mapLeadsDrafts,
  mapLeadsPipeline,
  mapLeadsProfiles,
  mapLeadsSent,
  mapLeadsSources,
  mapLeadsTemplates,
} from "./compute-leads-data";
import { LeadsSetupLaunch, useLeadsSetup } from "./onboarding";
import "./leads.css";

export function sourceInboxDebugNote(inbox: SourceInboxResponse | null): string | null {
  const debug = inbox?.debug;
  if (!debug) return null;

  const { counts } = debug;
  const total =
    counts.profiles +
    counts.threads +
    counts.drafts +
    counts.skippedDrafts +
    counts.privateSearchBuyers;
  if (!debug.fallback && total > 0) return null;

  const note = `Source inbox read: ${debug.readPath} | ${counts.threads} threads | ${counts.drafts} drafts | ${counts.profiles} profiles | ${counts.skippedDrafts} skipped | ${counts.privateSearchBuyers} private buyers`;
  if (!debug.fallback) return note;
  return debug.fallbackError ? `${note} | fallback: ${debug.fallbackError}` : `${note} | fallback`;
}

export function sourceInboxProfileStatusForLabel(label: string): SourceInboxProfileStatus | null | undefined {
  const key = label.trim().toLowerCase();
  if (key === "no status") return null;
  if (key === "new lead") return "new_lead";
  if (key === "follow up") return "follow_up";
  if (key === "ghosting") return "ghosting";
  if (key === "dead") return "dead";
  if (key === "closed seller") return "closed_seller";
  if (key === "closed buyer") return "closed_buyer";
  return undefined;
}

export function LeadsDesignShell() {
  const data = useRealEstateHubData();
  const inbox = data.sourceInbox;
  const setSourceInbox = data.setSourceInbox;

  const leadsSetup = useLeadsSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const setupSnapshot = leadsSetup.setup;
  const showOnboarding =
    !leadsSetup.loading && !!setupSnapshot && (!setupSnapshot.complete || forceOnboarding);

  const [templatesRaw, setTemplatesRaw] = useState<OutreachTemplate[] | null>(null);
  const [sentRaw, setSentRaw] = useState<SourceInboxSentItem[] | null>(null);

  const refreshTemplates = useCallback(async () => {
    const res = await api.getOutreachTemplates();
    setTemplatesRaw(res.templates ?? []);
  }, []);

  const refreshSent = useCallback(async (includePending = false) => {
    const res = await api.getSourceInboxSent(100, includePending);
    setSentRaw(res.items ?? []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getOutreachTemplates()
      .then((res) => { if (!cancelled) setTemplatesRaw(res.templates ?? []); })
      .catch(() => { if (!cancelled) setTemplatesRaw([]); });
    api
      .getSourceInboxSent(100)
      .then((res) => { if (!cancelled) setSentRaw(res.items ?? []); })
      .catch(() => { if (!cancelled) setSentRaw([]); });
    return () => { cancelled = true; };
  }, []);

  const templateMutations = useMemo(
    () => ({
      onCreate: async (laneId: string, name: string, body: string) => {
        await api.createOutreachTemplate({ lane: laneId, name, body });
        await refreshTemplates();
      },
      onSave: async (id: string, name: string, body: string) => {
        await api.updateOutreachTemplate(id, { name, body });
        await refreshTemplates();
      },
      onTogglePause: async (id: string, active: boolean) => {
        await api.updateOutreachTemplate(id, { active });
        await refreshTemplates();
      },
      onDelete: async (id: string) => {
        await api.deleteOutreachTemplate(id);
        await refreshTemplates();
      },
      onSuggest: async (laneId: string) => {
        const res = await api.suggestOutreachTemplate({ lane: laneId });
        await refreshTemplates();
        return { name: res.template.name, body: res.template.body };
      },
    }),
    [refreshTemplates],
  );

  const sources = useMemo(
    () =>
      inbox ? mapLeadsSources(inbox.sources ?? [], inbox.drafts ?? [], inbox.threads ?? []) : undefined,
    [inbox],
  );
  const drafts = useMemo(
    () => (inbox ? mapLeadsDrafts(inbox.drafts ?? []) : undefined),
    [inbox],
  );
  const profiles = useMemo(
    () => (inbox ? mapLeadsProfiles(inbox.profiles ?? []) : undefined),
    [inbox],
  );
  const pipeline = useMemo(
    () =>
      inbox
        ? mapLeadsPipeline(
            inbox.drafts ?? [],
            inbox.skippedDrafts ?? [],
            inbox.privateSearchBuyers ?? [],
          )
        : undefined,
    [inbox],
  );
  const kpis = useMemo(
    () => (inbox ? computeLeadsKpis(inbox.drafts ?? [], inbox.profiles ?? []) : undefined),
    [inbox],
  );
  const templates = useMemo(
    () => (templatesRaw ? mapLeadsTemplates(templatesRaw) : undefined),
    [templatesRaw],
  );
  const sent = useMemo(
    () => (sentRaw ? mapLeadsSent(sentRaw) : undefined),
    [sentRaw],
  );

  const handleToggleDirection = useCallback(
    async (dir: "inbound" | "outbound", value: boolean) => {
      try {
        await api.setAppleMessagesDirections({ [dir]: value });
        // Refresh the inbox so the banner + toggle reflect new server state
        // (inbound off clears the FDA banner; inbound on re-checks access).
        await data.refresh({ force: true });
      } catch (err) {
        console.error("apple messages direction toggle failed", err);
      }
    },
    [data],
  );

  const handleDraftAction = useCallback(
    async (action: LeadsDraftAction, draft: LeadsDraft) => {
      if (!draft.sourceId || !draft.taskId) return;
      try {
        // draft.body carries the edited text from the card (approve/edit must
        // send what's in the textarea, not the original template).
        const res = await api.updateSourceInboxDraft(
          draft.sourceId, draft.taskId, action, draft.body ?? "",
        );
        setSourceInbox(res);
      } catch (err) {
        console.error("draft action failed", err);
      }
    },
    [setSourceInbox],
  );

  const handleProfileFavoriteChange = useCallback(
    async (profile: LeadsProfile, favorite: boolean) => {
      try {
        const res = await api.updateSourceInboxProfileFavorite(profile.id, favorite, {
          contactId: profile.contactIds?.[0] ?? null,
        });
        setSourceInbox(res);
      } catch (err) {
        console.error("favorite toggle failed", err);
        throw err;
      }
    },
    [setSourceInbox],
  );

  const handleProfileStatusChange = useCallback(
    async (profile: LeadsProfile, label: string) => {
      const status = sourceInboxProfileStatusForLabel(label);
      if (status === undefined) throw new Error(`Unsupported lead status: ${label}`);
      const res = await api.updateSourceInboxProfile(profile.id, status);
      setSourceInbox(res);
    },
    [setSourceInbox],
  );

  const rootAttrs = {
    "data-accent": "graphite" as const,
    "data-density": "compact" as const,
    "data-dots": "smart" as const,
    "data-active-row": "fill" as const,
    "data-sections": "micro" as const,
    "data-artifacts": "hidden" as const,
  };

  return (
    <div className="app leads-design-embedded" {...rootAttrs}>
      {showOnboarding && setupSnapshot ? (
        <div className="leads-onboarding-wrap">
          <LeadsSetupLaunch
            setup={setupSnapshot}
            onSetupUpdated={(next) => leadsSetup.setSetup(next)}
            forceOnboarding={forceOnboarding}
            onForceOnboardingDone={() => setForceOnboarding(false)}
          />
        </div>
      ) : (
        <LeadsBoard
          sources={sources && sources.length > 1 ? sources : undefined}
          drafts={drafts && drafts.length > 0 ? drafts : undefined}
          profiles={profiles && profiles.length > 0 ? profiles : undefined}
          pipeline={pipeline}
          kpis={kpis}
          templates={templates && templates.length > 0 ? templates : undefined}
          sent={sent && sent.length > 0 ? sent : undefined}
          debugNote={sourceInboxDebugNote(inbox)}
          onDraftAction={handleDraftAction}
          onProfileFavoriteChange={handleProfileFavoriteChange}
          onProfileStatusChange={handleProfileStatusChange}
          onReRunOnboarding={() => setForceOnboarding(true)}
          onRefresh={() => void data.refresh({ force: true })}
          templateMutations={templateMutations}
          onSentRefresh={refreshSent}
          appleMessages={inbox?.appleMessages}
          onToggleDirection={handleToggleDirection}
        />
      )}
    </div>
  );
}

export default LeadsDesignShell;
