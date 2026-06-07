import { Skeleton } from "@/components/ui/skeleton";
import "@/pages/agent-hub.css";

const HUB_SKELETON_FOUR = [0, 1, 2, 3] as const;
const HUB_SKELETON_THREE = [0, 1, 2] as const;
const HUB_SKELETON_AGENTS = [0, 1, 2, 3] as const;

function HubSkel({ className = "" }: { className?: string }) {
  return <Skeleton className={`hub-skel ${className}`} />;
}

function HubKpiSkeleton() {
  return (
    <div className="hub-kpi">
      <HubSkel className="h-[13px] w-24" />
      <HubSkel className="mt-[9px] h-[26px] w-14" />
    </div>
  );
}

function HubRunwaySkeleton() {
  return (
    <div className="hub-runway-tile hub-runway-skeleton">
      <div className="hub-runway-top">
        <HubSkel className="h-[15px] w-[15px] rounded-[4px]" />
        <HubSkel className="h-[15px] w-24" />
        <HubSkel className="ml-auto h-[12px] w-16 rounded-full" />
      </div>
      <HubSkel className="soft mt-[9px] h-[12px] w-full" />
    </div>
  );
}

function HubAgentCardSkeleton({ index }: { index: number }) {
  const nameWidth = index % 2 === 0 ? "w-52" : "w-44";
  return (
    <div className="hub-agent hub-agent-skeleton">
      <div className="hub-agent-head">
        <HubSkel className={`h-[18px] ${nameWidth}`} />
        <div className="hub-agent-status">
          <HubSkel className="h-[6px] w-[6px] rounded-full" />
          <HubSkel className="h-[12px] w-14" />
        </div>
      </div>
      <HubSkel className="soft mt-[10px] h-[14px] w-11/12" />
      <HubSkel className="soft mt-[7px] h-[14px] w-3/4" />
      <div className="hub-agent-meta mono">
        <HubSkel className="h-[12px] w-16" />
        <HubSkel className="h-[12px] w-20" />
        <HubSkel className="h-[12px] w-16" />
        <HubSkel className="h-[12px] w-14" />
      </div>
      <div className="hub-agent-glance mono">
        <HubSkel className="soft h-[22px] w-28 rounded-[7px]" />
        <HubSkel className="soft h-[22px] w-24 rounded-[7px]" />
        <HubSkel className="soft h-[22px] w-20 rounded-[7px]" />
        <HubSkel className="soft h-[22px] w-32 rounded-[7px]" />
      </div>
      <div className="hub-agent-actions">
        <HubSkel className="h-[28px] w-[100px] rounded-[8px]" />
        <HubSkel className="h-[28px] w-[126px] rounded-[8px]" />
        <HubSkel className="h-[28px] w-[92px] rounded-[8px]" />
      </div>
    </div>
  );
}

