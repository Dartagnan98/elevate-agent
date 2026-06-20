import { spawnSync } from 'child_process';

const DEFAULT_ELEVATE_PYTHON = '/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python';

export interface OperationalDeal {
  id: string;
  title: string;
  side: 'listing' | 'buyer' | string;
  currentStage: number;
  stageEnteredAt: string | null;
  completionDate: string | null;
  subjectRemovalDate: string | null;
  listingDate: string | null;
  listPrice: number | null;
  offerPrice: number | null;
  sourceLabel: string | null;
  sourceKey: string | null;
  primaryContactId: string | null;
  mlsNumber: string | null;
}

export interface OperationalDealsOverview {
  generatedAt: string;
  today: string;
  totals: {
    activeAfterFilter: number;
    mockExcluded: number;
    rawMatched: number;
    byStatus: Record<string, number>;
    bySide: Record<string, number>;
  };
  byStage: Record<string, number>;
  bySource: Record<string, number>;
  closingsSoon: OperationalDeal[];
  subjectsSoon: OperationalDeal[];
  staleStages: Array<OperationalDeal & { daysInStage?: number }>;
  deals: OperationalDeal[];
}

export type OperationalDealsResult =
  | { kind: 'ok'; data: OperationalDealsOverview }
  | { kind: 'unavailable'; message: string };

function elevatePython(): string {
  return process.env.ELEVATE_PYTHON || DEFAULT_ELEVATE_PYTHON;
}

export function getOperationalDealsOverview(): OperationalDealsResult {
  const script = String.raw`
import json
import sys
from elevate_cli.data.connection import connect
from elevate_cli.data.deals import deals_overview

try:
    with connect() as conn:
        payload = deals_overview(conn, status='active', exclude_mock=True)
    print(json.dumps(payload, default=str))
except Exception as exc:
    print(json.dumps({'error': str(exc), 'type': exc.__class__.__name__}))
    sys.exit(1)
`;

  const result = spawnSync(elevatePython(), ['-c', script], {
    cwd: process.cwd(),
    encoding: 'utf-8',
    timeout: 12_000,
    env: process.env,
  });

  if (result.error) {
    return { kind: 'unavailable', message: result.error.message };
  }
  if (result.status !== 0) {
    const stderr = result.stderr?.trim();
    const stdout = result.stdout?.trim();
    return { kind: 'unavailable', message: stderr || stdout || `Elevate Python exited ${result.status}` };
  }

  try {
    const parsed = JSON.parse(result.stdout) as OperationalDealsOverview;
    if (!parsed || !Array.isArray(parsed.deals)) {
      return { kind: 'unavailable', message: 'Operational deals overview returned an unexpected payload.' };
    }
    return { kind: 'ok', data: parsed };
  } catch (err) {
    return {
      kind: 'unavailable',
      message: err instanceof Error ? err.message : 'Could not parse operational deals overview.',
    };
  }
}

export function stageLabel(side: string, stage: number): string {
  if (side === 'buyer') {
    switch (stage) {
      case 0:
        return 'Top 25 / Buyer Offer Prep';
      case 1:
        return 'Buyer Accepted Offer';
      case 2:
        return 'Buyer Conditions';
      case 3:
        return 'Buyer Subjects Off';
      case 8:
        return 'Closed';
      default:
        return `Buyer Stage ${stage}`;
    }
  }

  switch (stage) {
    case 0:
      return 'Pre-CMA';
    case 1:
      return 'CMA / Evaluation';
    case 2:
      return 'Listing Intake';
    case 3:
      return 'SkySlope & Matrix Prep';
    case 4:
      return 'Marketing Go';
    case 5:
      return 'Listing Live';
    case 6:
      return 'Accepted Offer';
    case 7:
      return 'Condition Removal';
    case 8:
      return 'Closed';
    case 10:
      return 'Nurture / Pre-CMA Watch';
    default:
      return `Stage ${stage}`;
  }
}

export function isCollapseEligible(deal: Pick<OperationalDeal, 'side' | 'currentStage'>): boolean {
  if (deal.side === 'listing') return deal.currentStage === 6 || deal.currentStage === 7;
  if (deal.side === 'buyer') return deal.currentStage >= 1 && deal.currentStage <= 3;
  return false;
}
