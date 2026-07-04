---
name: estratahub-documents
description: "Check and retrieve BC strata-document orders from eStrataHub/LTSA, Gmail first. Use when the realtor asks if ordered strata documents have arrived, asks to check LTSA/eStrataHub, wants strata documents pulled for a BC listing or accepted offer, or asks whether the docs answer a buyer's emailed questions on litigation, parking, pets, or rentals."
version: 1.0.0
author: Elevate
metadata:
  elevate:
    tags: [real-estate, strata, LTSA, eStrataHub, Gmail, documents]
---

# eStrataHub Documents

Use when the realtor asks whether ordered strata documents have arrived, asks to check LTSA/eStrataHub, or asks to retrieve strata documents for a BC strata listing or accepted offer.

## Fast Gmail check first

Use Google Workspace/Gmail before opening LTSA.

Search targeted terms:

```bash
gws gmail users messages list --params '{"userId":"me","q":"\"450 Main\" strata newer_than:30d","maxResults":10}' --format json
gws gmail users messages list --params '{"userId":"me","q":"\"Main Street\" strata newer_than:30d","maxResults":10}' --format json
gws gmail users messages list --params '{"userId":"me","q":"\"eStrataHub\" newer_than:30d","maxResults":10}' --format json
gws gmail users messages list --params '{"userId":"me","q":"from:ltsa.ca newer_than:14d","maxResults":10}' --format json
```

Then fetch candidate messages with `format=full` and inspect subject, snippet/body, and attachments. eStrataHub order notifications often have no attachments and only say the order was placed/accepted or that there is a message in eStrataHub.

Useful signals in eStrataHub emails:
- `Order Placed - # <order>, <strata plan>, <strata lot>, Due: <date>` means submitted but not necessarily accepted.
- `Order Accepted # <order>` means the management company accepted the order and gives due date.
- `Message for # <order>` means log into LTSA → eStrataHub → order → Messages tab.
- `Due Date` is the expected delivery date, not proof that documents are ready.

Report clearly whether the actual documents were found versus only order/status notifications.

## Example known pattern

For a unit-civic strata address such as `4-450 Main Street / <building name>`:
- Order #: assigned by eStrataHub at order time
- Property manager: the strata's managing company
- Property name: the strata corporation/building name
- Strata plan #: from the strata plan
- Strata lot #: from the strata plan
- Due date: the delivery deadline eStrataHub gives
- Gmail may only show order placed/accepted/message notices, not the delivered strata docs, until the manager actually uploads them.

## LTSA login path

The stable login URL discovered in browser work is:

```text
https://apps.ltsa.ca/iam/login
```

The root `https://myltsa.ltsa.ca` can redirect to the public LTSA site, and guessed paths like `/myltsa` or `/iam-ui/login` may 404.

Credentials are stored in the realtor's protected credentials env file:

```bash
source <realtor-credentials-env-file>
# MYLTSA_USER / MYLTSA_PASSWORD
```

Do not print secrets. To enter credentials in browser, copy each value to clipboard from the terminal and paste into the browser:

```bash
set -a; source <realtor-credentials-env-file>; set +a; printf %s "$MYLTSA_USER" | pbcopy
set -a; source <realtor-credentials-env-file>; set +a; printf %s "$MYLTSA_PASSWORD" | pbcopy
```

If the Sign In button does not respond, prefer clicking the real submit button via browser console rather than calling native form submit:

```js
document.querySelector('#kc-form-login button[type=submit],#kc-login')?.click();
```

Only use `checkLogin(); document.querySelector('#kc-form-login').submit();` as a fallback on the username/password screen.

## MFA / verification caveat

LTSA may require MFA setup or verification during login. The MFA screen can offer Email/Text/Authenticator. The masked MFA email address shown on screen may differ from the address whose inbox is actually accessible (for example, a brokerage-domain address masked on screen versus a personal address the agent can search). If a new MFA code does not arrive in accessible Gmail, ask the realtor for the code from the masked email rather than guessing.

When selecting Email MFA, click the actual radio and continue button. If normal clicks are flaky:

```js
document.querySelector('#mfaEmail').click();
document.querySelector('#kc-mfa-config-form button[type=submit],button.btn-primary')?.click();
```

When MFA sends a code to Gmail, fetch it with:

```bash
gws gmail users messages list --params '{"userId":"me","q":"from:ltsa.ca \"verification code\" newer_than:10m","maxResults":5}' --format json
```

Then read matching messages and extract the 6-digit code from the snippet/body. If `newer_than` returns stale messages because Gmail search is not enough, inspect Date headers and prefer the newest header timestamp, or use an explicit date query like `after:YYYY/M/D`.

For the verification-code entry page, do **not** use `HTMLFormElement.prototype.submit.call(form)` or raw `form.submit()`. That bypassed LTSA's expected submit button and produced an Internal Server Error in one run. Type the code, then click the visible Continue button or run:

```js
document.querySelector('#submit').click();
```

If LTSA says the code is invalid, stop after one failed attempt and ask the realtor for the newest code. Do not keep retrying old codes and consume the remaining MFA attempts.

## eStrataHub portal steps

After login:
1. Open the eStrataHub tab/product from the LTSA account dashboard.
2. Use the My Orders page.
3. Search/filter by order number, address, strata plan, or strata lot.
4. Open the Details button for the order.
5. Check Documents/Downloads and Messages tabs.
6. Download available PDFs/zips to a property-specific local folder and verify file count, names, and nonzero sizes before reporting success.

## Reviewing buyer questions against strata docs

Use this pattern when the realtor asks whether strata documents answer a buyer's emailed questions.

