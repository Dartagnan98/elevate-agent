---
name: gmail-doc-router-scan-wrapper-json-guard
description: "Patch a local Gmail scan wrapper JSON parser to ignore keyring or trailing status text. Use when a gmail-doc-router cron tick must tell true zero-new-documents apart from a parser failure, especially after \"JSONDecodeError: Extra data.\" Not for the cron preflight-order check — use gmail-doc-router-api-preflight-guard instead."
metadata:
  elevate:
    tags: [real-estate, admin, gmail, cron, documents]
---

# Gmail Doc Router Scan Wrapper JSON Guard

Use this when a Gmail Doc Router cron run uses a local/maintained Python scan wrapper around `gws gmail`, especially before returning `[SILENT]` from a no-new-documents tick.

## Trigger

- A Gmail Doc Router run invokes a local script such as `$HOME/tmp/gmail_doc_router_scan.py`.
- `gws` output may include keyring/status lines before JSON or extra status/error text after JSON.
- The run must distinguish true zero/newly-seen results from parser failure.

## Procedure

1. Keep the mandatory first-class preflight first: `composio(status)`, `composio(accounts, toolkit='gmail')`, and `deals_overview()` or `elevate_db(describe)`.
2. Before running a local scan wrapper, inspect its JSON parser if it has not been checked recently.
3. If the helper uses `json.loads(stdout[idx:])`, patch it to use `json.JSONDecoder().raw_decode(...)` so trailing non-JSON text is ignored.
4. Parser pattern:

```python
def parse_jsonish(stdout):
    objs = []
    dec = json.JSONDecoder()
    for line in stdout.splitlines():
        s = line.strip()
        if not s:
            continue
        idx = s.find('{')
        if idx < 0:
            continue
        try:
            obj, _ = dec.raw_decode(s[idx:])
            objs.append(obj)
        except Exception:
            pass
    if not objs:
        idx = stdout.find('{')
        if idx >= 0:
            obj, _ = dec.raw_decode(stdout[idx:])
            objs.append(obj)
    return objs
```

5. Run the wrapper with the Elevate CLI venv and a known CA bundle:

```bash
PYTHONPATH=/Applications/Elevate.app/Contents/Resources/cli \
SSL_CERT_FILE=/etc/ssl/cert.pem \
/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python3 /path/to/gmail_doc_router_scan.py
```

(Adjust the app bundle path if Elevate is installed somewhere other than the default `/Applications` location.)

6. Before returning `[SILENT]`, verify the scan output shows:
   - bounded query counts for portal envelopes and subject-removal/address rows,
   - active address-backed rows using full civic phrases, not truncated prefixes,
   - `unique_count == seen_count`,
   - `unseen_count == 0`,
   - no blocker/error rows.

## Pitfall

Do not treat `JSONDecodeError: Extra data` as a Gmail/auth/search failure. It often means valid JSON was followed by extra wrapper output. Patch the parser, rerun, and only then decide whether the tick is silent.
