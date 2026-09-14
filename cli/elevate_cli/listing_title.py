"""Listing-intake title research and exact-price purchase approvals on the board."""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _json(value):
    return value if isinstance(value, dict) else json.loads(value or '{}')


def _pid(value):
    return re.sub(r'\D', '', str(value or ''))


def _deal(conn, deal_id):
    row = conn.execute('SELECT * FROM deals WHERE id=? FOR UPDATE', (deal_id,)).fetchone()
    if not row:
        raise ValueError('Listing not found')
    if row['side'] != 'listing' or str(row['province'] or 'BC').upper() != 'BC':
        raise ValueError('LTSA title preparation requires a BC listing')
    return row, _json(row['extra_toggles_json'])


def _runs(conn, deal_id):
    return [r for r in conn.execute('SELECT * FROM admin_action_runs WHERE deal_id=? ORDER BY created_at DESC', (deal_id,)).fetchall()
            if _json(r['payload_json']).get('listingTitlePreparation')]


def _new_run(conn, deal_id, source_run_id=None, prompt=None):
    from elevate_cli.data.dispatch import queue_action_run, update_action
    run = queue_action_run(conn, deal_id=deal_id, skill='real-estate-admin/property-lookup',
        name='Listing Intake: current title and seller names',
        payload={'listingTitlePreparation': True, 'sourceIntakeRunId': source_run_id,
                 'toStage': 2, 'mode': 'listing_intake_title'}, human_prompt=prompt)
    update_action(conn, run['registryId'], skill_args={'mode': 'listing_intake_title'})
    return run


def ensure_title_preparation(conn, deal_id, source_run_id):
    """Intake completion queues research once; it never authorizes a purchase."""
    row = conn.execute('SELECT side,province,current_stage,extra_toggles_json FROM deals WHERE id=? FOR UPDATE', (deal_id,)).fetchone()
    if not row or row['side'] != 'listing' or row['current_stage'] != 2 or str(row['province'] or 'BC').upper() != 'BC':
        return None
    from elevate_cli.mlc_handoff import title_identity_issues
    if not title_identity_issues(_json(row['extra_toggles_json'])):
        return None
    for run in _runs(conn, deal_id):
        if run['status'] in ('queued', 'running', 'waiting_human') or _json(run['payload_json']).get('sourceIntakeRunId') == source_run_id:
            return run['id']
    return _new_run(conn, deal_id, source_run_id)['id']