1. Find the buyer's questions in Gmail first. Search by email handle/name + property + strata terms, for example:
   ```python
   import json, subprocess
   GWS = "/usr/local/bin/gws"
   handle = "<buyer-email-handle>"
   address = "<property-address>"
   for q in [
       f"from:{handle} OR to:{handle}",
       f"{handle} {address}",
       f"{handle} strata",
   ]:
       subprocess.run([GWS, "gmail", "users", "messages", "list",
           "--params", json.dumps({"userId":"me","q":q,"maxResults":10}),
           "--format", "json"], check=True)
   ```
   Fetch candidate messages with `format=full`, decode text/html parts, and extract the exact bullet questions before reviewing docs.
2. Locate the listing/property Drive folder and any `Strata Docs` subfolder. Also check relist folders and older building folders. A main listing folder can have the Form B package while older folders contain historical minutes/financials, so do not assume one folder is complete.
3. Download PDFs locally for text review. `gws drive files get --output` may reject absolute paths as outside the current directory; set `cwd` to the destination folder and pass a relative filename:
   ```python
   params = {"fileId": file_id, "alt": "media", "supportsAllDrives": True}
   subprocess.run([GWS, "drive", "files", "get", "--params", json.dumps(params), "--output", "Form_B.pdf"], cwd=outdir, check=True)
   ```
4. Extract PDF text. On some macOS gateways, `pdftotext` may not be on the Python sandbox PATH even though it is installed; check `/opt/homebrew/bin/pdftotext` as a fallback location. If a PDF extracts to only form-feed characters, it is scanned/image-only and needs OCR or a different source.
5. Search extracted text by topic, not only exact phrasing. For strata questions, useful terms include: `window`, `sliding glass`, `balcony`, `deck`, `concrete`, `building envelope`, `engineer`, `consultant`, `special levy`, `assessment`, `water intrusion`, `condensation`, `seal`, `laundry`, `washer`, `dryer`, `occupancy`, `occupants`, `plumbing`, `electrical`, `repair`, `replacement`.
   - For standard Form B / strata-package questions also search: `court proceedings`, `tribunal`, `CRT`, `KEL-S-S`, `civil`, `Supreme Court`, `settled`, `resolved`, `discontinued`, `parking stall`, `storage locker`, `pet`, `dog`, `cat`, `rental`, `short-term`, `Airbnb`, `VRBO`, `Form K`.
   - eStrataHub order-container PDFs usually start with an index of embedded files. Use that index to identify the relevant sections, but still extract/search the full PDF because the embedded Form B, bylaws, rules, minutes, and court/CRT pages can all be concatenated into the one container.
   - If Drive has both a newer full order container and an older Form B/bylaws/rules set, review both. Do not assume the newer package contains the older Form B/bylaws unless the index confirms it.
6. For Form B-style questions, check the most authoritative source first:
   - **Litigation / court proceedings:** Common and Residential Form B item `(j)` can differ. Report each section separately. Then cross-check attached CRT/Supreme Court pages and the newest available council minutes for current status. If the Form B says a proceeding exists and the newest minutes say parties are “working to settle,” “await further instruction,” or “no further updates,” treat it as **not confirmed resolved** unless there is a dismissal, discontinuance, release, or explicit settled/resolved wording.
   - **Parking stalls:** Form B item `(m)` normally gives stall numbers and whether they are LCP/common property/strata lot. Include any note such as “refer to owner/developer agreement” or section 76 changeability.
   - **Storage locker:** Form B item `(n)` normally gives locker number and whether common property/LCP/strata lot. Include any note such as owner-developer assignment or short-term exclusive-use changeability.
   - **Pets:** Bylaws/rules are usually decisive. Summarize allowed pet count/type and practical restrictions such as leash/cleanup/removal/facility bans.
   - **Rental restrictions:** Bylaws section `Rentals` is usually decisive. Capture minimum term, short-term accommodation/Airbnb/VRBO bans, Form K requirements, business licence/city compliance, fines, and exemptions.
7. If pages extract poorly or key pages are image-only, map PDF page numbers with per-page `pdftotext` headers, then render the specific pages and use vision/OCR instead of guessing:
   ```bash
   pdfinfo order_795869.pdf | grep Pages
   pdftotext -f 13 -l 13 -layout order_795869.pdf -
   pdftoppm -f 13 -l 14 -png -r 180 order_795869.pdf order795869_page
   ```
   Use the rendered page images to read CRT/court filings, scanned minutes, or pages whose text extraction is blank or only form-feed characters.
8. Separate answers into:
   - **Answered by docs**: cite which doc and the concrete fact (e.g. Form B says approved future special levy is NIL; bylaws cap a 2-bed at four occupants).
   - **Partially answered**: depreciation report/funding model flags future work or potential levies, but Form B shows nothing currently approved.
   - **Not answered / needs strata manager or minutes**: unit-specific history, whether council discussed timelines, whether a specific alteration will be approved, and whether non-depreciation engineering/building-envelope reports exist.
9. Important distinction: depreciation report projections are not the same as approved levies. Report projected per-unit funding/levy numbers as future planning/model data only, and cross-check Form B for currently approved amounts.
10. Current minutes and current financial statements are often the decisive evidence for “has council discussed…” questions. If those are missing, say that clearly and do not over-answer from the depreciation report.

## Reporting

Be specific:
- If no documents are in Gmail: say no delivered docs found in email.
- If order notices exist: report order number, accepted status, property manager, strata plan/lot, and due date.
- If LTSA is blocked by MFA: say exactly which masked delivery method is blocking access and ask for the code.
- Do not claim documents are ready unless attachments/downloads were actually found and verified.
- For buyer-question reviews, provide a concise issue-by-issue matrix of what is answered, partially answered, and not answered, with the document source and any required follow-up.
