# Lofty API surface — by category

Source: `https://developer.lofty.com/openapi/openapi.json` (94 paths, 159 schemas).
Pulled 2026-05-14.

Auth: `LOFTY_API_KEY` (header `Authorization: token <key>`) or
`LOFTY_ACCESS_TOKEN` (`Authorization: Bearer <token>`).

Identifier note: all entity IDs are int64. Store as `TEXT` in SQLite to
avoid JS precision loss when pumping through the web layer.

Legend:
- ✅ pulled today, stored in `~/.elevate/sources/crm/*.jsonl` (legacy) and partly mirrored to operational.db
- ⚠️ pulled today but discarded (lives in raw lead JSON only)
- ❌ never pulled — would need a new sync pass + table

---

## 1. Lead core

`GET /v1.0/leads` (list), `GET /v1.0/leads/{leadId}`, `POST/PUT/DELETE`,
`POST /v1.0/leads/assignee` (preview routing), `POST /v1.0/leads/{leadId}/assignment`.

### Fields (`LeadResponse`)

| Field | Type | Status |
|---|---|---|
| leadId | int64 | ✅ |
| leadUserId | int64 | ❌ |
| firstName, lastName | string | ✅ (concatenated → `display_name`) |
| emails[] | string[] | ✅ |
| phones[] | string[] | ✅ |
| phoneStatuses[] | int[] | ❌ — invalid/valid/talked indicators |
| birthday | string | ❌ |
| language | string | ❌ |
| facebook, twitter | string | ❌ |
| leadSource (id) + source (string) | int + string | ✅ source only |
| stageId + stage | int + string | ✅ stage only |
| score | int | ✅ |
| tags[] (`UserLeadTagVo`: tagId, tagName, visibleType, creatorUserId) | array | ✅ tagName only |
| segments[] | string[] | ❌ — replaces deprecated `groups[]` |
| leadTypes[] | int[] | ❌ — Seller(1) / Buyer(2) / Renter(3) / Other(-1) |
| assignedUserId + assignedUser | int + string | ✅ user string only |
| lenderUserId | int64 | ❌ |
| teamId | int64 | ❌ |
| pondId + pondName | int + string | ❌ |
| streetAddress, city, state, zipCode | string | ❌ (deprecated on lead, lives on `leadPropertyList`) |
| createTime, lastUpdateTime, assignTime, lastTouch, lastVisit | string | ✅ partial (only first 1-2) |
| cannotText, cannotCall, cannotEmail | bool | ❌ — **consent flags, important** |
| unsubscription | bool | ❌ |
| hiddenFlag | bool | ❌ |
| referredBy | string | ❌ |
| opportunity | string | ❌ |
| **Buyer qualification (free fields)**: buyingTimeFrame, preQual, houseToSell, fthb, withBuyerAgent, mortgage, buyHouse | string ("Yes"/"No"/range codes) | ❌ |
| **Seller qualification**: sellingTimeFrame, withListingAgent | string | ❌ |
| leadInquiry | LeadInquiry obj | ❌ — see §2 |
| leadPropertyList[] | LeadProperty[] | ❌ — see §3 |
| leadFamilyMemberList[] | LeadFamilyMember[] | ❌ — see §4 |
| customAttributes[] | CustomAttribute[] | ❌ — see §15 |
| customRoleList[] | CustomRole[] | ❌ |
| assignCompletionStatus | bool | ❌ |
| ownershipId + ownershipScope | int + string | ❌ |

---

## 2. Lead saved-search criteria (`LeadInquiry`)

Embedded in the lead. There's no standalone endpoint — it round-trips
through `GET /v1.0/leads/{leadId}` and `PUT /v1.0/leads/{leadId}`.

```
priceMin, priceMax              int64
propertyType[]                  string[]  (Single Family Home, Condo, Townhouse, Mobile Home, etc.)
bedroomsMin, bedroomsMax        int
bathroomsMin, bathroomsMax      string
locations[]                     Location[] (city + stateCode)
modifyByAgent                   bool
defaultValue                    bool
createTime, updateTime          date-time
```

Status: ❌ never pulled. **This is the buyer-intent payload — what they
actually want.** Highest-priority addition for Open Thread.

