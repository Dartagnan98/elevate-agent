---
name: xposure-pcs-pipeline
description: Extract Xposure Private Client Search (PCS) buyer activity and score leads HOT/WARM/cold. Use when running or maintaining the Xposure/PCS buyer watchlist pipeline, especially AIR-board Xposure data feeding a Lofty CRM tag/stage sync.
---

# Xposure PCS Pipeline

Use this when asked to run or maintain the Xposure / Private Client Search buyer watchlist pipeline, especially for AIR board Xposure data and Lofty CRM sync.

## Preconditions

- Xposure portal: `https://interiorrealtors.xposureapp.com/`
- Board observed in this setup: `AIR`
- MLS credentials may be stored in `~/.elevate/.env` as `MLS_USERNAME` and `MLS_PASSWORD`.
- Lofty API key may be stored in `~/.elevate/.env` as `LOFTY_API_KEY`.
- Operational data source of truth is the embedded Postgres-backed Elevate store via `deals_overview` / `elevate_db` / `elevate_cli.data`; do not use old local SQLite operational DB paths for admin/CRM/deal records.
- Never print secrets, browser cookies, API keys, MLS username/password, or raw PII in final reports.

## Core approach

1. **Authenticate to Xposure in the browser**
   - Open `https://interiorrealtors.xposureapp.com/`.
   - Select board `AIR` if the login page requires board selection.
   - Fill credentials from environment programmatically; do not display them.
   - After login, remove blocking modal/backdrop if needed:
     ```js
     document.querySelectorAll('.modal, [role=dialog]').forEach(e => e.remove());
     document.body.classList.remove('modal-open');
     document.querySelectorAll('.modal-backdrop').forEach(e => e.remove());
     ```

2. **Fetch PCS contacts via authenticated browser session**
   - Confirmed endpoint:
     ```text
     /portal/air/Contacts?getJSON=true&swapFirstLastNames=false&statusFilter=&listingFilter=&orderByName=&orderByAsc=
     ```
   - Fetch from the browser context so the authenticated Xposure cookies are used.
   - Expected contact fields may include:
     - `contactId`
     - `rv_full_name`
     - `email`
     - `cell_phone`, `home_phone`
     - `pcs_last_login`
     - `searches[]`
     - `searchId`
     - `title`
     - `isActive`
     - `isSelfManaged`
     - `favorites_count`
     - `listingsCount`

3. **Extract HOT buyer saved-search details**
   - Inspect `/static/responsive/js/pcs-contacts.js?v=2.9` if endpoints or form parameters drift.
   - Saved-search details can be pulled by POSTing to:
     ```text
     /portal/air/ManageClients
     ```
   - Useful form fields discovered:
     - `currentContactID`
     - `currentSearchID`
     - `currentSubTab=ViewSearch`
   - If one large browser extraction times out, use smaller batches and stage interim JSON files locally.

4. **Score buyers**
   - HOT: `pcs_last_login` active within 30 days.
   - WARM: active within 90 days.
   - cold: older/no activity.
   - For HOT buyers, capture saved-search criteria such as areas, beds, property type/subtype, and search title.

5. **Stage normalized source data**
   - Write a redacted/normalized payload under the appropriate source/staging directory, or temporarily at `/tmp/pcs_payload.json` while developing.
   - Include run metadata: run timestamp, counts, buyer IDs, search IDs, activity score, criteria, and CRM match status.
   - Do not include secrets or cookies. Avoid user-visible raw PII unless required for the operation.

6. **Sync to Elevate operational store when needed**
   - Admin, CRM, outreach, and deal-file data live in the embedded Postgres-backed Elevate operational store, not old local SQLite files.
   - Use `elevate_db.describe` to confirm available tables/functions, then `elevate_db.query` for read-only checks or approved curated write helpers via `elevate_cli.data` / `elevate_db.call` where available.
   - Push deltas rather than full destructive rewrites where possible.

