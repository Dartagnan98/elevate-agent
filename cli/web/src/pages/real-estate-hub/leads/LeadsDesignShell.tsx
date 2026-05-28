import { useCallback, useEffect, useMemo, useState } from "react";
import LeadsBoard from "./components/leads-board";
import { useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { api } from "@/lib/api";
import type {
  OutreachTemplate,
  SourceInboxSentItem,
} from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction } from "./leads-data";
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

  const handleDraftAction = useCallback(
    async (action: LeadsDraftAction, draft: LeadsDraft) => {
      if (!draft.sourceId || !draft.taskId) return;
      try {
        const res = await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action);
        setSourceInbox(res);
      } catch (err) {
        console.error("draft action failed", err);
      }
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
          onDraftAction={handleDraftAction}
          onReRunOnboarding={() => setForceOnboarding(true)}
        />
      )}
    </div>
  );
}

export default LeadsDesignShell;