---

## 3. Lead properties (`leadPropertyList`)

Embedded in the lead. Each entry is a property the lead is interested in
(viewed, favorited, inquired about) or — for sellers — the property
they're selling.

```
id                              int64  (the lead-property record id)
listingId, autoListingId        string / int64  (MLS link)
streetAddress, city, state, zipCode, county     string
propertyType                    string  ("Single Family Home", "Condo", ...)
bedrooms, bathrooms             int / double
squareFeet                      int64
lotSize                         double  (acres)
parkingSpace                    int64
floors                          int
price, priceMin, priceMax       int64
label                           string  ("Favorited", "Viewing", "Submitted Inquiry", custom)
labelType, labelList            string
note                            string
listingStatus                   string
pictureUrl, siteListingUrl      string
mailAddress                     bool   (true = mailing address rather than property of interest)
```

Status: ❌. **Required for Open Thread — "what listings is this lead
attached to."**

---

## 4. Family members (`LeadFamilyMember`)

Embedded in the lead under `leadFamilyMemberList`. Co-buyers, spouses,
kids.

```
relationship             string  ("Husband", "Wife", "Co-Buyer", "Child")
firstName  (required)    string
lastName                 string
phones[]                 string[]
emails[]                 string[]
birthday                 string  ("MMM d, yyyy")
```

Status: ❌. Useful for de-dup vs "second contact same household" and for
showing "this lead has a co-buyer" in the thread drawer.

---

## 5. Activities (timeline)

`GET /v2.0/leads/{leadId}/activities` (preferred),
`GET /v1.0/leads/{leadId}/activities`, `POST /v1.0/leads/{leadId}/activity`.

```
id              int64
leadId          int64
agentId         int64
activityTime    ISO 8601
channel         string  (Call | Text | Email)
communicationType  string  (Auto | Manual | Logged)
direction       string  (Inbound | Outbound)
callingOutcome  string  (Talked, No Answer, Voicemail, ...)   — Call only
leadPhoneNumber string                                          — Call only
emailEventType  string  (Sent | Opened | Bounced)               — Email only
emailSubject    string                                          — Email only
note            string                                          — Logged only
listing         LeadProperty  (when activity is a Browse/Search/Inquiry)
type, text, link, picture, created, scheduledDate, pageName        — Browse shape
```

Status: ✅ pulled and normalized into `lead-events.jsonl` via
`_lofty_get_activities` + `_lofty_normalize_activity`. **No SQLite mirror
yet** — would land in the existing `events` table.

---

## 6. Notes

`GET /v1.0/notes?leadId=…` (list), `GET/PUT/DELETE /v1.0/notes/{noteId}`,
`POST /v1.0/notes`.

```
noteId             int64    (use with GET/PUT/DELETE — distinct from timeline id)
id                 int64    (timeline id)
leadId             int64
creatorId          int64
creatorName        string
lastEditorId       int64
lastEditorName     string
content            string
createTime         string   ("yyyy-MM-dd HH:mm:ss" UTC)
lastUpdate         string
deleteFlag         bool
isPin              bool
systemNote         bool     (auto-generated vs agent-typed)
```

Status: ✅ pulled into `lead-events.jsonl` (type=`lofty_note`).
`isPin` / `systemNote` / `lastEditor` are dropped — would be useful in
Open Thread.

---

## 7. Tasks & appointments

V1: `GET/POST/PUT/DELETE /v1.0/tasks`, `GET /v1.0/appts`.
V2: `GET/POST/PUT/DELETE /v2.0/tasks`, `/finish`, `/unfinish`, `my-tasks`.

### V2 task (`TaskResponseV2`) — the modern shape

```
id, leadId, creatorId            int64
content                          string
type                             string  (Call | Email | Text | Other | Appointment)
subject, body                    string  (Email-type only)
startAt, endAt                   ISO 8601
timeZoneCode                     string
allDay                           bool
address                          string  (Appointment-type only)
finishFlag, overdueFlag          bool
finishTime, createTime, lastUpdate    string
reminderType                     int
assignedRole                     string  (Agent | Assistant)
assignedUser + assignedUserId    string + int64
pipelineId                       int64
queryId, queryInfo               int + string   (smart-plan provenance)
leadName, leadEmail, leadPhone, leadFirstName, leadLastName    string
teamId, leadUserId               int64
```