7. **Sync to Lofty CRM safely**
   - Lofty API access was confirmed with:
     ```text
     GET https://api.lofty.com/v1.0/leads?page=1&per_page=1
     Authorization: token [REDACTED]
     ```
   - Lofty lead list supports precise search by `email` and `phone`, plus `key` for name/phone/email.
   - For non-destructive tag updates, use:
     ```text
     PUT /v1.0/leads/{leadId}
     ```
     with `tagsAdd`, not `tags`.
   - `tags` replaces all existing tags; avoid it unless intentionally doing a full tag replacement.
   - `/v1.0/agent/{agentId}/tag/add` is for tagging agents, not leads.
   - Recommended tag for these records: `xposure-pcs`.
   - Stage/stage-name updates require reading the current Lofty API schema and preserving existing lead fields.

8. **Generate branded watchlist PDF/report**
   - Check installed PDF/report libraries first. In one observed environment, `reportlab`, `fpdf`, `weasyprint`, `PIL`, and `matplotlib` were not installed, while macOS `textutil` existed.
- If PDF libraries are unavailable, generate HTML/Markdown first, then convert with available local tools.
- The existing `run_pipeline_finalize.py` may complete DB/CRM work but leave `files.pdf=null` when `reportlab` is missing. In that case, do not rerun the whole pipeline; generate the watchlist from `latest-summary.json` + the run payload, write `<run_id>-hot-watchlist.html` and `<run_id>-hot-watchlist.pdf`, then patch both `<run_id>-summary.json` and `latest-summary.json` with the PDF/HTML paths.
- On macOS, `textutil` may exist but does not reliably create multi-page PDFs from HTML. If `reportlab`/`fpdf`/`weasyprint` are unavailable and no converter is installed, generate a minimal PDF directly with Python stdlib: create pages with Helvetica/Helvetica-Bold Type1 fonts, write text streams, xref table, and trailer. Verify with `file <pdf>` (must say `PDF document`) and confirm page count/size.
- Include:
  - branded cover
  - per-lead cards
  - score
  - last active date
  - areas
  - beds
  - property type
  - short call script

## Pitfalls and learned constraints