export function AgentHubSkeleton() {
  return (
    <div className="hub-root" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading Agent Hub</span>
      <div className="hub">
        <div className="hub-inner hub-skeleton-page">
          <div className="hub-hero">
            <div>
              <HubSkel className="mb-[7px] h-[11px] w-20" />
              <HubSkel className="h-[23px] w-56 max-w-[70vw]" />
              <HubSkel className="soft mt-[8px] h-[13px] w-[min(36rem,82vw)]" />
            </div>
            <div className="hub-hero-actions">
              <HubSkel className="h-[31px] w-[118px] rounded-[8px]" />
              <HubSkel className="h-[31px] w-[86px] rounded-[8px]" />
            </div>
          </div>

          <div className="hub-kpis">
            {HUB_SKELETON_FOUR.map((item) => (
              <HubKpiSkeleton key={`kpi-${item}`} />
            ))}
          </div>

          <div className="hub-block">
            <div className="hub-block-head">
              <HubSkel className="h-[17px] w-32" />
              <HubSkel className="h-[13px] w-20" />
            </div>
            <div className="hub-runway">
              {HUB_SKELETON_FOUR.map((item) => (
                <HubRunwaySkeleton key={`runway-${item}`} />
              ))}
            </div>
          </div>

          <div className="hub-block">
            <div className="hub-block-head">
              <HubSkel className="h-[17px] w-32" />
              <HubSkel className="h-[13px] w-24" />
            </div>
            <HubSkel className="soft mb-[8px] h-[13px] w-[min(34rem,100%)]" />
            <div className="hub-skeleton-inline-form">
              <HubSkel className="h-[35px] min-w-0 flex-1 rounded-[8px]" />
              <HubSkel className="h-[34px] w-[118px] rounded-[8px]" />
            </div>
          </div>

          <div className="hub-block">
            <div className="hub-block-head">
              <HubSkel className="h-[17px] w-48" />
              <HubSkel className="h-[29px] w-[116px] rounded-[8px]" />
            </div>

            <div className="hub-exectel">
              <div className="hub-exectel-head">
                <HubSkel className="h-[15px] w-36" />
                <HubSkel className="h-[12px] w-20" />
              </div>
              <div className="hub-exectel-form">
                <div className="hub-exectel-field">
                  <HubSkel className="h-[12px] w-32" />
                  <HubSkel className="mt-[7px] h-[39px] w-full rounded-[8px]" />
                </div>
                <div className="hub-exectel-field">
                  <HubSkel className="h-[12px] w-32" />
                  <HubSkel className="mt-[7px] h-[39px] w-full rounded-[8px]" />
                </div>
                <div className="hub-exectel-actions">
                  <HubSkel className="h-[33px] w-[72px] rounded-[8px]" />
                  <HubSkel className="h-[33px] w-[86px] rounded-[8px]" />
                </div>
              </div>
            </div>

            <div className="hub-agents">
              {HUB_SKELETON_AGENTS.map((item) => (
                <HubAgentCardSkeleton key={`agent-${item}`} index={item} />
              ))}
              <div className="hub-agent-add hub-agent-add-skeleton">
                <HubSkel className="mb-[4px] h-[18px] w-[18px] rounded-[5px]" />
                <HubSkel className="h-[14px] w-24" />
                <HubSkel className="soft h-[12px] w-52 max-w-full" />
              </div>
            </div>
          </div>

          <div className="hub-section">
            <div className="hub-handoff-head">
              <div>
                <HubSkel className="h-[17px] w-40" />
                <div className="hub-handoff-meta mono">
                  <HubSkel className="soft h-[12px] w-24" />
                  <HubSkel className="soft h-[12px] w-20" />
                  <HubSkel className="soft h-[12px] w-28" />
                </div>
              </div>
              <div className="hub-handoff-actions">
                <HubSkel className="h-[33px] w-[104px] rounded-[8px]" />
                <HubSkel className="h-[33px] w-[94px] rounded-[8px]" />
              </div>
            </div>
            <div className="hub-mini3">
              {HUB_SKELETON_THREE.map((item) => (
                <HubKpiSkeleton key={`handoff-kpi-${item}`} />
              ))}
            </div>
            <div className="hub-handoff-flags mono">
              {HUB_SKELETON_THREE.map((item) => (
                <HubSkel className="soft h-[12px] w-32" key={`flag-${item}`} />
              ))}
            </div>
            <div className="hub-handoff-list">
              {HUB_SKELETON_THREE.map((item) => (
                <div className="hub-handoff-row" key={`handoff-${item}`}>
                  <div className="hub-handoff-row-top">
                    <HubSkel className="h-[14px] w-2/5" />
                    <HubSkel className="h-[12px] w-20" />
                  </div>
                  <HubSkel className="soft mt-[6px] h-[12px] w-1/2" />
                </div>
              ))}
            </div>
          </div>

          <div className="hub-section hub-access">
            <HubSkel className="mb-[10px] h-[17px] w-32" />
            <div className="hub-access-ents mono">
              {HUB_SKELETON_FOUR.map((item) => (
                <HubSkel className="soft h-[12px] w-24" key={`access-${item}`} />
              ))}
            </div>
            <HubSkel className="soft mt-[8px] h-[12px] w-[min(38rem,100%)]" />
            <HubSkel className="soft mt-[14px] h-[12px] w-[min(28rem,100%)]" />
          </div>
        </div>
      </div>
    </div>
  );
}
