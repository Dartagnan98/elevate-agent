"""Listing intake continuation and review of PDFs actually saved in the kit."""
import hashlib
import json
import re
from pathlib import Path


def _json(value):
    return value if isinstance(value, dict) else json.loads(value or '{}')


def _mlc_run(conn, run_id):
    row = conn.execute(
        'SELECT r.*, reg.skill, reg.skill_args_json FROM admin_action_runs r '
        'JOIN admin_action_registry reg ON reg.id=r.registry_id WHERE r.id=?', (run_id,)
    ).fetchone()
    if not row or row['skill'] not in {'mlc', 'real-estate-admin/mlc'}:
        return None, None
    return row, _json(row['skill_args_json']).get('mode')


def resume_documents_after_intake(conn, deal_id, run_id):
    """Queue a skipped document step once, retaining its actual invocation mode."""
    source, mode = _mlc_run(conn, run_id)
    if mode != 'intake' or source['status'] not in {'succeeded', 'completed'}:
        return None
    from elevate_cli.listing_title import ensure_title_preparation
    ensure_title_preparation(conn, deal_id, run_id)
    deal = conn.execute('SELECT side,current_stage FROM deals WHERE id=? FOR UPDATE', (deal_id,)).fetchone()
    if not deal or deal['side'] != 'listing' or deal['current_stage'] != 2:
        return None
    candidates = conn.execute(
        'SELECT r.*, reg.skill_args_json FROM admin_action_runs r '
        'JOIN admin_action_registry reg ON reg.id=r.registry_id '
        "WHERE r.deal_id=? AND reg.skill IN ('mlc','real-estate-admin/mlc') ORDER BY r.created_at DESC", (deal_id,)
    ).fetchall()
    skipped = None
    for row in candidates:
        payload = _json(row['payload_json'])
        if payload.get('sourceIntakeRunId') == run_id:
            return row['id']
        if _json(row['skill_args_json']).get('mode') != 'documents':
            continue
        # Only the same stage-entry cycle. Do not revive an old listing cycle.
        if not source['deal_event_id'] or row['deal_event_id'] != source['deal_event_id']:
            continue
        if row['status'] != 'skipped':
            return row['id']
        skipped = skipped or row
    if skipped is None:
        return None
    from elevate_cli.data.dispatch import _insert_run
    payload = _json(skipped['payload_json'])
    payload.pop('result', None)
    payload.update(sourceIntakeRunId=run_id, deferredFromRunId=skipped['id'],
                   continuationReason='Listing intake completed; prepare the listing-kit PDFs and request document review.')
    result = _insert_run(conn, registry_id=skipped['registry_id'], deal_id=deal_id,
                         deal_event_id=None, payload=payload)
    return result['id']


def document_review_prompt(conn, deal_id, run_id, existing_prompt=None):
    """A documents-mode success is a review handoff, never silent completion."""
    _source, mode = _mlc_run(conn, run_id)
    if mode != 'documents':
        return None
    old = existing_prompt or {}
    review = listing_document_review(conn, deal_id)
    issues = listing_preparation_issues(conn, deal_id) if review else []
    if (review and not issues and (old.get('decision') or {}).get('approved') is True
            and (old.get('decision') or {}).get('documentVersionHash') == review['versionHash']):
        return None
    if review is None:
        return {'title': 'Listing drafts need preparation',
                'message': 'The selected listing forms are not all saved as current PDFs. Open Listing Intake documents on the scorecard and finish preparation.',
                'requiredFields': ['Approve retrying document preparation'],
                'actionLabel': 'Retry preparation'}
    warnings = review.pop('warnings', [])
    return {'title': 'Listing drafts need correction' if issues else 'Review listing drafts',
            'message': f"Open the {len(review['documents'])} listing drafts using the document links, or review/edit them in the scorecard's Listing Intake section. Sending for signature requires a separate approval." +
                       (' Review notes: ' + '; '.join(w.rstrip('.; ') for w in warnings) + '.' if warnings else ''),
            'requiredFields': [],
            'actionLabel': 'Approve drafts for signature setup',
            'documentReview': review,
            **({'approvalBlockedReason': 'Before approving: ' + '; '.join(issues)} if issues else {})}


def title_identity_issues(t):
    """A receipt must reconcile the actual registered owners and legal spelling."""
    title = t.get('listingTitleVerification') or {}
    issues = []
    path = Path(str(title.get('filePath') or ''))
    try:
        title_bytes = path.read_bytes()
        actual_hash = hashlib.sha256(title_bytes).hexdigest() if title_bytes.startswith(b'%PDF-') else ''
    except OSError:
        actual_hash = ''
    if not actual_hash or actual_hash != title.get('sha256') or not title.get('searchedAt'):
        issues.append('obtain and attach the current LTSA title')
    else:
        import unicodedata
        normalize = lambda value: ' '.join(unicodedata.normalize('NFC', str(value)).casefold().split())
        sellers = t.get('sellerLegalNames') or [s.get('name') for s in t.get('onboardingSellers', []) if isinstance(s, dict)]
        if isinstance(sellers, str):
            sellers = [sellers]
        current_sellers = sorted(normalize(s) for s in sellers if s)
        matched = sorted(normalize(s) for s in title.get('matchedSellerNames', []) if s)
        owners = sorted(normalize(s) for s in title.get('registeredOwners', []) if s)
        if (title.get('status') != 'verified' or title.get('ownerMatch') is not True
                or not owners or not current_sellers or current_sellers != matched or matched != owners
                or re.sub(r'\D', '', str(t.get('pid'))) != re.sub(r'\D', '', str(title.get('pid')))):
            issues.append('reconcile all sellers and their full legal spelling against the registered title owners')
    return issues


