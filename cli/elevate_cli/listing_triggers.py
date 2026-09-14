"""BC listing triggers shared by chat, UI and verified-document review.

Call within connect(); allow exceptions to escape to roll back stage and queue.
Semantic evidence is attested by the caller; attachment ownership/bytes and
repeat delivery are enforced here. No external send occurs in this module.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping
from elevate_cli.data.deals import get_deal, move_deal_stage, _insert_deal_event, set_deal_fields, set_deal_toggle
from elevate_cli.data.dispatch import evaluate, queue_action_run

TARGETS = {'comps_requested': 1, 'listing_prep_requested': 2,
 'platform_prep_requested': 3, 'signed_mlc_received': 3,
 'marketing_prep_requested': 4, 'photos_received': 4,
 'mls_activation_requested': 5, 'mls_live_verified': 5,
 'accepted_offer_requested': 6, 'signed_cps_received': 6,
 'condition_removal_confirmed': 7, 'signed_removal_received': 7}
DOCUMENTS = {'signed_mlc_received', 'signed_cps_received', 'signed_removal_received'}
REQUESTS = {k for k in TARGETS if k.endswith('_requested')} | {'condition_removal_confirmed'}
EXPECTED = {'comps_requested': {0, 1}, 'signed_mlc_received': {2, 3},
 'photos_received': {3, 4}, 'signed_cps_received': {5, 6},
 'signed_removal_received': {6, 7}, 'condition_removal_confirmed': {6, 7},
 'accepted_offer_requested': {5, 6}}

def text(evidence, key):
    value = evidence.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'evidence.{key} is required')
    return value.strip()

def attachment_sha(conn, deal_id, evidence):
    aid, expected = text(evidence, 'attachmentId'), text(evidence, 'sha256').lower()
    row = conn.execute('SELECT file_path FROM deal_attachments WHERE id=? AND deal_id=?', (aid, deal_id)).fetchone()
    if row is None:
        raise ValueError('evidence attachment must belong to this deal')
    with Path(row['file_path']).open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        raise ValueError('evidence attachment checksum changed')
    return actual

def validate(conn, deal_id, trigger, evidence, to_stage=None):
    if not isinstance(evidence, Mapping):
        raise ValueError('evidence must be an object')
    if trigger == 'manual_stage_move':
        if type(to_stage) is not int or not 0 <= to_stage <= 7:
            raise ValueError('manual listing trigger target must be 0 through 7')
        target = to_stage
    elif trigger in TARGETS:
        target = TARGETS[trigger]
    else:
        raise ValueError('unknown listing trigger')
    source = text(evidence, 'sourceId')
    if evidence.get('matchConfirmed') is not True:
        raise ValueError('confirm one matching listing before triggering work')
    if trigger in REQUESTS or trigger == 'manual_stage_move':
        if evidence.get('userRequested') is not True:
            raise ValueError('this trigger requires an explicit user request')
        text(evidence, 'requestText')
    if trigger in DOCUMENTS:
        if evidence.get('fullySigned') is not True or evidence.get('currentContractConfirmed') is not True:
            raise ValueError('verified full execution and current-contract match are required')
        text(evidence, 'verificationNotes')
        text(evidence, 'contractId')
    if trigger in {'signed_removal_received', 'condition_removal_confirmed'} and evidence.get('allConditionsRemoved') is not True:
        raise ValueError('partial condition removal requires review; do not mark the deal firm')
    if trigger in DOCUMENTS or trigger == 'photos_received':
        source = attachment_sha(conn, deal_id, evidence)
    if trigger == 'mls_live_verified':
        if evidence.get('publicationVerified') is not True:
            raise ValueError('MLS publication must be verified')
        text(evidence, 'verificationNotes')
        source = text(evidence, 'mlsNumber')
    return target, hashlib.sha256(f'{trigger}:{source}'.encode()).hexdigest()

def lock_deal(conn, deal_id):
    if conn.execute('SELECT id FROM deals WHERE id=? FOR UPDATE', (deal_id,)).fetchone() is None:
        raise LookupError('listing deal not found')
    deal = get_deal(conn, deal_id)
    if deal['side'] != 'listing' or str(deal.get('province') or '').lower() != 'bc':
        raise ValueError('listing triggers currently support BC listing deals only')
    if deal.get('status') != 'active':
        raise ValueError('cannot trigger an archived or inactive listing')
    return deal

def prior_event(conn, deal_id, key):
    for row in conn.execute('SELECT id,payload_json FROM deal_events WHERE deal_id=? ORDER BY created_at DESC', (deal_id,)).fetchall():
        if (json.loads(row['payload_json'] or '{}').get('listingTrigger') or {}).get('key') == key:
            return row['id']
    return None

def runs_for(conn, event_id):
    return [dict(r) for r in conn.execute('SELECT id,status FROM admin_action_runs WHERE deal_event_id=?', (event_id,)).fetchall()]

def queue(conn, deal_id, event_id, skill, evidence, actor, name):
    run = queue_action_run(conn, deal_id=deal_id, skill='real-estate-admin/'+skill, name=name,
        payload={'listingTriggerEvidence': dict(evidence), 'resumeExistingArtifacts': True}, actor=actor)
    conn.execute('UPDATE admin_action_runs SET deal_event_id=? WHERE id=?', (event_id, run['id']))
    return run

def retry_queue_failures(conn, event_id):
    # Only a failed cron-creation attempt is safe to retry automatically on an
    # explicit repeat. Never re-run failed business work or a possible send.
    rows = conn.execute("SELECT id,payload_json FROM admin_action_runs WHERE deal_event_id=? AND status='failed' AND cron_job_id IS NULL", (event_id,)).fetchall()
    for row in rows:
        payload = json.loads(row['payload_json'] or '{}')
        if payload.pop('dispatchError', None):
            conn.execute("UPDATE admin_action_runs SET status='queued',error_message=NULL,completed_at=NULL,payload_json=? WHERE id=?",
                         (json.dumps(payload), row['id']))

def apply_listing_trigger(conn, deal_id, *, trigger, evidence, actor, to_stage=None):
    deal = lock_deal(conn, deal_id)
    target, key = validate(conn, deal_id, trigger, evidence, to_stage)
    old = int(deal['currentStage'])
    prior = prior_event(conn, deal_id, key)
    if prior:
        retry_queue_failures(conn, prior)
        return {'deal': deal, 'outcome': 'duplicate', 'eventId': prior, 'runs': runs_for(conn, prior)}
    if target < old and trigger != 'manual_stage_move':
        return {'deal': deal, 'outcome': 'already_beyond_stage', 'runs': []}
    if trigger in EXPECTED and old not in EXPECTED[trigger]:
        raise ValueError(f'{trigger} does not apply to current stage {old}')
    continuation = old == target and trigger in {'photos_received', 'signed_mlc_received', 'signed_cps_received', 'signed_removal_received', 'mls_live_verified', 'mls_activation_requested'}
    if old == target and not continuation:
        return {'deal': deal, 'outcome': 'already_in_stage', 'runs': []}
    context = {'key': key, 'trigger': trigger, 'evidence': dict(evidence)}
    if old != target:
        move_deal_stage(conn, deal_id, to_stage=target, actor=actor, gate_checked=True,
                        dispatch_events=False, transition_context={'listingTrigger': context})
        event_id = prior_event(conn, deal_id, key)
    else:
        event_id = _insert_deal_event(conn, deal_id=deal_id, kind='agent_activity', actor=actor,
                                     payload={'listingTrigger': context})['id']
    if trigger == 'mls_activation_requested':
        set_deal_toggle(conn, deal_id, actor=actor, field='listingActivationStatus', value='requested', dispatch_events=False)
    if trigger == 'mls_live_verified':
        set_deal_toggle(conn, deal_id, actor=actor, field='listingActivationStatus', value='verified_live', dispatch_events=False)
        set_deal_fields(conn, deal_id, actor=actor, fields={'mlsNumber': evidence['mlsNumber']})
    if old != target:
        evaluate(conn, deal_id=deal_id, deal_event_id=event_id, trigger='stage_exit',
                 from_stage=old, actor=actor, create_cron_jobs=False, notify_human=False, extra_payload=context)
        runs = evaluate(conn, deal_id=deal_id, deal_event_id=event_id, trigger='stage_entry',
                 to_stage=target, actor=actor, create_cron_jobs=False, notify_human=False, extra_payload=context)
        if not runs:
            raise ValueError('no enabled workflow for this stage; stage move rolled back')
    elif continuation and trigger != 'mls_activation_requested':
        skill = {'signed_mlc_received': 'skyslope-sync', 'signed_cps_received': 'offer-review',
                 'signed_removal_received': 'subject-removal'}.get(trigger, 'marketing')
        queue(conn, deal_id, event_id, skill, evidence, actor, 'Resume existing listing work with new verified evidence')
        if trigger == 'signed_mlc_received':
            queue(conn, deal_id, event_id, 'matrix-incomplete-listing', evidence, actor,
                  'Resume existing incomplete listing with verified signed MLC')
    if trigger == 'mls_activation_requested':
        queue(conn, deal_id, event_id, 'listing-activation', evidence, actor, 'Send requested listing activation to configured BC Listings recipient')
    return {'deal': get_deal(conn, deal_id), 'outcome': 'updated' if old == target else 'moved',
            'eventId': event_id, 'runs': runs_for(conn, event_id)}

def queue_document_review(conn, deal_id, *, source_id, attachments, actor='gmail-doc-router'):
    deal = lock_deal(conn, deal_id)
    if int(deal['currentStage']) > 7 or not attachments:
        return {'outcome': 'not_applicable'}
    shas = sorted({attachment_sha(conn, deal_id, a) for a in attachments})
    key = hashlib.sha256(('document_review:'+':'.join(shas)).encode()).hexdigest()
    prior = prior_event(conn, deal_id, key)
    if prior:
        return {'outcome': 'duplicate', 'eventId': prior, 'runs': runs_for(conn, prior)}
    evidence = {'sourceId': source_id, 'attachments': attachments}
    event_id = _insert_deal_event(conn, deal_id=deal_id, kind='agent_activity', actor=actor,
        payload={'listingTrigger': {'key': key, 'trigger': 'document_review', 'evidence': evidence}})['id']
    queue(conn, deal_id, event_id, 'listing-event-review', evidence, actor, 'Verify inbound listing documents and apply authorized stage trigger')
    return {'outcome': 'queued', 'eventId': event_id, 'runs': runs_for(conn, event_id)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file', required=True, help='JSON: deal_id, trigger, evidence')
    args = parser.parse_args()
    from elevate_cli.data.connection import connect
    from elevate_cli.access import is_entitlement_active, ENTITLEMENT_REAL_ESTATE_ADMIN
    if not is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None):
        raise SystemExit('real_estate_admin entitlement required')
    request = json.loads(Path(args.request_file).read_text())
    with connect() as conn:
        result = apply_listing_trigger(conn, request['deal_id'], trigger=request['trigger'],
             evidence=request['evidence'], to_stage=request.get('to_stage'), actor='agent:listing-trigger')
    print(json.dumps(result))

if __name__ == '__main__':
    main()