### V1 `Appointment` (legacy, distinct table from tasks)

```
id, leadId, creatorId, assignToUid    int64
descr, address                        string
deadline (start), endTime, finishTime, createTime, lastUpdate   int64 ms / date-time
allDay, finishFlag, deleteFlag, overdue                         bool
assignRoleType                        int
```

Status: ✅ tasks pulled into `lead-events.jsonl` (type=`lofty_task`) via
`_lofty_get_tasks` (still hitting v1.0 path — we should switch to v2.0).
**Appointments and v2 task fields (startAt/endAt/timeZoneCode/address)
are dropped today.**

---

## 8. Calls

`GET /v1.0/calls` (list of a lead, requires `leadId` param),
`GET /v1.0/calls/{callId}`, `GET /v1.0/call/url/{callId}` (recording URL).
Also `GET /v1.0/communication/call` and `/v2`.

### `CallHistory`

```
id            int64
agentId       int64
leadId        int64
createTime    string
direction     string   (Outbound | Inbound)
leadPhoneNumber  string
```

Full call (`CallResponse`) adds duration, outcome, recording metadata,
talk-time. Recording URL is a separate endpoint.

Status: ⚠️ partially — call activity surfaces in `/v2.0/leads/{id}/activities`
with channel=Call, but duration/recordingUrl/voicemail-transcript are
**never pulled**.

---

## 9. Email + SMS history

`GET /v1.0/communication/email`, `GET /v1.0/communication/text`,
`POST /v1.0/message/email/send`, `POST /v1.0/message/sms/send`.

### `EmailResponse`

```
id                int64
leadId            int64
direction         string
agentId           int64
eventType         string   (Sent | Opened | Bounced)
emailEventTime    string
emailType         string   (Manual | Auto)
emailSubject      string
fromPond          bool
```

### `SmsResponse`

```
messageId         string
phoneNumber       string
phoneCode         string
```

Status: ⚠️ partial — these events leak through the v2 activities
endpoint, but the dedicated history endpoints with rich event types
(Opened/Bounced for emails, delivery status for SMS) aren't pulled.

---

## 10. Manual logs (custom timeline categories)

`GET /v1.0/logType` (list of a lead), `POST /v1.0/logType` (add),
`GET /v1.0/logType/{logTypeId}`, `DELETE /v1.0/logType/{logTypeId}`.

Agent-configured custom log types (e.g. "Met in person", "Sent gift",
"Saw at open house"). Schema is team-specific.

Status: ❌. Optional. Most teams use this for off-channel touchpoints
that should land in the thread.

---

## 11. AI features

`POST /v2.0/ai/prepare-insight` — generate context briefing for a lead.
`GET /v2.0/ai/lead-analysis`, `POST /v2.0/ai/lead-analysis` — async lead-analysis tasks.
`POST /v2.0/ai/call-summary/generate`, `GET /v2.0/ai/call-summary` — AI call transcript summary.
`POST /v2.0/ai/call-script` — generate next-call script for a lead.

Status: ❌. We do our own scoring (`review_contact`) so lead-analysis is
redundant, but **call-summary is a free win** — show the transcript
summary inline in Open Thread instead of just "call, 4 min".

---

## 12. Sales Agents (Lofty's AI dialer)

Whole separate v2 surface — only relevant if the team uses Lofty's AI
dialer ("Sales Agents").

- `GET /v2.0/working-leads` — paginated list of leads in the AI working pool
- `POST /v2.0/working-leads/add` — batch add
- `PUT /v2.0/sales-agents/working-lead/{leadId}/mute`
- `GET /v2.0/sales-agents/by-lead`, `/quota`, `/current`
- `GET /v2.0/plan-tasks/lead/{leadId}` — plan tasks per lead
- `POST /v2.0/plan-tasks/create` — batch create plan tasks
- `POST /v2.0/sales-agent/ai-number/send-sms-to-agent`

