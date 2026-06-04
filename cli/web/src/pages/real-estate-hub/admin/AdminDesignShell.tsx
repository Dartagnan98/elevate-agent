import { useCallback, useMemo, useState } from "react";
import AdminBoard from "./components/admin-board";
import { useAdminDeals } from "./use-admin-deals";
import { adminDealToDeal, adminDealToBuyerDeal } from "./admin-mappers";
import { computeAdminKpis } from "./compute-admin-kpis";
import { computeAdminEvents } from "./compute-admin-events";
import { useAdminEvents } from "./use-admin-events";
import {
  AdminSetupLaunch,
  AdminOnboardingCoach,
  computeCoachInitialQuestion,
  useAdminSetup,
  type CoachMessage,
} from "./index";
import "./admin.css";

export function AdminDesignShell() {
  const rootAttrs = {
    "data-accent": "graphite" as const,
    "data-density": "compact" as const,
    "data-dots": "smart" as const,
    "data-active-row": "fill" as const,
    "data-sections": "micro" as const,
    "data-artifacts": "hidden" as const,
  };

  const { deals, loading, error, refresh, moveDeal } = useAdminDeals();
  const { events: syncedEvents, error: eventsError, refresh: refreshEvents } = useAdminEvents(21);

  const adminSetup = useAdminSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const setupSnapshot = adminSetup.setup;

  // Coach state — mirrors the legacy page so the "Ask the coach" connector
  // buttons (and the floating launcher) open a real, working coach panel.
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachMention, setCoachMention] = useState<string | null>(null);
  const [coachMessages, setCoachMessages] = useState<CoachMessage[]>([]);
  const openCoach = useCallback(() => setCoachOpen(true), []);
  const initialCoachQuestion = useMemo(
    () => computeCoachInitialQuestion(setupSnapshot),
    [setupSnapshot],
  );
  const resetCoach = useCallback(() => {
    setCoachMessages([{ role: "assistant", content: initialCoachQuestion }]);
    setCoachMention(null);
    setCoachOpen(true);
  }, [initialCoachQuestion]);
  const showOnboarding =
    !adminSetup.loading && !!setupSnapshot && (!setupSnapshot.complete || forceOnboarding);

  const { listingDeals, buyerDeals } = useMemo(() => {
    const listing = [];
    const buyer = [];
    for (const d of deals) {
      if (d.side === "buyer") buyer.push(adminDealToBuyerDeal(d));
      else listing.push(adminDealToDeal(d));
    }
    return { listingDeals: listing, buyerDeals: buyer };
  }, [deals]);

  const kpis = useMemo(() => computeAdminKpis(deals), [deals]);
  const fallbackEvents = useMemo(() => computeAdminEvents(deals), [deals]);
  const events = syncedEvents.length > 0 ? syncedEvents : fallbackEvents;
  const visibleError = error || (eventsError && fallbackEvents.length === 0 ? eventsError : null);
  const handleRefresh = async () => {
    await Promise.all([refresh(), refreshEvents()]);
  };

  return (
    <div className="app admin-design-embedded" {...rootAttrs}>
      {showOnboarding && setupSnapshot ? (
        <div className="admin-onboarding-wrap">
          <AdminSetupLaunch
            setup={setupSnapshot}
            onSetupUpdated={(next) => adminSetup.setSetup(next)}
            forceOnboarding={forceOnboarding}
            onForceOnboardingDone={() => setForceOnboarding(false)}
            openCoach={openCoach}
            setCoachMention={setCoachMention}
          />
          {coachOpen ? (
            <AdminOnboardingCoach
              initialQuestion={initialCoachQuestion}
              onClose={() => setCoachOpen(false)}
              onReset={resetCoach}
              externalMention={coachMention}
              messages={coachMessages}
              setMessages={setCoachMessages}
            />
          ) : (
            <button
              type="button"
              onClick={openCoach}
              aria-label="Open onboarding coach"
              className="fixed bottom-6 right-6 z-[110] inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-[12.5px] text-foreground shadow-md hover:border-primary"
            >
              Ask the coach
            </button>
          )}
        </div>
      ) : (
        <AdminBoard
          deals={listingDeals.length > 0 ? listingDeals : undefined}
          buyerDeals={buyerDeals.length > 0 ? buyerDeals : undefined}
          kpis={kpis}
          events={events}
          loading={loading}
          error={visibleError}
          onRefresh={handleRefresh}
          onMoveDeal={moveDeal}
          onReRunOnboarding={() => setForceOnboarding(true)}
        />
      )}
    </div>
  );
}

export default AdminDesignShell;