- `elevate sync xposure --json` returned `Unknown source connector: xposure`; do not assume a built-in connector exists.
- `search_files` over broad directories like `/Users/admin` may time out. Narrow to `~/.elevate` or exact project paths.
- Browser console output can expose cookies if `document.cookie` is printed. Never print or persist cookie values.
- Do not print credentials from `.env` while debugging login, even in terminal output. Use only boolean/status checks such as `has_creds=True`; terminal output may be captured in transcripts.
- Browser Use CLI `input` echoes the typed value in JSON output, so do not use it for passwords or other secrets in logged terminal runs. For secret entry, use CDP/Browser Use `eval` with local env values and print only redacted booleans like `{filledPassword:true}`; if a CLI command could echo secrets, suppress or sanitize stdout before it enters the transcript.
- When debugging login DOM state, do not print raw `input.value`, `textContent`, serialized button lists, or hidden fields. Some IAM pages expose typed credentials in element values/text snapshots. Print only booleans (`filledUser`, `filledPassword`, `clicked`) and sanitized URL/page-state labels.
- If you must inspect candidate DOM elements on the IAM login page, never use a fallback like `textContent || value` because `<input>` elements will leak the entered username/password. For inputs, print only tag/id/type/placeholder/required/disabled and redact or omit all `value` fields before stdout.
- Shell commands that pipe secret-reading code or embed credentials may trigger security scanning. Use safe Python/urllib and print only statuses, counts, and redacted metadata.
- Direct `requests` login may appear to succeed but then redirect the contacts endpoint to `interfacexpress.com/portal/Login` instead of returning JSON. If that happens, authenticate in the browser using the Xposure UI and fetch the contacts endpoint from the browser context.
- When browser tools cannot read local environment variables, a reusable workaround in local-browser sessions is a short-lived localhost credential-injection server that reads `~/.elevate/.env` and serves JavaScript to fill the login form. Kill the server after the run. Never print the served JS or credentials.
- Xposure/InteriorBC MFA email selection is a clickable `div#send-code-email`, not a semantic button. If MFA automation stalls on the verification-method page, click `#send-code-email` or text `Send code via Email` before polling Gmail for the 6-digit code.
- InteriorBC login can show `Login Request Expired` after the board-to-IdP handoff. Click `Continue`, wait for the username/password form to refresh, then refill credentials and click `#loginbtn` again. In the 2026-06-17 run, the programmatic fill succeeded but a second explicit `#loginbtn.click()` was needed to move from `iam.interiorbc.ca/idp/login` to `/portal/air/Contacts`.
- The InteriorBC username/password fields may live inside open shadow roots. Plain `document.querySelector('#username')` / `document.querySelector('input[type=password]')` can fail even though Browser Use state shows the inputs. Use a deep shadow-root traversal (or Browser Use `input` by the current element indexes) and dispatch composed `input`/`change` events before clicking `#loginbtn`.
- `pcs_last_login` dates can use Xposure's compact format like `Apr 2/25`; parse `%b %d/%y` / `%B %d/%y` in addition to ISO and slash-numeric formats. Missing this format misclassifies every buyer as cold. If a run unexpectedly reports `hot=0 warm=0 cold=<all contacts>` while raw contacts have non-empty `pcs_last_login`, stop and inspect the raw date format before trusting the score counts, then rerun extraction/finalization after fixing the parser.
- In cloud/browserbase-style browser sessions, the browser may not be able to fetch `127.0.0.1` from the agent machine, and `/var/folders/.../DevToolsActivePort` may not exist. In that case, do **not** rely on terminal-side localhost injection or terminal CDP discovery; use the provided `Browser Use CLI` tool for browser evaluation and avoid strategies that require moving local secrets into browser JS unless a secure credential bridge is available.
- To move large browser-fetched payloads back to local processing in local-browser sessions, start a short-lived localhost receiver and `fetch('http://127.0.0.1:<port>/contacts.json', {method:'POST', body:text})` from the browser. This avoids trying to return ~MB payloads through `Browser Use CLI`.
- If browser-to-localhost fetch is blocked by the browser sandbox/CORS but local DevTools is available, use Chrome DevTools Protocol (CDP) from the terminal instead of returning large payloads through `Browser Use CLI`:
  1. Find the agent browser DevTools port from the newest `/var/folders/.../T/agent-browser-chrome-*/DevToolsActivePort` file.
  2. Use Python `websockets` (available in the Elevate venv) to connect to the tab websocket from `http://127.0.0.1:<port>/json`; use `python` from the Elevate venv, not `python3`, because `python3` may not have `websockets` installed.
  3. Run `Runtime.evaluate` with `awaitPromise=true` and `returnByValue=true` to execute authenticated in-page `fetch(...)`, then write returned text directly to staging files such as `contacts_raw.json`.
  4. Re-read the DevToolsActivePort path after any browser restart; the temp Chrome profile directory changes between sessions.