```
WorkingLeadV2: leadId, firstName, lastName, email, phone, createdAt
PlanTaskResponseV2: id, content, taskType (CALL/EMAIL/TEXT), status (PENDING/FINISHED/OVERDUE), dueAt, createdAt, assignedTo, creatorId
```

Status: ❌. Skyleigh isn't on Sales Agents AFAIK — verify before pulling.

---

## 13. Calendar V2

`GET /v2.0/calendar` (list events — unifies tasks + appointments),
`POST /v2.0/calendar` (create), `PUT /v2.0/calendar/{calendarId}`,
`POST /v2.0/calendar/{calendarId}/finish`/`unfinish`, `DELETE`,
`GET /v2.0/calendar/meetings/available`.

### `CalendarItemV2`

```
id            string   ("12345-task" or "12345-appointment")
type          string   (TASK | APPOINTMENT)
taskId        int64
sourceType    int
content       string
title         string   (auto: lead name + event type)
finished      bool
startAt, endAt    ISO 8601
startAtMs, endAtMs  int64
timeZoneCode  string
leadId        int64
```

Status: ❌. Useful as the canonical "what's on this lead's calendar"
feed for the thread drawer, instead of stitching tasks + appointments.

---

## 14. Transactions (deals)

`GET /v2.0/transactions` (list all), `GET /v1.0/leads/{leadId}/transactions`,
`POST /v1.0/leads/{leadId}/transaction` (create),
`GET/PUT /v1.0/leads/{leadId}/transaction/{transactionId}`,
`POST /v1.0/leads/{leadId}/transaction/property/address` (set address),
`GET /v1.0/transaction/customfields` (custom field defs).

### `TransactionV2Item`

```
transactionId, leadId, propertyId      int64
transactionName                        string  (property address / deal name)
leadName, agentName                    string
assignedAgent                          int64
transactionType                        enum  (Purchase | Listing | Lease | Other)
transactionStatus                      string  (team-configured pipeline status)
homePrice                              number
commissionRate, gci, teamRevenue, agentRevenue   number
expectedCloseDate, closeDate            int64 ms
appointmentDate, agreementSignedDate    int64 ms
offerDate, contractDate, appraisalDate, homeInspectionDate, escrowDate    int64 ms
expiration                             int64 ms
created, updated                       int64 ms
customFields[]                         CustomFieldRequest[]
```

Status: ❌. **High-value.** Our `deals` table is the local twin; this is
the source of truth on Lofty's side. We'd pull these and reconcile
against `deals` on sync.

---

## 15. Custom fields

`GET /v1.0/teamFeatures/listCustomField` — lead custom-field defs.
`GET /v1.0/transaction/customfields` — transaction custom-field defs.
`POST /v1.0/teamFeatures/custom-field` — add a lead custom field.

### `CustomFieldResponse`

```
id      int64
name    string
type    enum  (DATE | TEXT | NUMBER | PERCENTAGE | Single-Select | Multi-Select | CURRENCY | HTML)
params  string  (JSON-encoded option list for select types)
```

Custom field values live on the lead as `customAttributes[]`
(name/value pairs keyed by the def `id`).

Status: ❌. Without these, every team-specific field (e.g. "Loan officer",
"FUB tag") is invisible in our thread drawer.

---

## 16. Tags (reference data)

`GET /v1.0/teamFeatures/listTag` — list of tags available to the caller.
Per-lead tags come embedded in `LeadResponse.tags[]`.

```
UserLeadTag: tagId, tagName, visibleType, creatorUserId, leadId, createTime
```

Status: ⚠️ tagNames pulled into `tags[]`, full tag metadata dropped.

---

## 17. Lead Ponds (shared lead pools)

`GET /v1.0/team-features/lead-ponds` — list visible ponds.
`GET /v1.0/team-features/lead-pond/{id}` — pond detail.

```
LeadPond: id, pondName, pondOwnerId, agentIds[]
```

Status: ❌. Determines whether the lead is in a team pond vs assigned
directly. Useful for "this lead is in the shared follow-up pond,
nobody's been told to call them yet."

---

## 18. Team members

