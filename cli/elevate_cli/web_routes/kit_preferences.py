"""Account-scoped document preparation preferences (never transaction values)."""
import json
import os
import tempfile
from pathlib import Path

FIELDS = {'cpsDepositTerms', 'cpsDepositHolder', 'designatedAgency', 'designatedAgency2', 'listingCommission', 'buyerAgencyComp'}


def preference_path():
    from elevate_constants import get_account_key, get_elevate_home
    return Path(get_elevate_home()) / 'preferences' / get_account_key() / 'document-kit.json'


def read_preferences(path=None):
    path = Path(path) if path is not None else preference_path()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('Saved kit preferences are invalid. Save your preferences again.')
    return {k: str(v) for k, v in raw.items() if k in FIELDS and isinstance(v, str)}


def write_preferences(values, path=None):
    if set(values) - FIELDS:
        raise ValueError('Unsupported kit preference')
    if any(not isinstance(v, str) or len(v) > 2000 for v in values.values()):
        raise ValueError('Preference values must be text of at most 2000 characters')
    path = Path(path) if path is not None else preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {k: values.get(k, '').strip() for k in FIELDS}
    fd, temporary = tempfile.mkstemp(prefix='.kit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(cleaned, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return read_preferences(path)
