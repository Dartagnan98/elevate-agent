import { spawnSync } from 'child_process';
import { NextResponse, type NextRequest } from 'next/server';

const DEFAULT_ELEVATE_PYTHON = '/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python';
const DEAL_ID_RE = /^[A-Za-z0-9_.:-]{1,160}$/;

function elevatePython(): string {
  return process.env.ELEVATE_PYTHON || DEFAULT_ELEVATE_PYTHON;
}

function normalizeSide(value: unknown): 'listing' | 'buyer' | null {
  return value === 'listing' || value === 'buyer' ? value : null;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const dealId = decodeURIComponent(id || '');
  if (!DEAL_ID_RE.test(dealId)) {
    return NextResponse.json({ error: 'Invalid deal id.' }, { status: 400 });
  }

  const body = await request.json().catch(() => ({}));
  const requestedSide = normalizeSide((body as { side?: unknown }).side);

  const script = String.raw`
import json
import re
import sys
from datetime import datetime, timezone

from elevate_cli.data.connection import connect
from elevate_cli.data.deals import (
    _decode_json,
    _encode_json,
    _insert_deal_event,
    get_deal,
    list_deal_contacts,
    move_deal_stage,
    set_deal_fields,
    set_deal_toggle,
)

DEAL_ID = sys.argv[1]
REQUESTED_SIDE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
ACTOR = 'dashboard:deal-collapsed-button'
LISTING_RESET_STAGE = 5
BUYER_RESET_STAGE = 0
LISTING_CLEAR_FIELDS = {
    'offerDate': None,
    'subjectRemovalDate': None,
    'depositDueDate': None,
    'completionDate': None,
    'possessionDate': None,
    'offerPrice': None,
    'depositAmount': None,
    'offerAcceptedAt': None,
    'subjectsRemovedAt': None,
    'completedAt': None,
    'depositInTrustAt': None,
}
BUYER_CLEAR_FIELDS = {
    **LISTING_CLEAR_FIELDS,
    'mlsNumber': None,
    'legalDescription': None,
    'lotSizeSqft': None,
    'yearBuilt': None,
    'listPrice': None,
    'listingDate': None,
    'listingPublishedAt': None,
}
LISTING_EXTRA_RE = re.compile(r'(buyer|purchaser|offer|accepted|deposit|subject|completion|possession|adjustment)', re.I)
BUYER_EXTRA_RE = re.compile(r'(property|listing|address|mls|legal|pid|strata|offer|accepted|deposit|subject|completion|possession|adjustment)', re.I)
BUYER_ROLE_RE = re.compile(r'(buyer|purchaser|tenant)', re.I)


def contact_name(item):
    contact = item.get('contact') or {}
    for key in ('displayName', 'display_name', 'name', 'fullName', 'primaryEmail', 'primary_email'):
        value = contact.get(key)
        if value:
            return str(value)
    return None


def scrub_extra(conn, deal_id, pattern):
    row = conn.execute('SELECT extra_toggles_json FROM deals WHERE id=?', (deal_id,)).fetchone()
    extra = _decode_json(row['extra_toggles_json']) if row and row['extra_toggles_json'] else {}
    if not isinstance(extra, dict):
        extra = {}
    removed = {key: extra[key] for key in list(extra.keys()) if pattern.search(str(key))}
    if removed:
        for key in removed:
            extra.pop(key, None)
        conn.execute('UPDATE deals SET extra_toggles_json=?, updated_at=? WHERE id=?', (
            _encode_json(extra),
            datetime.now(timezone.utc).isoformat(),
            deal_id,
        ))
    return removed


def remove_listing_buyers(conn, deal_id):
    rows = conn.execute('SELECT id, role, contact_id, notes FROM deal_contacts WHERE deal_id=?', (deal_id,)).fetchall()
    removed = []
    for row in rows:
        role = str(row['role'] or '')
        if BUYER_ROLE_RE.search(role):
            removed.append({'id': row['id'], 'role': role, 'contactId': row['contact_id'], 'notes': row['notes']})
            conn.execute('DELETE FROM deal_contacts WHERE id=?', (row['id'],))
    return removed


def maybe_rename_buyer_card(conn, deal_id):
    contacts = list_deal_contacts(conn, deal_id)
    buyer_names = []
    for item in contacts:
        role = str(item.get('role') or '')
        if BUYER_ROLE_RE.search(role) or role.lower() in {'client', 'primary'}:
            name = contact_name(item)
            if name and name not in buyer_names:
                buyer_names.append(name)
    if not buyer_names:
        return None
    new_title = 'Buyer: ' + ' & '.join(buyer_names[:2])
    conn.execute('UPDATE deals SET title=?, updated_at=? WHERE id=?', (
        new_title,
        datetime.now(timezone.utc).isoformat(),
        deal_id,
    ))
    return new_title


def collapse_deal():
    with connect() as conn:
        deal = get_deal(conn, DEAL_ID)
        if deal is None:
            raise LookupError(f'deal {DEAL_ID!r} not found')
        side = REQUESTED_SIDE or deal.get('side')
        if side not in {'listing', 'buyer'}:
            raise ValueError(f'unsupported deal side {side!r}')
        current_stage = int(deal.get('currentStage') or 0)
        if side == 'listing' and current_stage not in {6, 7}:
            raise ValueError('listing deal collapse is only available from Accepted Offer or Condition Removal')
        if side == 'buyer' and current_stage not in {1, 2, 3}:
            raise ValueError('buyer deal collapse is only available from accepted-offer buyer stages')

        target_stage = LISTING_RESET_STAGE if side == 'listing' else BUYER_RESET_STAGE
        clear_fields = LISTING_CLEAR_FIELDS if side == 'listing' else BUYER_CLEAR_FIELDS
        removed_contacts = remove_listing_buyers(conn, DEAL_ID) if side == 'listing' else []
        removed_extra = scrub_extra(conn, DEAL_ID, LISTING_EXTRA_RE if side == 'listing' else BUYER_EXTRA_RE)
        new_title = None

        set_deal_fields(conn, DEAL_ID, actor=ACTOR, fields=clear_fields)
        if side == 'buyer':
            conn.execute('UPDATE deals SET listing_address=NULL, source_row_id=NULL, updated_at=? WHERE id=?', (
                datetime.now(timezone.utc).isoformat(),
                DEAL_ID,
            ))
            new_title = maybe_rename_buyer_card(conn, DEAL_ID)
        set_deal_toggle(conn, DEAL_ID, field='deal_collapsed', value=True, actor=ACTOR)
        set_deal_toggle(conn, DEAL_ID, field='collapsed_reset_target_stage', value=target_stage, actor=ACTOR)
        set_deal_toggle(conn, DEAL_ID, field='collapsed_reset_side', value=side, actor=ACTOR)
        moved = move_deal_stage(conn, DEAL_ID, to_stage=target_stage, actor=ACTOR, force=True)
        _insert_deal_event(
            conn,
            deal_id=DEAL_ID,
            kind='toggle_change',
            actor=ACTOR,
            field_name='deal_collapsed_reset',
            old_value={'stage': current_stage, 'side': side},
            new_value={'stage': target_stage, 'side': side},
            payload={
                'reason': 'deal_collapsed_button',
                'listingBehavior': 'move_to_listing_live_and_clear_previous_buyers',
                'buyerBehavior': 'move_to_top_25_and_clear_property_information',
                'clearedFields': sorted(clear_fields.keys()),
                'removedBuyerContacts': removed_contacts,
                'removedExtraKeys': sorted(removed_extra.keys()),
                'newTitle': new_title,
            },
        )
        conn.commit()
        return {'deal': moved, 'targetStage': target_stage, 'removedBuyerContacts': len(removed_contacts), 'removedExtraKeys': sorted(removed_extra.keys()), 'newTitle': new_title}

try:
    print(json.dumps({'success': True, **collapse_deal()}, default=str))
except Exception as exc:
    print(json.dumps({'success': False, 'error': str(exc), 'type': exc.__class__.__name__}, default=str))
    sys.exit(1)
`;

  const result = spawnSync(elevatePython(), ['-c', script, dealId, requestedSide ?? ''], {
    cwd: process.cwd(),
    encoding: 'utf-8',
    timeout: 20_000,
    env: process.env,
  });

  const stdout = result.stdout?.trim();
  let parsed: Record<string, unknown> | null = null;
  if (stdout) {
    try {
      parsed = JSON.parse(stdout) as Record<string, unknown>;
    } catch {
      parsed = null;
    }
  }

  if (result.error) {
    return NextResponse.json({ error: result.error.message }, { status: 500 });
  }
  if (result.status !== 0 || !parsed?.success) {
    const error = typeof parsed?.error === 'string'
      ? parsed.error
      : result.stderr?.trim() || stdout || `Collapse command exited ${result.status}`;
    return NextResponse.json({ error }, { status: 500 });
  }

  return NextResponse.json(parsed);
}