`GET /v1.0/me` — caller's profile.
`GET /v1.0/members` — team roster.
`GET /v1.0/members/{account}` — by email.
`GET /v1.0/users/{userId}` — (deprecated) by id.

`UserResponse` has the standard agent fields (id, firstName, lastName,
email, phone, role, profilePicture, etc).

Status: ❌. Needed if we want to show "assigned to <name>" with avatar
in Open Thread — we currently just store `assignedUser` as a string.

---

## 19. Organization + offices

`GET /v1.0/org`, `POST /v1.0/org/company`, `POST /v1.0/org/office`,
`PUT /v1.0/org/office`, `GET /v1.0/org/permission/profiles`.

```
OrganizationInfo: orgType, enterpriseInfo, multiTeamInfo
```

Status: ❌. Reference data, low priority.

---

## 20. Routing

`GET /v1.0/routing/role/list`, `GET /v1.0/routing/rule/list/{type}`,
`PUT /v1.0/routing/rule/{type}`, `GET/PUT /v1.0/routing/rule/supplement/{type}`,
`GET /v1.0/routing/member/list/{type}`, `POST /v1.0/leads/assignee`
(preview which agent a lead would route to).

Status: ❌. Admin-side. Useful if we want Elevate to mirror Lofty's
routing decisions instead of round-robining ourselves.

---

## 21. Listings (MLS)

`GET /v1.0/listing` — search by agent / office.
`POST /v2.0/listings/search` — search by filters.
`GET /v1.0/getPublishedListings` — agent's published listings.

### `ListingItem` (the big one)

Address (street, city, state, zip[], county, area, subdivision, community),
price, beds, baths, sqft, builtYear, lotSize, listingStatus, purchaseType,
propertyTypes[], propertyTypePrimary/Secondary, pictureList[],
openHouseSchedules + start/end, agent+coAgent (id, name, orgId, orgName),
hoaFee + frequency, condoFee + frequency, garageParkingSpaces,
interiorFeatures, exterior, mlsListDateL, detailsDescribe (full
description).

Status: ❌. Separate from leads. Worth pulling so Open Thread can show
"this is the listing they're asking about" with photo + full detail.

---

## 22. Vendors

`GET /v1.0/vendor/list` — caller's team vendors (lenders, inspectors,
title reps, etc).

```
VendorInfo: id, agentUserId, firstName, lastName, phoneNumber, phoneCode,
phoneCountry, email, roleName, companyName, companyAddress
```

Status: ❌. Useful for "this lead's lender is X" lookups.

---

## 23. System logs

`GET /v1.0/systemLogs` — full audit trail of internal events
(assignment changes, stage moves, automated actions).

```
SystemLogResponse: id, leadId, agentId, timelineType, timelineTime,
createTime, fromId, fromType, toId, toType, leadFullName, fromFirstName,
fromLastName, toFirstName, toLastName, sticky, canSticky, content (JSON
varies by timelineType), updateTime
```

Status: ❌. The most complete audit log. Best replacement for our own
event re-derivation logic.

---

## 24. Webhooks (push instead of poll)

`POST /v1.0/webhook` (create), `GET /v1.0/webhooks` (list),
`DELETE /v1.0/webhook/{subscribeId}`.

```
WebhookResponse: subscribeId, teamId, listId (event-category id),
vendorId, callbackUrl, limit (rate, max 5000/30min)
```

Status: ❌. **If we're hosted at `app.ctrlstrategies.com`, register a
webhook and stop polling.** Currently we sync the entire lead list every
cron tick.

---

## 25. Notifications

`POST /v2.0/sales-agent/notification/app-push/send-task-reminder` (push),
`POST /v2.0/sales-agent/message/sms/send-to-agent`,
`POST /v2.0/sales-agent/message/email/send-to-agent`,
`POST /v1.0/agent/send-notification` (opportunity alert).

Status: ❌. Outbound only — we can use these to notify agents from
Elevate without spinning our own SMS/email rail through Lofty.

---

# Recommended DB / Open-Thread additions, ranked