- Make the localhost receiver support both POST uploads and GET reads from the staging dir. This lets the browser fetch precomputed `batch_N.json` work packets from `127.0.0.1` and POST `details_N.json` results back without exposing local files directly.
- The browser extraction can time out or close the CDP websocket on the final HOT saved-search batch. Prefer batching HOT buyers at about 20 contacts per `Browser Use CLI` or CDP `Runtime.evaluate` call. If a larger/all-batch call times out or `websockets.exceptions.ConnectionClosedError` appears, it may still have written early `details_*.json` files; verify staged files, delete only stale/missing batch outputs, then rerun the remaining batch index one contact at a time.
- If per-contact reruns all fail with `IndexError` or the browser snapshot is an empty page, the authenticated Xposure session likely dropped or the tab is on a blank `/portal/air/` page. Re-authenticate in the browser, remove any modal/backdrop, confirm the URL is an authenticated page such as `/portal/air/MlsFullSearch...`, then rerun only the missing `details_N.json` batch.
- For saved-search criteria, the `/portal/air/ManageClients` HTML often contains labels such as `Property Type: '...'`, `Property Sub Type: '...'`, `Bedrooms Total: Minimum '2'`, `Current Price: Maximum '$300,000'`, and long community/area lists. Strip scripts/styles/tags and extract label/value pairs from visible text rather than relying on stable form fields. A robust browser-side extractor should POST form fields `currentContactID`, `currentSearchID`, and `currentSubTab=ViewSearch` with `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`, then parse visible text for the desired labels.
- Local operational DB constraints matter only for legacy environments. Current admin/CRM/deal-file source of truth is embedded Postgres via Elevate data helpers, so do not call `sqlite3` or write `~/.elevate/data/operational.db` for cron/admin work. If a legacy script still mentions SQLite, prefer a newer Postgres-aware helper or stage files + CRM sync only until the helper is migrated.
- Existing Xposure contacts may already be in `contacts` with a generated UUID primary key and `source_key='xposure-pcs:<id>'`. Before upserting into `contacts`, query by `source_key` and reuse that `id`; otherwise `INSERT ... ON CONFLICT(id)` can fail with `UNIQUE constraint failed: contacts.source_key`.
- Use `lead_signals` unique key `(source_id, source_native_id)` for PCS deltas, and use `pcs_buyers.contact_id` pointing to the resolved local contact id. Store the Xposure native id in `source_key`, not as the assumed local contact primary key. After an `INSERT ... ON CONFLICT(source_id, source_native_id) DO UPDATE` to `lead_signals`, re-read the actual `lead_signals.id` before writing `pcs_buyers.lead_signal_id`; older rows may keep a non-deterministic UUID and a freshly computed UUID will violate the FK.
- In the current realtor-tools environment, Node `playwright` is installed while Python `playwright` may not be. Prefer Node scripts for Xposure browser automation unless Python deps are explicitly installed.
- Lofty can return HTTP 403 even with `LOFTY_API_KEY` present. In that case, stage the redacted payload, update local operational DB, record the API status in the summary, and report that external CRM tagging/stage sync is pending rather than claiming success.
- Lofty API access can also complete while matching zero delta targets. In the 2026-06-21 run, finalization reported `crm.status="completed"`, `targets=172`, `matched=0`, `updated=0`, `missing=172` after indexing only 25 Lofty records. In that case, say the Lofty sync ran but no Lofty records were changed because no delta targets matched existing Lofty leads; do not phrase it as successful Lofty tagging/stage updates.
- Lofty API access has also worked in this tools environment against both `https://api.lofty.com/v1.0` and `https://api.chime.me/v1.0`; prefer `https://api.lofty.com/v1.0` for current runs.
- If Lofty API access works, `PUT /v1.0/leads/{leadId}` with `tagsAdd` supports additive tags. For HOT PCS buyers, a safe payload is `{'tagsAdd':['xposure-pcs','xposure-pcs-hot'], 'stage':'Active Lead'}` when stage change is needed. Avoid destructive `tags` replacement.
- For scheduled runs, do not try to update all 1k+ Xposure contacts in Lofty when only deltas are required. Build a delta set from the previous `contacts_normalized.json`, then push only new/changed contacts. A full all-leads Lofty index is still useful for matching, but writes should be scoped to deltas.
- As of 2026-06-13, `/Users/admin/realtor-tools/scripts/xposure/finalize-pcs-cron.py` exists and is the preferred cron finalizer. It uses the embedded Postgres Elevate shim via `elevate_cli.data.connect`, stages `<run_id>-crm-delta-payload.json`, pushes additive Lofty `tagsAdd` tags/stages for delta/HOT contacts only, writes `crm_sync_status.json`, generates the watchlist HTML/PDF, updates `<run_id>-summary.json` and `latest-summary.json`, and should be run with `terminal(timeout=600)` because CRM indexing/search plus PDF generation can exceed the 5-minute execute_code cap. Do not use `/Users/admin/realtor-tools/scripts/xposure/finalize-pcs-run.py` for cron/admin work because it still targets the old SQLite operational DB. If Postgres rejects an update with `IndeterminateDatatype`, avoid `CASE WHEN ? IS NOT NULL` with nullable parameters in SQL and branch in Python instead. If `contacts_activity_tier_check` rejects `cold`, map PCS tiers to allowed contact `activity_tier` values: HOT → `active`, WARM → `warm`, cold → `dormant`. As of 2026-06-29, the finalizer falls back from the broad Lofty lead index to targeted `email`/`phone`/`key` lead searches and only mutates a lead when the returned record has an exact email/phone match; this fixed the case where the broad index returned only 25 leads and previously produced `matched=0`. If a run still reports low matches, run targeted-search diagnostics before claiming CRM tags/stages were pushed.
- Lofty responses contain PII. Do not quote sample leads in user-facing output.
- `tagsAdd` is safe for additive CRM tagging; `tags` is destructive.
- In scheduled cron/cloud-browser runs, a fresh Xposure scrape can fail when the portal routes through REALTOR.ca/Auth0 SSO and the browser session cannot access local `.env` credentials or localhost bridges. If this happens, do not claim a fresh scrape. Either stop with a clear partial status, or if downstream processing is still useful, run finalization only from the most recent staged `contacts_raw.json`/`details_*.json` and explicitly report the staging-file timestamps/caveat.
- Before finalizing from staged data, verify `contacts_raw.json` and representative `details_*.json` mtimes. If they are older than the current run, the run is a downstream refresh from existing scrape data, not a true end-to-end scrape.
- If `run_pipeline_finalize.py` writes a summary with `files.pdf=null` because `reportlab` is missing, immediately run `generate_watchlist_pdf.py`, verify with `file <pdf>` that it is a valid PDF, and confirm `latest-summary.json` contains both `files.pdf` and `files.html` before reporting completion.

