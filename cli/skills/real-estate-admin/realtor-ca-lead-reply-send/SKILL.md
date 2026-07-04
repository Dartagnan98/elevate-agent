---
name: realtor-ca-lead-reply-send
description: "Send an approved reply to a REALTOR.ca lead or showing request and mark it handled. Use when the realtor says \"looks great, send it\" or \"email them back and offer 12-3\" after a reply was drafted."
version: 1.0.0
metadata:
  elevate:
    tags: [real-estate, realtor.ca, leads, showing-request, email, mailjet, lead-status]
    related_skills: [realtor-ca-inbox-classification, outreach-lanes]
---

# REALTOR.ca lead reply send

Use this after a REALTOR.ca lead/inquiry/showing request has been found and the user explicitly says to send the drafted reply.

## Trigger examples

- “Looks great. Please send it to them in an email.”
- “Send that reply to the REALTOR.ca lead.”
- “Email them back and offer 12-3.”

## Guardrails

- A draft approval such as “looks great, send” is approval to send that specific message. Do not ask again.
- Do not improvise a materially different message after approval. Only make tiny formatting fixes.
- If the recipient email is missing, retrieve it from the original REALTOR.ca email or ask for it. Do not guess.
- Use the realtor's voice rules for the message body: `Hi Name :)`, no em dashes, space before `?` and `!`, warm and short.
- For browser/online portal work, use the account's configured browser-automation path only.

## Send path

1. Confirm the contact details already extracted from the REALTOR.ca lead:
   - name
   - email
   - phone, if present
   - listing address / MLS
   - lead type, especially showing request vs inquiry

2. If Gmail/browser compose is needed, use `browser-use --profile --session <name>` and avoid Cloud/API/profile-sync paths. If a session reports `different config`, reuse it without explicit config or close/reopen the session before continuing. Before sending from Gmail, verify the signed-in Google account is actually the realtor's sending account. Local browser profiles may open a different Google account; if Gmail is not clearly the realtor's account, do not send from that session.

3. If a transactional email is acceptable and the sender is verified, Mailjet MCP is the preferred fallback when Gmail/browser state is ambiguous, signed into the wrong account, or stuck on session/profile issues:
   - Check sender with `mcp_mailjet_get_sender(email="<realtor's sending address>")`.
   - Send with `mcp_mailjet_send_email` from the realtor, `reply_to` the realtor, and both text + simple HTML bodies.
   - Keep the subject tied to the original thread, for example `Re: Showing request for 450 Main Street Unit# 17`.

4. Verify delivery after send:
   - Use returned `MessageID`, `MessageHref`, or `MessageUUID`.
   - Read back via Mailjet request when available, e.g. `mcp_mailjet_mailjet_request(method="GET", path="message/<id>")`.
   - Report only when status is `sent` or equivalent success.

## Lead board handling

The board-sync reminder may say a lead was left with no status. The `lead_status` tool requires an existing `contact_id`; it cannot create a contact.

If `lead_status` returns `contact not found`:

1. Search contacts by exact email/phone/name with `elevate_db`.
2. If no contact exists, create/upsert one with `elevate_db(action="call", function="upsert_contact", kwargs={...})` using:
   - `display_name`
   - `primary_email`
   - `primary_phone`
   - `type="buyer"` for buyer/showing inquiries unless evidence says otherwise
   - `stage="hot"` for an active showing request
   - `lead_source="REALTOR.ca"`
   - `opportunity` describing the listing/showing request
   - `tags_json` / `lead_types_json` for `REALTOR.ca`, address, and `showing_request`
3. Use the returned contact `id` with `lead_status`:
   - `action="set", status="follow_up"`
   - `action="heat", label="hot", score=80-90, reason="REALTOR.ca showing request..."`
   - `action="follow_up", needs=true`
4. Add a contact note with `add_contact_note` including:
   - date
   - what was sent
   - showing window offered
   - delivery handle/MessageID/UUID

## Final response format

Keep the final concise:

- `Sent to <Name> by email.`
- To / From
- delivery status and MessageUUID or MessageID
- lead board status update made

Do not paste the whole email again unless the user asks.

## Pitfalls learned

- `lead_status` requires `contact_id`; passing an email/name will fail if the contact is not already in Elevate.
- If no contact exists, use `upsert_contact` first, then run `lead_status` against the returned `id`.
- Mailjet readback may return `Subject: ""` even when the send request included a subject. Treat the message `Status: sent` plus matching MessageID/UUID as the verification handle.