| # | Priority | Category | New table(s) | Why |
|---|---|---|---|---|
| 1 | **P0** | §2 Lead Inquiry | `lead_inquiries` (1:1 with contact) | Buyer-intent payload. The single highest-signal field set in the API. |
| 2 | **P0** | §3 Lead Properties | `lead_properties` (1:N) | "What homes are they looking at." Drives every other surface. |
| 3 | **P0** | §1 Lead consent + qualification | extend `contacts` (cannot_text/call/email, unsubscription, opportunity, buying_time_frame, selling_time_frame, pre_qual, house_to_sell, fthb, etc.) | Consent flags = compliance. Qualification fields = lead routing logic. |
| 4 | **P0** | §14 Transactions | mirror into existing `deals` table (new columns: `lofty_transaction_id`, `commission_rate`, `gci`, all date columns) | We already have `deals`; missing the financial + date fields. |
| 5 | **P1** | §5 Activities + §8 Calls + §9 Email/SMS | extend `events` (already have it) — pull v2 activities + dedicated email/SMS endpoints | Existing `events` table just needs richer payloads (eventType for emails, callingOutcome for calls). |
| 6 | **P1** | §4 Family members | `lead_family_members` (1:N) | Co-buyer / spouse identity. Also enables identity merge. |
| 7 | **P1** | §15 + §1 customAttributes | `custom_field_defs` (team-level) + `contact_custom_values` (per-contact JSON or 1:N) | Without these, team-specific fields invisible. |
| 8 | **P1** | §16 Tags + §17 Ponds | `lead_tags_ref` (team tag catalog), add `pond_id` + `pond_name` to contacts | Pond membership changes routing. |
| 9 | **P2** | §11 AI call summary | extend `events` (`call_summary` payload) | Free transcript summary on Lofty's side. |
| 10 | **P2** | §21 Listings | `listings` table (MLS feed) | Show full listing card next to "they asked about 123 Main St". |
| 11 | **P2** | §13 Calendar V2 | new `calendar_events` or just lean on `tasks` v2 columns | Unified feed; can stitch from tasks for now. |
| 12 | **P2** | §18 Team members | `lofty_users` reference table | Avatar / proper name for "assigned to". |
| 13 | **P3** | §22 Vendors | `lofty_vendors` reference table | Lender + partner lookup. |
| 14 | **P3** | §23 System logs | extend `events` with `kind='system_log'` rows | Audit trail. |
| 15 | **P3** | §24 Webhooks | replace cron poll with push | Real-time sync. Requires public callback URL. |
| 16 | **P3** | §10 Manual logs | extend `events` with `kind='manual_log'` rows | Team-specific touchpoints. |
| 17 | optional | §12 Sales Agents | n/a | Only if Skyleigh adopts Lofty's AI dialer. |
| 18 | optional | §19 Org, §20 Routing | n/a | Admin-side, low value. |

---

## Suggested next migrations

```
0015_lead_inquiry.sql      — lead_inquiries (contact_id pk, price/beds/baths/locations json, updated_at)
0016_lead_properties.sql   — lead_properties (id, contact_id, label, address, listing_id, picture_url, ...)
0017_contacts_lofty_fields.sql
                           — ADD COLUMN cannot_text, cannot_call, cannot_email,
                             unsubscription, hidden, opportunity, buying_time_frame,
                             selling_time_frame, pre_qual, house_to_sell, fthb,
                             with_buyer_agent, mortgage, buy_house, with_listing_agent,
                             pond_id, pond_name, lead_types, segments_json, lofty_lead_user_id
0018_deals_lofty_sync.sql  — ADD COLUMN lofty_transaction_id, commission_rate, gci,
                             team_revenue, agent_revenue, appointment_date, agreement_signed_date,
                             offer_date, contract_date, appraisal_date, home_inspection_date,
                             escrow_date, expiration_date
0019_lead_family.sql       — lead_family_members
0020_custom_fields.sql     — custom_field_defs + contact_custom_values
0021_listings.sql          — listings (mls feed)
0022_call_summaries.sql    — call_summaries (call_id pk, transcript, summary, ai_model)
```

Each migration is additive — no data loss. The connector
(`sync_lofty_crm_source`) extends one endpoint at a time; the
read-side (`db_thread_context_response`) starts surfacing the new
columns once they're populated.
