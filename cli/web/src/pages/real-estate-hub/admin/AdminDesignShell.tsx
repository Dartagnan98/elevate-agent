import { useMemo, useState } from "react";
import AdminBoard from "./components/admin-board";
import { useAdminDeals } from "./use-admin-deals";
import { adminDealToDeal, adminDealToBuyerDeal } from "./admin-mappers";
import { computeAdminKpis } from "./compute-admin-kpis";
import { computeAdminEvents } from "./compute-admin-events";
import { useAdminEvents } from "./use-admin-events";
import { AdminSetupLaunch, useAdminSetup } from "./index";
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

  const { deals, loading, error, refresh } = useAdminDeals();
  const { events: syncedEvents, error: eventsError, refresh: refreshEvents } = useAdminEvents(21);

  const adminSetup = useAdminSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const setupSnapshot = adminSetup.setup;
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
            openCoach={() => {}}
            setCoachMention={() => {}}
          />
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
          onReRunOnboarding={() => setForceOnboarding(true)}
        />
      )}
    </div>
  );
}

export default AdminDesignShell;
