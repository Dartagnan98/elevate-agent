---
name: gmail-attachment-to-drive-proof
description: Find a specific Gmail attachment and save it to the right Google Drive folder with proof. Use for admin requests like "find the BIR in Gmail and save it to Drive with proof": verifies the attachment against property/deal facts and produces proof with Gmail/Drive IDs and checksums.
version: 1.0.0
metadata:
  elevate:
    tags: [gmail, drive, real-estate-admin, proof, attachments, google-workspace]
    related_skills: [google-workspace, deal-matcher, admin-result-writer]
---

# Gmail attachment to Drive with proof

Use this when the user asks to locate a document in Gmail, save it into the correct Drive folder, and provide proof. Typical examples: BIR responses, receipts, signed forms, title/search documents, tax notices, or realtor-sent attachments.

## Rules

- Use local CLI/API tools only. Do not open Google in a browser unless explicitly needed and approved.
- This workflow normally uses `gws` via terminal and does not need browser navigation.
- Match the deal/folder using strong identifiers before uploading: deal ID, exact civic address, MLS number, named client, Gmail subject/ref number, document text.
- Never attach or upload to a fuzzy match. If multiple plausible folders exist, prefer the folder under the known operational parent such as the realtor's listing files folder, and verify parent path. If still ambiguous, stop and ask.
- Produce proof that can be independently checked: Gmail message ID/thread ID, sender, subject, attachment filename, Drive file ID, folder ID/path, file size, and checksum.

## Workflow

1. **Load prerequisites**
   - Load `google-workspace` for `gws` usage.
   - Load `deal-matcher` if the correct deal/folder is not already proven.
   - Load `admin-result-writer` if the result should be written back to an Admin deal.

2. **Check Google CLI availability/auth**

   ```bash
   command -v gws
   python ${ELEVATE_HOME:-$HOME/.elevate}/skills/productivity/google-workspace/scripts/setup.py --check || true
   ```

   If setup reports `NOT_AUTHENTICATED` but `gws` direct reads work, continue. `gws` may be authenticated through its own keyring.

3. **Search Gmail with several targeted queries**

   Use `gws gmail users messages list` with `userId: me`. Start narrow, then broaden. Example for a BIR (Building Information Request):

   ```bash
   gws gmail users messages list \
     --params '{"userId":"me","q":"\"B11 450 Main Street\" has:attachment","maxResults":10}' \
     --format json
   ```

   Useful query variants:
   - Exact address: `"B11 450 Main Street"`
   - Normalized address: `"B11" "450" "Main" has:attachment`
   - Reference number: `"BIR58798"`
   - Sender + terms: `from:birbuilding@<municipality>.ca ("450" OR "Main" OR "BIR58798")`
   - Document type: `(BIR OR "Building Information Request") address/ref has:attachment`

4. **Inspect candidate messages and attachments**

   Fetch candidates in `full` or `metadata` format and list headers plus attachment parts. Avoid unsafe shell pipelines that pipe untrusted data directly into interpreters. Prefer writing small Python scripts or output JSON to a temp file first.

   ```python
   import subprocess, json

   msg = json.loads(subprocess.run([
       'gws','gmail','users','messages','get',
       '--params', json.dumps({'userId':'me','id':MESSAGE_ID,'format':'full'}),
       '--format','json'
   ], text=True, capture_output=True, check=True).stdout)

   headers = {h['name'].lower(): h['value'] for h in msg.get('payload',{}).get('headers',[])}
   attachments = []
   def walk(part):
       if not part: return
       body = part.get('body') or {}
       if part.get('filename') or body.get('attachmentId'):
           attachments.append({
               'filename': part.get('filename'),
               'mimeType': part.get('mimeType'),
               'size': body.get('size'),
               'attachmentId': body.get('attachmentId'),
               'partId': part.get('partId'),
           })
       for child in part.get('parts') or []:
           walk(child)
   walk(msg.get('payload'))
   print(headers, attachments)
   ```

5. **Resolve the correct Drive folder**

   Search Drive folders by address and client names:

   ```bash
   gws drive files list \
     --params '{"q":"mimeType=\"application/vnd.google-apps.folder\" and trashed=false and name contains \"450\"","pageSize":20,"fields":"files(id,name,mimeType,parents,createdTime,modifiedTime),nextPageToken","supportsAllDrives":true,"includeItemsFromAllDrives":true}' \
     --format json
   ```

   Verify parent chain with `drive.files.get` until root. For the realtor's listing files, the preferred path is usually:

   `My Drive / 1 - Shared Team Folder / 1 - Client Files / 1 - Listing Files / <realtor's listing folder> / <property folder>`

   A similarly named orphan folder may exist. Do not use it unless the operational folder path proves it is correct.

6. **Check for existing duplicate in the destination folder**

   Before uploading, list exact or near-exact names in the chosen parent:

   ```bash
   gws drive files list \
     --params '{"q":"trashed=false and '\''FOLDER_ID'\'' in parents and (name contains '\''BIR'\'' or name contains '\''Building Information'\'')","pageSize":20,"fields":"files(id,name,mimeType,parents,createdTime,modifiedTime,size,md5Checksum),nextPageToken","supportsAllDrives":true,"includeItemsFromAllDrives":true}' \
     --format json
   ```

   If an exact file already exists, verify checksum/content and report it instead of duplicating. If only a receipt or related document exists, proceed with the requested final document.