## Verified cron command sequence

As of the 2026-06-18 scheduled run, `/Users/admin/realtor-tools/scripts/xposure/run-pcs-extract-cdp.py` and `/Users/admin/realtor-tools/scripts/xposure/finalize-pcs-cron.py` are present and worked end-to-end against a Browser Use Chrome remote-debugging session. The Elevate app venv Python was at `$(command -v python)` (`/Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python` in that run), not the older `/Users/admin/.elevate/elevate/cli/.venv/bin/python`. The CDP port may also drift; `run-pcs-extract-cdp.py` now accepts `CDP_PORT` and defaults to `9222`.

```bash
cd /Users/admin/realtor-tools
# If no healthy browser-use session exists, start one first:
# /Users/admin/.local/bin/browser-use --json --session pcs open https://interiorrealtors.xposureapp.com/
# Then read the port from `browser-use --json sessions` (cdp_url ws://127.0.0.1:<port>/...).
CDP_PORT="<browser-use-cdp-port>"
RUN_ID="pcs-$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/Users/admin/realtor-tools/data/xposure-pcs/$RUN_ID"
mkdir -p "$OUT"
PY="$(command -v python)"
CDP_PORT="$CDP_PORT" "$PY" scripts/xposure/run-pcs-extract-cdp.py "$OUT"
PYTHONPATH="/Applications/Elevate.app/Contents/Resources/cli${PYTHONPATH:+:$PYTHONPATH}" "$PY" scripts/xposure/finalize-pcs-cron.py "$OUT"
file "$OUT/${RUN_ID}-hot-watchlist.pdf"
```

If `run-pcs-extract-cdp.py` hangs or times out before writing files, do not rerun blind loops. First inspect the Browser Use session/port with sanitized CDP booleans only: current URL, title, `hasUsername`, `hasPassword`, `hasLoginBtn`, `hasSendEmail`, `hasCodeInput`, `hasExpired`, `hasMfa`, `hasSignIn`, and `isXposure`. Avoid dumping DOM/input lists after credentials are filled because IAM pages can expose typed values, CSRF tokens, hidden signals, and other sensitive text in logs.

