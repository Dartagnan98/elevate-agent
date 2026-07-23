import { useState } from "react";
import LeadsBoard from "./components/leads-board";
import { HubDataErrorBanner } from "@/pages/real-estate-hub/_shared";
import { LeadsSetupLaunch, useLeadsSetup } from "./onboarding";
import { useLeadsBoardData } from "./use-leads-board-data";
import "./leads.css";
import "./leads-custom-cols.css";

export { sourceInboxDebugNote, sourceInboxProfileStatusForLabel } from "./use-leads-board-data";

export function LeadsDesignShell() {
  const boardData = useLeadsBoardData();
  const { data, inbox } = boardData;

  const leadsSetup = useLeadsSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const setupSnapshot = leadsSetup.setup;
  // Setup belongs inside the CRM, but it must not become a full-screen gate.
  // Realtors can inspect the live/empty board first and open setup deliberately.
  const showOnboarding = !leadsSetup.loading && !!setupSnapshot && forceOnboarding;
  const setupIncomplete = !leadsSetup.loading && Boolean(setupSnapshot && !setupSnapshot.complete);

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
      <HubDataErrorBanner className="mb-3" data={data} />
      {leadsSetup.error && !setupSnapshot && (
        <div className="lb-replies-empty lb-crm-error leads-setup-load-error" role="alert">
          <span>Source setup is unavailable. {leadsSetup.error}</span>
          <button
            type="button"
            className="lb-btn"
            disabled={leadsSetup.loading}
            onClick={() => void leadsSetup.refresh()}
          >
            {leadsSetup.loading ? "Retrying…" : "Retry source setup"}
          </button>
        </div>
      )}
      {setupIncomplete && !showOnboarding && (
        <div className="leads-setup-inline" role="status">
          <div>
            <strong>Lead source setup is incomplete</strong>
            <span>The CRM remains available. Connect a source before expecting live conversation profiles or outreach drafts.</span>
          </div>
          <button type="button" className="lb-btn" onClick={() => setForceOnboarding(true)}>
            Open source setup
          </button>
        </div>
      )}
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
          sources={boardData.sources}
          drafts={boardData.drafts}
          profiles={boardData.profiles}
          pipeline={boardData.pipeline}
          kpis={boardData.kpis}
          templates={boardData.templates}
          templatesState={boardData.templatesState}
          sent={boardData.sent}
          sentState={boardData.sentState}
          draftSendNotices={boardData.draftSendNotices}
          loading={data.loading || data.refreshing}
          error={data.error}
          debugNote={boardData.debugNote}
          onDraftAction={boardData.handleDraftAction}
          onDraftActionComplete={boardData.handleDraftActionComplete}
          onProfileFavoriteChange={boardData.handleProfileFavoriteChange}
          onProfileTop25Change={boardData.handleProfileTop25Change}
          onProfileTagsChange={boardData.handleProfileTagsChange}
          onProfileStatusChange={boardData.handleProfileStatusChange}
          onReRunOnboarding={leadsSetup.loading
            ? undefined
            : setupSnapshot
              ? () => setForceOnboarding(true)
              : () => void leadsSetup.refresh()}
          onRefresh={() => void data.refresh({ force: true })}
          templateMutations={boardData.templateMutations}
          onSentRefresh={boardData.refreshSent}
          appleMessages={inbox?.appleMessages}
          onToggleDirection={boardData.handleToggleDirection}
        />
      )}
    </div>
  );
}

export default LeadsDesignShell;
