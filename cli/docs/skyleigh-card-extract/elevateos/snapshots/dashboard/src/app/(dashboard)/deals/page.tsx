import Link from 'next/link';
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBriefcase,
  IconChecklist,
  IconClock,
  IconMessageCircle,
} from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DealCollapsedButton } from '@/components/realestate/deal-collapsed-button';
import {
  getRealtorCommandCenter,
  REALTOR_DEAL_STAGES,
  type DealRisk,
  type RealtorDeal,
  type RealtorDealStage,
} from '@/lib/realestate/command-center';
import {
  getOperationalDealsOverview,
  isCollapseEligible,
  stageLabel,
  type OperationalDeal,
} from '@/lib/realestate/operational-deals';

export const dynamic = 'force-dynamic';

function riskClass(risk: DealRisk): string {
  if (risk === 'red') return 'border-destructive/35 bg-destructive/5 text-destructive';
  if (risk === 'yellow') return 'border-warning/35 bg-warning/10 text-foreground';
  return 'border-success/25 bg-success/5 text-foreground';
}

function riskText(risk: DealRisk): string {
  if (risk === 'red') return 'At risk';
  if (risk === 'yellow') return 'Watch';
  return 'Clear';
}

const STAGE_DESCRIPTIONS: Partial<Record<RealtorDealStage, string>> = {
  'Pre-CMA': 'Google Form intake + Lofty contact check before pricing work starts.',
  'CMA / Evaluation': 'CMA PDF, pricing evaluation, and seller-facing price story.',
  'Listing Intake': 'Client said yes. Starts MLC intake, missing fields, docs, and approval before signing.',
  'SkySlope & Matrix Prep': 'Signed MLC received. Save docs, create SkySlope file, and prep Matrix incomplete listing.',
  'Marketing Go': 'Next step after SkySlope/Matrix prep. Coming-soon, launch copy, social, email, and listing assets.',
  Closed: 'Closed properties live here only and are excluded from the active top-seller / pending-deal lists.',
};

const OPERATIONAL_STAGE_COLUMNS: Array<{
  label: string;
  description: string;
  include: (deal: OperationalDeal) => boolean;
}> = [
  {
    label: 'Top 25 Buyers',
    description: 'Buyer cards that are still active prospects.',
    include: (deal) => deal.side === 'buyer' && deal.currentStage === 0,
  },
  {
    label: 'Buyer Accepted Offer',
    description: 'Buyer-side accepted offers, conditions, and subject removal.',
    include: (deal) => deal.side === 'buyer' && deal.currentStage >= 1 && deal.currentStage <= 3,
  },
  {
    label: 'Listing Live',
    description: 'Active seller listings before an accepted offer.',
    include: (deal) => deal.side === 'listing' && deal.currentStage === 5,
  },
  {
    label: 'Accepted Offer',
    description: 'Seller listing cards with an accepted offer. Collapse button appears here.',
    include: (deal) => deal.side === 'listing' && deal.currentStage === 6,
  },
  {
    label: 'Condition Removal',
    description: 'Accepted offers moving through subject removal and closing prep.',
    include: (deal) => deal.side === 'listing' && deal.currentStage === 7,
  },
];

function formatMoney(value: number | null): string | null {
  if (value === null || Number.isNaN(value)) return null;
  return new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 }).format(value);
}

function collapseResetCopy(deal: OperationalDeal): string {
  if (deal.side === 'buyer') return 'Moves buyer back to Top 25 and clears property-specific fields.';
  return 'Moves listing back to Listing Live and removes prior buyer memory from the seller card.';
}

function OperationalDealCard({ deal }: { deal: OperationalDeal }) {
  const price = formatMoney(deal.offerPrice ?? deal.listPrice);
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium">{deal.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{deal.side} · {stageLabel(deal.side, deal.currentStage)}</p>
        </div>
        <Badge variant="outline">Stage {deal.currentStage}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {price && <span>{price}</span>}
        {deal.mlsNumber && <span>MLS {deal.mlsNumber}</span>}
        {deal.subjectRemovalDate && <span>Subjects {deal.subjectRemovalDate}</span>}
        {deal.completionDate && <span>Completion {deal.completionDate}</span>}
      </div>
      {isCollapseEligible(deal) && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/35 p-2">
          <p className="max-w-[260px] text-xs text-muted-foreground">{collapseResetCopy(deal)}</p>
          <DealCollapsedButton dealId={deal.id} dealTitle={deal.title} side={deal.side} />
        </div>
      )}
    </div>
  );
}

function OperationalStageColumn({
  label,
  description,
  deals,
}: {
  label: string;
  description?: string;
  deals: OperationalDeal[];
}) {
  return (
    <section className="min-h-40 rounded-md border bg-muted/20 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{label}</h2>
        <Badge variant="secondary">{deals.length}</Badge>
      </div>
      {description && <p className="mb-3 text-xs text-muted-foreground">{description}</p>}
      {deals.length === 0 ? (
        <p className="rounded-md border border-dashed bg-background/70 p-3 text-xs text-muted-foreground">
          No deals in this stage.
        </p>
      ) : (
        <div className="grid gap-2">
          {deals.map((deal) => <OperationalDealCard key={deal.id} deal={deal} />)}
        </div>
      )}
    </section>
  );
}

function DealCard({ deal }: { deal: RealtorDeal }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium">{deal.client}</h3>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{deal.nextAction}</p>
        </div>
        <Badge variant="outline" className={riskClass(deal.risk)}>
          {riskText(deal.risk)}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{deal.owner}</span>
        <span>·</span>
        <span>{deal.lastTouchLabel}</span>
        <span>·</span>
        <span>{deal.messageCount} msgs</span>
      </div>
      {deal.blocker && (
        <div className="mt-3 rounded-md bg-muted/45 px-2 py-1.5 text-xs text-muted-foreground">
          {deal.blocker}
        </div>
      )}
      {deal.lastMessage && (
        <p className="mt-3 line-clamp-2 text-xs text-muted-foreground">{deal.lastMessage}</p>
      )}
    </div>
  );
}