Recovery patterns seen in production:
- If the browser is on `http://www.interfacexpress.com/portal/Login`, the prior auth did not stick. Navigate to `https://interiorrealtors.xposureapp.com/portal/Login`, explicitly select the `Interior BC` / `AIR` option in `select[name=creaHomeBoard]`, then click Sign In.
- If the browser is sitting on `https://iam.interiorbc.ca/idp/login`, use the existing Browser Use session/port and fill the IAM username/password through CDP with env values. Print only booleans such as `hasCreds`, `filledUser`, `filledPassword`, and `clicked`.
- If the extractor hangs for 10 minutes with an empty run directory and the sanitized state still shows the IAM login page, stop the timed-out run and inspect for the hidden/session-timeout state using booleans only. If `Login Request Expired` is present, click the `Continue` button, wait for the fresh login form, then fill `#username` and `#password` directly and click `#loginbtn`. In the 2026-06-22 run, this direct selector fill returned a null CDP value but succeeded and landed on `/portal/air/MlsFullSearch?...`; rerunning the extractor/finalizer after that completed end-to-end.
- The IAM `Password Login` click can appear to do nothing at first. After filling, wait briefly and click `#loginbtn` again if the sanitized state still shows the login page. In the 2026-06-21 run, the second click landed at `/portal/air/MlsFullSearch?...`.
- In the 2026-06-23 run, setting `input.value` programmatically and clicking `#loginbtn` landed on `https://iam.interiorbc.ca/idp/logout`, but focusing each field, clearing it, using CDP `Input.insertText` for username/password, then clicking `#loginbtn` succeeded and landed on `/portal/air/MlsFullSearch?...`. If direct JS value assignment unexpectedly logs out, restart/navigate to `/portal/Login`, select Interior BC, and retry with `Input.insertText` rather than printing or shell-expanding credentials.
- In the 2026-07-03 cron run, the first foreground `run-pcs-extract-cdp.py` attempt timed out at 600s because the Browser Use tab was still on `https://iam.interiorbc.ca/idp/login` and the output directory was empty. The reliable recovery was to inspect sanitized CDP booleans only, navigate the existing `pcs` session back to `https://interiorrealtors.xposureapp.com/portal/Login`, select Interior BC, click Sign In, then use CDP mouse clicks plus `Input.insertText` for username/password and click the visible login button by coordinates. A direct JS value-fill attempt again sent the tab to `idp/logout`, so prefer the coordinate/`Input.insertText` path whenever the login page is already loaded but the extractor is stuck. After the URL reaches `/portal/air/MlsFullSearch?...`, start a fresh `OUT` directory and rerun extractor + finalizer rather than reusing the timed-out empty directory.
- In the 2026-06-26 cron run, reusing an existing unrelated Browser Use session (`mir`) and then a fresh `pcs` session both timed out at IAM login until the page was manually reset. The reliable recovery was: open `https://interiorrealtors.xposureapp.com/portal/Login` in the Browser Use session, select `Interior BC`, click Sign In, wait for `https://iam.interiorbc.ca/idp/login`, then use CDP mouse events to click the visible username/password boxes, clear them, use `Input.insertText` for `MLS_USERNAME` and `MLS_PASSWORD`, and click the visible `#loginbtn` by coordinates. Pressing Enter from the password field produced `Login Request Expired`; clicking the visible login button succeeded and landed on `/portal/air/MlsFullSearch?...`. After that, rerunning `run-pcs-extract-cdp.py` against the same `CDP_PORT` completed normally.
- A successful post-login Xposure page may still contain hidden username/code fields, generic error text, or MFA-related words in hidden page text. Do not use booleans like `hasMfa=true` alone as failure. Treat an authenticated `/portal/air/...` URL such as `/portal/air/MlsFullSearch?...` or `/portal/air/Contacts` as good enough to rerun or resume extraction.
- If the extractor is already running in the background and appears hung with an empty output directory while the browser target is on `https://iam.interiorbc.ca/idp/login`, you can recover the same run by authenticating that existing CDP tab manually. Use sanitized state checks, fill `#username` and `#password` with CDP `Input.insertText`, click `#loginbtn`, wait until the URL reaches `/portal/air/...`, then wait on the original process. In the 2026-06-25, 2026-06-28, and 2026-06-30 runs, the original extractor resumed after manual login and completed successfully, so killing/restarting was not necessary.
- When filling the InteriorBC IAM login through CDP, `Runtime.callFunctionOn` with a hard-coded `executionContextId` can silently return `null` or fail to find fields, especially with open shadow-root inputs. Prefer a sanitized `Runtime.evaluate` IIFE that deep-traverses shadow roots, focuses/clears each field, then uses `Input.insertText` for username/password and coordinate-clicks the visible `#loginbtn`. Print only booleans like `user_found`, `pass_found`, and `button_found`; never print input values or DOM text after credentials are present.
- The `#loginbtn` can remain disabled immediately after programmatic fill even when `#username` and `#password` have nonzero lengths. Dispatch composed `keydown`/`keypress`/`input`/`keyup`/`change` events on both fields, wait about 1 second, then re-check `button.disabled` before clicking. If you click while disabled, the page may stay on `iam.interiorbc.ca/idp/login` and show only a generic invalid/error state while clearing both fields; refill and wait for the button to enable instead of assuming the credentials failed. In the 2026-07-02 run, after a sanitized CDP fill left the page on `iam.interiorbc.ca/idp/login` with the fields populated and no invalid/MFA/expired state, a second explicit `#loginbtn.click()` reported `disabled:true` but still landed on `/portal/air/Contacts`; treat a post-click authenticated `/portal/air/...` URL as success and let the already-running extractor resume.
- `browser-use --json --session pcs state` may return an empty URL/elements payload even while the CDP target is correctly on the IAM page. In that case, use sanitized CDP inspection via `http://127.0.0.1:<port>/json` and `Runtime.evaluate` for URL/title/boolean state rather than relying on Browser Use state output.
- When parsing `browser-use --json sessions` in shell, do not pipe directly into `python - <<'PY' ...` because the heredoc consumes stdin and the JSON pipe will be lost. Capture stdout to a temp file first, then pass that file path to Python for sanitized parsing.
- In the 2026-06-27 cron run, `browser-use --json --session pcs open ...` timed out in a foreground terminal call but succeeded when started as a tracked background process and waited on with `process.wait`. After opening, `browser-use --json sessions` showed the CDP port but not the current URL, which was still enough to run the extractor. If the background extractor shows no logs, do not assume it is dead: Python output may be fully buffered until exit. Check `ps` for the child `run-pcs-extract-cdp.py` process and inspect the browser state through sanitized CDP booleans. In that run, the extractor was sitting at `https://iam.interiorbc.ca/idp/login`; filling credentials via CDP `Input.insertText` and clicking the visible login button let the already-running extractor resume and complete end-to-end without restart.