7. **Download the Gmail attachment locally**

   Use `gmail.users.messages.attachments.get`, base64url-decode the `data`, and save with a normalized descriptive filename.

   ```python
   import subprocess, json, base64, hashlib, os

   att = json.loads(subprocess.run([
       'gws','gmail','users','messages','attachments','get',
       '--params', json.dumps({'userId':'me','messageId':MESSAGE_ID,'id':ATTACHMENT_ID}),
       '--format','json'
   ], text=True, capture_output=True, check=True).stdout)

   data = base64.urlsafe_b64decode(att['data'] + '='*((4-len(att['data'])%4)%4))
   out = '/tmp/descriptive-name.pdf'
   open(out,'wb').write(data)
   print(hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest(), len(data))
   ```

8. **Verify document content**

   For PDFs, use `pdftotext` if available, then inspect the extracted text for deal/ref identifiers.

   ```bash
   pdftotext /tmp/descriptive-name.pdf /tmp/descriptive-name.txt
   ```

   Required proof points vary by document. For a municipal BIR (Building Information Request), verify:
   - `BUILDING INFORMATION REQUEST RESPONSE`
   - applicant name
   - property civic/legal address
   - `Ref. No.`
   - document date
   - key response result

9. **Upload to Drive**

   ```bash
   gws drive +upload /tmp/descriptive-name.pdf \
     --parent FOLDER_ID \
     --name 'Descriptive-Name.pdf' \
     --format json > /tmp/upload_result.json
   ```

   The upload helper may return only minimal fields. Always verify the file afterward:

   ```bash
   gws drive files get \
     --params '{"fileId":"FILE_ID","fields":"id,name,mimeType,parents,createdTime,modifiedTime,size,md5Checksum,webViewLink,trashed","supportsAllDrives":true}' \
     --format json
   ```

   Then list by exact name plus parent to prove placement:

   ```bash
   gws drive files list \
     --params '{"q":"trashed=false and name=\"Descriptive-Name.pdf\" and '\''FOLDER_ID'\'' in parents","pageSize":10,"fields":"files(id,name,mimeType,parents,createdTime,modifiedTime,size,md5Checksum,webViewLink),nextPageToken","supportsAllDrives":true,"includeItemsFromAllDrives":true}' \
     --format json
   ```

   Compare Drive `md5Checksum` and `size` to the local file.

10. **Write proof artifacts**

   Create a concise markdown proof report and a machine-readable JSON report. Include:
   - task name and timestamp
   - deal/folder match decision
   - Gmail message ID/thread ID/from/to/date/subject/attachment name/size
   - local path, local size, MD5, SHA256
   - document text proof points
   - Drive folder ID/path, uploaded file ID/name/size/MD5/webViewLink
   - whether MD5/size matched

11. **Write back to Admin deal if applicable**

   Attach the actual PDF and proof report to the matched deal:

   ```python
   admin_deal(action='attach', deal_id=DEAL_ID, file_path=PDF_PATH, kind='signed_document', summary='...')
   admin_deal(action='attach', deal_id=DEAL_ID, file_path=PROOF_MD_PATH, kind='compliance_status', summary='...')
   ```

   Use a neutral `kind` if the document is not signed, such as `compliance_status`, `offer_pdf`, or `form_draft`, depending on what the dashboard expects.

## Pitfalls learned

- Gmail search can return many unrelated messages when using broad address terms. Use message headers, sender, subject, and attachment filename to isolate the correct final document.
- Related BIR emails may include receipts, refund/cancellation emails, or attached `.eml` messages. The final BIR response is usually from `BIR Building` and has the actual PDF attachment.
- `gws drive +upload` may not return parent/size/checksum in its immediate response. Always call `drive.files.get` after upload.
- Drive can contain duplicate property folders, including orphan folders. Verify the parent path, not just folder name.
- Security guardrails may block shell pipelines that pipe external command output directly into Python/Perl. Write output to a temp file or use a saved Python script instead.
- When scripting `gws ... --params`, always shell-quote the complete JSON params string (for example with `shlex.quote(json.dumps(params))`). Unquoted Gmail query strings containing spaces, quotes, or parentheses can produce misleading `Invalid --params JSON` errors.
- For large Gmail message/attachment payloads, prefer Python `subprocess.run(..., capture_output=True)` and parse the raw JSON stdout directly. Terminal-wrapper output can truncate or wrap JSON and break attachment extraction.
- Gmail attachment data may be base64url encoded and may omit padding. Normalize `-`/`_` if needed and add missing `=` padding before decoding, or use the provider/CLI attachment endpoint exactly as returned. A decode error such as “number of data characters ... cannot be 1 more than a multiple of 4” means the parsed payload is likely not the clean attachment data.
- Verify the downloaded file content, not just the filename. For PDFs, run `file`, `pdfinfo`, and `pdftotext` and compare extracted text against the requested artifact type. A property/assessment subject sheet is not proof of sold-comps/sold-properties even if the filename contains the property address and Xposure.
- If the requested document is not found but a related attachment is recovered, save it with a precise filename and audit note, but do not attach or label it as the requested artifact.
- Do not mark checklist/stage items complete just because a document was saved. Only attach evidence unless the workflow explicitly completed a checklist item.

## Final response template

Keep the user-facing result concise:

- `Completed.`
- Gmail source: message ID, sender, subject, attachment.
- Document verified: address/ref/date/key result.
- Drive destination: folder name/path, file name, Drive file ID, checksum/size match.
- Deal writeback: attached PDF/proof report if done.
- Issues: any ambiguity or blockers.