function StageColumn({ stage, deals }: { stage: RealtorDealStage; deals: RealtorDeal[] }) {
  const description = STAGE_DESCRIPTIONS[stage];

  return (
    <section className="min-h-40 rounded-md border bg-muted/20 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{stage}</h2>
        <Badge variant="secondary">{deals.length}</Badge>
      </div>
      {description && <p className="mb-3 text-xs text-muted-foreground">{description}</p>}
      {deals.length === 0 ? (
        <p className="rounded-md border border-dashed bg-background/70 p-3 text-xs text-muted-foreground">
          No deals in this stage.
        </p>
      ) : (
        <div className="grid gap-2">
          {deals.map((deal) => <DealCard key={deal.id} deal={deal} />)}
        </div>
      )}
    </section>
  );
}

export default async function DealsPage() {
  const result = await getRealtorCommandCenter();
  const operationalResult = getOperationalDealsOverview();
  const data = result.data;
  const operationalDeals = operationalResult.kind === 'ok' ? operationalResult.data.deals : [];
  const activeDeals = data.deals.filter((deal) => deal.stage !== 'Closed');
  const urgentDeals = activeDeals.filter((deal) => deal.risk === 'red');
  const replyDeals = activeDeals.filter((deal) => deal.lastInbound);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
          <p className="text-sm text-muted-foreground">
            Pre-CMA, CMA, listing intake, SkySlope/Matrix prep, Marketing Go, and admin work required to keep deals moving.
          </p>
        </div>
        <Link href="/" className="inline-flex items-center gap-1 text-sm font-medium text-primary">
          Back to overview <IconArrowRight size={15} />
        </Link>
      </div>

      {result.kind !== 'ok' && (
        <div className="rounded-md border bg-muted/30 p-4 text-sm text-muted-foreground">
          {result.kind === 'no-db'
            ? 'Connect data_roots.messages_db or initialize a source connector in Settings to populate the deal pipeline.'
            : `Could not read the configured messages source: ${result.message}`}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Card className="rounded-md">
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Open Deals</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{activeDeals.length}</p>
            </div>
            <IconBriefcase size={20} className="text-primary" />
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">At Risk</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{urgentDeals.length}</p>
            </div>
            <IconAlertTriangle size={20} className="text-primary" />
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Replies</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{replyDeals.length}</p>
            </div>
            <IconMessageCircle size={20} className="text-primary" />
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Feedback</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{data.feedbackDue}</p>
            </div>
            <IconMessageCircle size={20} className="text-primary" />
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Admin Items</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{data.adminQueue.length}</p>
            </div>
            <IconChecklist size={20} className="text-primary" />
          </CardContent>
        </Card>
      </div>

      <section className="space-y-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Property score cards</h2>
            <p className="text-sm text-muted-foreground">
              Live Admin deal cards grouped by stage. The Deal collapsed button shows on accepted-offer seller cards and buyer accepted-offer cards.
            </p>
          </div>
          {operationalResult.kind !== 'ok' && (
            <Badge variant="outline" className="w-fit">Operational cards unavailable</Badge>
          )}
        </div>
        {operationalResult.kind !== 'ok' && (
          <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
            {operationalResult.message}
          </div>
        )}
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-5">
          {OPERATIONAL_STAGE_COLUMNS.map((column) => (
            <OperationalStageColumn
              key={column.label}
              label={column.label}
              description={column.description}
              deals={operationalDeals.filter(column.include)}
            />
          ))}
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {REALTOR_DEAL_STAGES.map((stage) => (
            <StageColumn
              key={stage}
              stage={stage}
              deals={data.deals.filter((deal) => deal.stage === stage)}
            />
          ))}
        </div>

        <aside className="space-y-4">
          <Card className="rounded-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconClock size={18} />
                Deadline Radar
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.deadlineRadar.length === 0 ? (
                <p className="text-sm text-muted-foreground">No deadline tasks are currently surfaced.</p>
              ) : (
                data.deadlineRadar.map((item) => (
                  <Link
                    key={item.id}
                    href={item.href}
                    className="block rounded-md px-2 py-2 transition-colors hover:bg-muted/45"
                  >
                    <p className="truncate text-sm font-medium">{item.title}</p>
                    <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{item.detail}</p>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="rounded-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconMessageCircle size={18} />
                Listing Feedback
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.listingFeedback.length === 0 ? (
                <p className="text-sm text-muted-foreground">No showing feedback follow-ups are currently surfaced.</p>
              ) : (
                data.listingFeedback.map((item) => (
                  <Link
                    key={`${item.kind}-${item.id}`}
                    href={item.href}
                    className="block rounded-md px-2 py-2 transition-colors hover:bg-muted/45"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <Badge variant="secondary">{item.owner}</Badge>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{item.detail}</p>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="rounded-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconChecklist size={18} />
                Required Admin
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.adminQueue.length === 0 ? (
                <p className="text-sm text-muted-foreground">No approvals, missing docs, or human tasks are blocking deals.</p>
              ) : (
                data.adminQueue.map((item) => (
                  <Link
                    key={`${item.kind}-${item.id}`}
                    href={item.href}
                    className="block rounded-md px-2 py-2 transition-colors hover:bg-muted/45"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <Badge variant="secondary">{item.owner}</Badge>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{item.detail}</p>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
