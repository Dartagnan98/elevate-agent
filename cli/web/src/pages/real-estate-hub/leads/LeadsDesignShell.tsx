import { useState } from "react";
import LeadsBoard from "./components/leads-board";
import { HubDataErrorBanner } from "@/pages/real-estate-hub/_shared";
import { LeadsSetupLaunch, useLeadsSetup } from "./onboarding";
import { useLeadsBoardData } from "./use-leads-board-data";
import "./leads.css";

export { sourceInboxDebugNote, sourceInboxProfileStatusForLabel } from "./use-leads-board-data";

export function LeadsDesignShell() {
  const boardData = useLeadsBoardData();
  const { data, inbox } = boardData;

  const leadsSetup = useLeadsSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const setupSnapshot = leadsSetup.setup;
  const showOnboarding =
    !leadsSetup.loading && !!setupSnapshot && (!setupSnapshot.complete || forceOnboarding);

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
          sent={boardData.sent}
          debugNote={boardData.debugNote}
          onDraftAction={boardData.handleDraftAction}
          onDraftActionComplete={boardData.handleDraftActionComplete}
          onProfileFavoriteChange={boardData.handleProfileFavoriteChange}
          onProfileStatusChange={boardData.handleProfileStatusChange}
          onReRunOnboarding={() => setForceOnboarding(true)}
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