def title_order_quote(conn, deal_id, quote):
    """Validate parcel and freeze the exact current-title order being authorized."""
    _, extra = _deal(conn, deal_id)
    pid = _pid(quote.get('pid'))
    number = str(quote.get('titleNumber') or '').strip().upper()
    try:
        total = Decimal(str(quote.get('totalCad')))
        quoted = datetime.fromisoformat(str(quote.get('quotedAt') or '').replace('Z', '+00:00'))
    except (InvalidOperation, ValueError):
        raise ValueError('A valid LTSA total and quote timestamp are required')
    if (not total.is_finite() or total <= 0 or total != total.quantize(Decimal('.01'))
            or not re.fullmatch(r'[A-Z]{1,3}\d+', number) or len(pid) != 9
            or pid != _pid(extra.get('pid'))):
        raise ValueError('The title order must match the saved PID and show the exact CAD total')
    if quoted.tzinfo is None:
        raise ValueError('The quote timestamp must include a timezone')
    if quoted > datetime.now(timezone.utc):
        raise ValueError('The title quote timestamp cannot be in the future')
    result = {'provider': 'LTSA', 'product': 'Current registered title', 'currency': 'CAD',
              'pid': f'{pid[:3]}-{pid[3:6]}-{pid[6:]}', 'titleNumber': number,
              'totalCad': format(total, '.2f'), 'quotedAt': quoted.isoformat()}
    result['versionHash'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def _prompt(quote):
    return {'title': 'Approve current title purchase',
            'message': f"Order the current LTSA title {quote['titleNumber']} for PID {quote['pid']} for ${quote['totalCad']} CAD total, including fees and tax. Then verify every seller's full legal name against the title and update the MLC. MLC approval remains blocked until that check is complete.",
            'requiredFields': [], 'actionLabel': f"Approve title purchase — ${quote['totalCad']} CAD",
            'dismissLabel': 'Hold off', 'titleOrder': quote}


def prepare_title_order(conn, deal_id, quote, run_id=None):
    """Publish/revise one board card. Repeated preparation preserves consent/claims."""
    quote = title_order_quote(conn, deal_id, quote)
    from elevate_cli.data.dispatch import _select_action_run_with_registry, _row_to_run, now_iso
    candidates = _runs(conn, deal_id)
    row = next((r for r in candidates if r['id'] == run_id), None) if run_id else next(
        (r for r in candidates if r['status'] in ('waiting_human', 'queued', 'running')), None)
    if run_id and row is None:
        raise ValueError('The title order must belong to this listing title-preparation run')
    if row:
        old = _json(row['human_prompt_json'])
        if old.get('titleOrderClaim'):
            raise ValueError('This title purchase was already started; reconcile the provider order before retrying')
        if row['status'] not in ('waiting_human', 'queued', 'running'):
            raise ValueError('This title-preparation run is no longer active')
        if (old.get('titleOrder') or {}).get('versionHash') == quote['versionHash']:
            return _row_to_run(_select_action_run_with_registry(conn, row['id']))
        conn.execute("UPDATE admin_action_runs SET status='waiting_human',human_prompt_json=?,updated_at=?,completed_at=NULL WHERE id=?",
                     (json.dumps(_prompt(quote)), now_iso(), row['id']))
        return _row_to_run(_select_action_run_with_registry(conn, row['id']))
    return _new_run(conn, deal_id, prompt=_prompt(quote))


def validate_title_order(conn, deal_id, quote, expected_hash):
    current = title_order_quote(conn, deal_id, quote)
    if not expected_hash or expected_hash != current['versionHash'] or quote.get('versionHash') != expected_hash:
        raise ValueError('The title order changed. Refresh and approve its current title, PID and exact fee.')
    return current


def claim_title_order(conn, run_id, quote):
    """Worker must recheck the live order and claim once before clicking Purchase."""
    from elevate_cli.data.dispatch import _run_lookup, now_iso
    conn.execute('SELECT id FROM admin_action_runs WHERE id=? FOR UPDATE', (run_id,)).fetchone()
    row = _run_lookup(conn, run_id)
    prompt = _json(row['human_prompt_json'])
    approved = prompt.get('titleOrder') or {}
    decision = prompt.get('decision') or {}
    if row['status'] not in ('queued', 'running') or decision.get('approved') is not True:
        raise ValueError('The title purchase has not been approved on the Action Board')
    validate_title_order(conn, row['deal_id'], approved, decision.get('titleOrderHash'))
    live = title_order_quote(conn, row['deal_id'], {**quote, 'quotedAt': approved['quotedAt']})
    if live['versionHash'] != approved['versionHash']:
        raise ValueError('The live title order or price changed; prepare a new title-purchase approval')
    if prompt.get('titleOrderClaim'):
        raise ValueError('Title purchase already started. Check LTSA orders; do not purchase twice.')
    prompt['titleOrderClaim'] = {'claimedAt': now_iso(), 'versionHash': approved['versionHash']}
    conn.execute('UPDATE admin_action_runs SET human_prompt_json=? WHERE id=?', (json.dumps(prompt), run_id))
    return {'claimed': True, 'titleOrder': approved}


def title_result_prompt(conn, deal_id, payload, old, incoming, status):
    """Keep purchase consent through callbacks and require title evidence to finish."""
    if not payload.get('listingTitlePreparation'):
        return incoming, status
    # A provider access challenge must not erase the operator's durable title
    # approval. Keep the exact quote and decision on the board while the worker
    # retries the saved local browser session.
    prompt = dict(old or {})
    prompt.update(incoming or {})
    for key in ('titleOrder', 'decision', 'titleOrderClaim'):
        if key not in prompt and key in old:
            prompt[key] = old[key]
    if prompt.get('titleOrder'):
        quote = title_order_quote(conn, deal_id, prompt['titleOrder'])
        prior_quote = old.get('titleOrder') or {}
        if old.get('titleOrderClaim') and quote['versionHash'] != prior_quote.get('versionHash'):
            raise ValueError('A title purchase was started. Reconcile that order before replacing its approval.')
        prompt = {**prompt, **_prompt(quote)}
        prompt.pop('decision', None)
        prompt.pop('titleOrderClaim', None)
        if quote['versionHash'] == prior_quote.get('versionHash'):
            for key in ('decision', 'titleOrderClaim'):
                if key in old:
                    prompt[key] = old[key]
    if status in ('succeeded', 'completed'):
        _, extra = _deal(conn, deal_id)
        from elevate_cli.mlc_handoff import title_identity_issues
        issues = title_identity_issues(extra)
        if issues:
            prompt.update(title='Title verification needs attention', titleVerification=True,
                message='The MLC is still blocked: ' + '; '.join(issues) + '.',
                approvalBlockedReason='Attach the current title and reconcile every seller’s legal name before completing this task.',
                actionLabel='Title verification incomplete')
            return prompt, 'waiting_human'
    return prompt or incoming, status


def resume_documents_after_title(conn, deal_id, title_run_id):
    """Verified title resumes document preparation without granting draft approval."""
    from elevate_cli.mlc_handoff import _mlc_run, title_identity_issues
    from elevate_cli.data.dispatch import now_iso, _insert_run
    _, extra = _deal(conn, deal_id)
    if title_identity_issues(extra):
        return
    prior_documents = None
    resumed = False
    for row in conn.execute('SELECT * FROM admin_action_runs WHERE deal_id=? ORDER BY created_at DESC', (deal_id,)).fetchall():
        _, mode = _mlc_run(conn, row['id'])
        if mode != 'documents':
            continue
        prior_documents = prior_documents or row
        if row['status'] in ('queued', 'running'):
            return  # The existing preparation will use the updated title facts.
        old = _json(row['human_prompt_json'])
        if row['status'] != 'waiting_human' or not (old.get('documentReview') or old.get('title') == 'Listing drafts need preparation'):
            continue
        payload = _json(row['payload_json'])
        payload['verifiedTitleRunId'] = title_run_id
        prompt = {'title': 'Title verified — update listing drafts',
                  'message': 'Rebuild and visually check all selected listing forms using the full verified seller legal names. Then request document approval on the Action Board.',
                  'requiredFields': []}
        conn.execute("UPDATE admin_action_runs SET status='queued',human_prompt_json=?,payload_json=?,cron_job_id=NULL,result_idempotency_key=NULL,result_json=NULL,error_message=NULL,completed_at=NULL,updated_at=? WHERE id=?",
                     (json.dumps(prompt), json.dumps(payload), now_iso(), row['id']))
        resumed = True
    if not resumed and prior_documents:
        # A dismissed pre-title review stays dismissed. New verified facts get
        # a fresh preparation run rather than reviving that declined decision.
        _insert_run(conn, registry_id=prior_documents['registry_id'], deal_id=deal_id,
                    deal_event_id=None, payload={'toStage': 2, 'verifiedTitleRunId': title_run_id,
                    'sourceDocumentRunId': prior_documents['id'], 'continuationReason':
                    'Title verified; regenerate listing forms with full seller legal names and request fresh document approval.'})
