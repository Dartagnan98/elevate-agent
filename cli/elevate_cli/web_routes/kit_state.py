"""Document provenance and validation shared by buyer and listing kits."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import uuid


def version_path(previous):
    return str(Path(previous).parent / f"document-{uuid.uuid4().hex}.pdf")


def source_hash(toggles):
    # Ignore UI checkpoints and package metadata; conservatively invalidate on
    # other deal inputs, including inputs written by agents outside the wizard.
    source = {k: v for k, v in toggles.items()
              if k not in ('offerKit', 'listingKit', 'cpsKitForms', 'listingKitForms')
              and not k.lower().endswith(('step', 'collapsed', 'open'))}
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()


def input_hash(toggles, doc):
    common = next((d.get('fields', {}) for d in (toggles.get('offerKit') or {}).get('documents', []) if d.get('id') == 'cps-residential'), {})
    inputs = [source_hash(toggles), common, doc.get('fields', {})]
    if doc.get('pdfWidgetOverrides'):
        inputs.append(doc['pdfWidgetOverrides'])
    if 'pdfTermsOverride' in doc:
        inputs.append({'pdfTermsOverride': doc['pdfTermsOverride']})
    return hashlib.sha256(json.dumps(inputs,
                                    sort_keys=True, default=str).encode()).hexdigest()


def stale(doc, toggles=None):
    edited, generated = str(doc.get('editedAt') or ''), str(doc.get('generatedAt') or '')
    return bool((edited and (not generated or edited > generated)) or
                (toggles is not None and doc.get('generatedInputHash') and
                 doc['generatedInputHash'] != input_hash(toggles, doc)))


def seed_fields(previous, seed):
    fields = dict(previous.get('fields') or {})
    old_seed = previous.get('seededFields')
    overrides = dict(previous.get('fieldOverrides') or {})
    if old_seed is None:
        # Historic fields have no reliable provenance. Never silently replace a
        # possibly intentional edit: ask for an explicit field confirmation.
        ambiguous = [k for k, v in fields.items() if k in seed and v and
                     v != seed[k] and k not in overrides]
        if ambiguous:
            raise ValueError('Confirm these existing document fields in the editor before rebuilding: ' + ', '.join(ambiguous))
    else:
        for key, value in fields.items():
            if key not in overrides and key in old_seed and value != old_seed[key]:
                overrides[key] = value
    fields.update(seed)
    fields.update(overrides)  # Explicit empty edits are intentional too.
    return fields, dict(seed), overrides


def invalidate(toggles):
    now = datetime.utcnow().isoformat()
    for key in ('offerKit', 'listingKit'):
        for doc in (toggles.get(key) or {}).get('documents', []):
            if doc.get('filePath'):
                doc['editedAt'] = now
                doc['status'] = 'draft'


def selected_documents(toggles, kit_key, ids):
    docs = (toggles.get(kit_key) or {}).get('documents', [])
    forms = toggles.get('listingKitForms' if kit_key == 'listingKit' else 'cpsKitForms') or {}
    by_id = {d.get('id'): d for d in docs}
    if not ids:
        raise ValueError('Select at least one document to review.')
    chosen = []
    for ident in dict.fromkeys(ids):
        doc = by_id.get(ident)
        if not doc:
            raise ValueError(f'Selected document is missing: {ident}')
        if kit_key == 'offerKit' and ((ident == 'cps-addendum' and toggles.get('cpsUmbrella') == 'mobile') or (ident == 'cps-mobile-addendum' and toggles.get('cpsUmbrella') != 'mobile')):
            raise ValueError(f'Document does not match this property type: {ident}')
        if forms.get(ident) is False and not (kit_key == 'listingKit' and ident == 'mlc'):
            raise ValueError(f'Document is excluded from this kit: {ident}')
        if not doc.get('filePath') or not os.path.isfile(str(doc['filePath'])):
            raise ValueError(f'Draft the selected document first: {ident}')
        if stale(doc, toggles):
            raise ValueError(f'Redraft before review — inputs changed: {ident}')
        chosen.append(doc)
    return chosen