def listing_preparation_issues(conn, deal_id):
    """A BC listing needs verified title identities in the actual MLC PDF."""
    row = conn.execute('SELECT province,extra_toggles_json FROM deals WHERE id=?', (deal_id,)).fetchone()
    if not row or str(row['province'] or 'BC').upper() != 'BC':
        return []
    t = _json(row['extra_toggles_json'])
    from elevate_cli.web_routes.kit_context import seller_mailing_parts, retained_commission
    issues = title_identity_issues(t)
    mailing = seller_mailing_parts(t)
    if not all(mailing[k] for k in ('sellerStreet','sellerCity','sellerState','sellerZip')):
        issues.append('complete the seller mailing address')
    mlc = next((d for d in (t.get('listingKit') or {}).get('documents', []) if d.get('id') == 'mlc'), {})
    retained = (mlc.get('pdfWidgetOverrides') or {}).get('txtEqualTo3', (mlc.get('fields') or {}).get('commissionRetained', retained_commission(t)))
    if not str(retained or '').strip():
        issues.append('complete the listing brokerage retained commission in Section 5 D(ii)')
    if not title_identity_issues(t):
        # Check the saved form, including widget edits that can override deal facts.
        import fitz
        normalize = lambda s: ' '.join(str(s).casefold().split())
        expected = sorted(normalize(s) for s in t['listingTitleVerification']['matchedSellerNames'])
        try:
            with fitz.open(mlc.get('filePath') or '') as pdf:
                values = {w.field_name.lower(): w.field_value or '' for page in pdf for w in page.widgets() or []}
            for prefix in ('txtseller', 'txtsellersig'):
                actual = sorted(normalize(values.get(prefix + str(i), '')) for i in (1,2,3) if values.get(prefix + str(i)))
                if actual != expected:
                    raise ValueError('MLC seller names differ from title')
        except (OSError, RuntimeError, ValueError):
            issues.append('regenerate the MLC with every seller’s full title-verified legal name in the seller and signature blocks')
    return issues


def listing_document_review(conn, deal_id):
    """Bind review to every selected form, its current inputs and actual bytes."""
    row = conn.execute('SELECT extra_toggles_json FROM deals WHERE id=?', (deal_id,)).fetchone()
    if not row:
        return None
    toggles = _json(row['extra_toggles_json'])
    from elevate_cli.web_routes.kit_state import selected_documents, input_hash
    included = toggles.get('listingKitForms') or {}
    defaults = {'mlc': True, 'dorts': True, 'pnc': True, 'pds': True,
                'pds-rural-addendum': False, 'pds-no-disclosure': False}
    stored = (toggles.get('listingKit') or {}).get('documents', [])
    ids = sorted({'mlc'} | {k for k, v in {**defaults, **included}.items() if v}
                 | {d['id'] for d in stored if d.get('id') not in defaults and included.get(d['id']) is not False})
    try:
        docs = selected_documents(toggles, 'listingKit', ids)
        import fitz
        documents = []
        for doc in docs:
            if doc.get('ready') is False:
                return None
            path = Path(doc['filePath'])
            with fitz.open(path) as pdf:
                if not pdf.is_pdf or pdf.page_count < 1 or pdf.needs_pass:
                    return None
            documents.append({'id': doc['id'], 'name': doc.get('name') or doc['id'],
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                              'inputHash': input_hash(toggles, doc),
                              'generatedAt': doc.get('generatedAt', '')})
    except (ValueError, OSError, RuntimeError):
        return None
    version = hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()
    return {'kit': 'listing', 'versionHash': version, 'documents': documents,
            'warnings': list(dict.fromkeys(str(w) for d in docs for w in d.get('warnings', [])))}


def validate_document_review(conn, deal_id, review):
    current = listing_document_review(conn, deal_id)
    if not current or current['versionHash'] != review.get('versionHash'):
        raise ValueError('Listing documents changed or are incomplete. Redraft and review the current PDFs before approving.')
    issues = listing_preparation_issues(conn, deal_id)
    if issues:
        raise ValueError('Before approving: ' + '; '.join(issues))
    return current


def refresh_document_reviews(conn, deal_id):
    """Keep an open review accurate after regeneration or kit edits."""
    rows = conn.execute("SELECT id,human_prompt_json FROM admin_action_runs WHERE deal_id=? AND status='waiting_human'", (deal_id,)).fetchall()
    for row in rows:
        old = _json(row['human_prompt_json'])
        if not old.get('documentReview') and old.get('title') != 'Listing drafts need preparation':
            continue
        prompt = document_review_prompt(conn, deal_id, row['id'])
        if prompt:
            conn.execute('UPDATE admin_action_runs SET human_prompt_json=? WHERE id=?', (json.dumps(prompt), row['id']))
