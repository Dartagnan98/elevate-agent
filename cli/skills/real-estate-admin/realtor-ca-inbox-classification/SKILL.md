---
name: realtor-ca-inbox-classification
description: "Find and classify REALTOR.ca lead emails for a listing, read-only, no state changes. Use when asked whether a REALTOR.ca email was a showing request vs general inquiry, or to pull the date/sender/snippet for a REALTOR.ca lead."
version: 1.0.0
author: Elevate
license: MIT
metadata:
  elevate:
    tags: [real-estate, gmail, realtor.ca, leads, inbox, classification]
---

# REALTOR.ca inbox classification

Use this for read-only Gmail checks of REALTOR.ca lead emails tied to a listing address or MLS number.

## Guardrails

- Read-only only: do **not** reply, send, archive, label, mark read/unread, move, delete, or update lead/deal state unless the user separately asks.
- Return only the requested fields when the user asks for a compact finding.
- Prefer exact listing identifiers first: street address, unit number, MLS number, and `from:Lead@realtor.ca`.
- REALTOR.ca lead emails can have a subject that says `General inquiry` even when the free-text message asks to arrange a showing. Classification should use both the subject and the message body.

## Gmail access pattern

1. Load `productivity/google-workspace` if Gmail access/setup details are needed.
2. Check for `gws` and authentication state:
   ```bash
   command -v gws || true
   python ${ELEVATE_HOME:-$HOME/.elevate}/skills/productivity/google-workspace/scripts/setup.py --check || true
   ```
   If setup prints `NOT_AUTHENTICATED`, still try a harmless direct `gws` Gmail read because the account may be authenticated through the keyring backend.
3. Search read-only with tight Gmail queries. Examples:
   ```bash
   gws gmail users messages list --params '{"userId":"me","q":"in:inbox from:Lead@realtor.ca \"450 Main\"","maxResults":10}' --format json
   gws gmail users messages list --params '{"userId":"me","q":"in:anywhere from:Lead@realtor.ca \"450 Main\"","maxResults":10}' --format json
   gws gmail users messages list --params '{"userId":"me","q":"in:inbox from:Lead@realtor.ca \"MLS_NUMBER\"","maxResults":10}' --format json
   ```
4. Retrieve each candidate's metadata first:
   ```bash
   gws gmail users messages get --params '{"userId":"me","id":"MESSAGE_ID","format":"metadata","metadataHeaders":["Date","From","Subject","To"]}' --format json
   ```
5. Retrieve full body for likely matches or ambiguous cases:
   ```bash
   gws gmail users messages get --params '{"userId":"me","id":"MESSAGE_ID","format":"full"}' --format json
   ```
   Decode `payload.body.data` / nested text parts with URL-safe base64. Strip HTML and collapse whitespace for snippets.

## Classification rules

Classify as **Showing request** when any of these are present:

- Subject starts with or includes `Showing request for ...`.
- Body says `[Name] would like to book a showing at ...`.
- Body contains `Book a Showing:` or `Preferred Date/Times for showing:`.
- Body free text asks to `schedule a visit`, `arrange a showing`, or proposes a showing date/time, even if the subject says `General inquiry`.

Classify as **General inquiry** when:

- Subject includes `General inquiry for ...`, and
- Body asks for information only, business/lease details, tenant/use questions, buyer/investor questions, etc., without requesting a showing/visit date.

If the subject and body conflict, report the nuance briefly, e.g. `Classification: Showing request, body asks to arrange a showing even though REALTOR.ca subject says General inquiry`.

## Browser Use Gmail extraction notes

When the task is to pull contact details from a REALTOR.ca lead email, use the account's configured browser-automation path for Gmail access. A reliable pattern is:

```bash
browser-use --session <session> --profile <realtor-profile-name> open 'https://mail.google.com/mail/u/0/#search/from%3ALead%40realtor.ca%20%22STREET%20ADDRESS%22%20newer_than%3A30d'
sleep 8
browser-use --session <session> state
browser-use --session <session> click <message-row-ref>
sleep 5
browser-use --session <session> eval "(()=>Array.from(document.querySelectorAll('a')).map((a,i)=>({i,text:(a.innerText||a.textContent||'').trim(),href:a.href,title:a.title,aria:a.getAttribute('aria-label')})).filter(x=>/Contact via Email|tel:|mailto:|778|realtor/i.test(JSON.stringify(x))).slice(0,50))()"
```

Useful findings from REALTOR.ca lead emails:
- `Contact via Email` is often a `mailto:` link containing the actual lead email, even when the visible email is hidden.
- Phone numbers are often exposed as `tel:` links and visible anchor text.
- The visible body includes preferred channel, viewing preference, MLS number, and lead activity count.
- Opening a Gmail message can mark it read. If the task is read-only and the message was unread, restore it to unread before finishing using Gmail's `Mark as unread` button. Mention this in the final if it happened.

Before recommending or recording any lead status, check Elevate contacts/identities for the extracted email and phone. If no contact exists and the user asked only to find details/draft without sending or updating CRM, do not create a new contact or fabricate a lead status update. Report `No lead status update made` unless a specific status write was actually performed.

If the user asks for a same-thread reply draft to a REALTOR.ca showing request:
- Draft only unless the user explicitly says to send or create the Gmail draft.
- Use the original REALTOR.ca/Gmail subject with `Re:`.
- Match the realtor's message tone: `Hi <Name> :)`, short, warm, first person, no em dashes, space before `?`/`!`.
- Use property-specific showing constraints if found in the email/thread or provided context. For a seller-accommodated-showing scenario, a concise ask like `The sellers are happy to accommodate viewings anytime before the dinner rush, and 12 to 3 would be ideal if that works for you. Does something in that window work on your end ?` fits better than a generic availability menu.
- Do not create CRM/lead records under draft-only scope. State clearly whether anything was sent, drafted, or changed.

## Useful extraction script pattern

Use a short Python helper to keep raw JSON/tool noise out of the final answer:

```python
import base64, html, json, re, subprocess

def gws(args):
    p = subprocess.run(args, capture_output=True, text=True, check=False)
    out = p.stdout
    if out.startswith('Using keyring'):
        out = '\n'.join(out.splitlines()[1:])
    return json.loads(out)

def decode(data):
    if not data:
        return ''
    return base64.urlsafe_b64decode(data + '='*((4-len(data)%4)%4)).decode('utf-8','replace')

def walk(part):
    chunks = []
    mt = part.get('mimeType','')
    body = part.get('body',{})
    if body.get('data') and mt in ('text/plain','text/html'):
        chunks.append(decode(body['data']))
    for child in part.get('parts',[]) or []:
        chunks.extend(walk(child))
    return chunks

msg = gws(['gws','gmail','users','messages','get','--params',json.dumps({'userId':'me','id':'MESSAGE_ID','format':'full'}),'--format','json'])
headers = {h['name'].lower(): h['value'] for h in msg.get('payload',{}).get('headers',[])}
body = ' '.join(walk(msg.get('payload',{})))
body = re.sub(r'<[^>]+>', ' ', body)
body = re.sub(r'\s+', ' ', html.unescape(body)).strip()
print(headers.get('date'))
print(headers.get('from'))
print(headers.get('subject'))
print(body[:1000])
```

## Final response format

Keep it concise. Include:

- Date/time, preserving original email timezone if useful and optionally converting to PT.
- Subject.
- Sender.
- Relevant snippet showing the classification evidence.
- Clear classification only.
- If relevant, state that nothing was changed.

Do not include unrelated candidate emails unless the user asks for all matches.