Once the browser is authenticated, rerun the extractor/finalizer against a fresh `OUT` directory using the same `CDP_PORT` if no extractor is still running. If a previous timed-out run created an empty `OUT`, ignore it and use the later successful run directory.

The older Node sequence can still be used where Playwright browser launch is healthy:

```bash
RUN_ID="pcs-$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/Users/admin/realtor-tools/data/xposure-pcs/$RUN_ID"
mkdir -p "$OUT"
node scripts/xposure/run-pcs-extract.js "$OUT"
PY="/Users/admin/.elevate/elevate/cli/.venv/bin/python"
PYTHONPATH="/Users/admin/.elevate/elevate/cli${PYTHONPATH:+:$PYTHONPATH}" "$PY" scripts/xposure/finalize-pcs-cron.py "$OUT"
file "$OUT/${RUN_ID}-hot-watchlist.pdf"
```

If the extractor succeeds but the finalizer fails with `ModuleNotFoundError: No module named 'elevate_cli'`, do **not** rerun the Xposure scrape. Re-run only the finalizer against the same `OUT` directory with the Elevate CLI source on `PYTHONPATH` as shown above. If system `/usr/bin/python3` fails on Python 3.10+ syntax such as `Path | None`, use the Elevate venv Python at `/Users/admin/.elevate/elevate/cli/.venv/bin/python`.

Expected successful extract output shape includes nonzero `contacts`, `hot`, `warm`, `cold`, and `details_fail:0`. The finalizer should update `latest-summary.json`, write `<run_id>-summary.json`, generate both `<run_id>-hot-watchlist.html` and `<run_id>-hot-watchlist.pdf`, and complete Lofty sync with `crm.status="completed"` when API access works. Verify the PDF with `file`; a successful run may produce one cover plus one page per HOT buyer.

## Verification checklist

- Xposure login succeeded and browser is on `/portal/air/...`.
- Contacts endpoint returns JSON and nonzero records.
- Buyer score counts add up to total PCS buyers.
- In `contacts_normalized.json`, records are currently under top-level `contacts`, and the activity tier field is `_tier` with values `HOT`, `WARM`, and `cold`; do not assume a field named `score` or `tier` exists during verification.
- HOT saved-search detail fetches have success/failure counts. `hot_search_details.json` may be a list of detail records, and extracted criteria can appear under keys such as `criteria`, `parsedCriteria`, `parsed`, `fields`, or `summary`.
- Local staged JSON exists and parses.
- DB writes have an `ingest_runs` row and expected row counts when the Postgres-aware helper is available.
- Lofty API calls return HTTP 200/2xx; no secrets or sample lead PII printed.
- Watchlist PDF/report file exists and has one cover plus per-lead cards. For the current report format, expected page count is `HOT + 1`.
