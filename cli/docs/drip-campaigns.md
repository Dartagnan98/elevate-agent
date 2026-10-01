# Drip campaigns

The Leads pack's Drips section (`/drips` in the dashboard). Ships the
Elevation campaigns as editable templates, lets an install build its own, and
runs the day-by-day schedule for every contact on a campaign.

## Model

| Table | What it holds |
| --- | --- |
| `drip_segments` | The pipeline segments a contact can be in. Renameable, reorderable, colour-coded, switchable. Seeded: New, Hot, Warm, Lukewarm, Long-Term, Bad Number, SOI / Past Clients. |
| `drip_campaigns` | A campaign: nurture, course, playbook or custom. `role` is `primary` (one per person at a time) or `layer` (runs alongside). `trigger_segment` auto-starts it the day a contact enters that segment; `layer_flag` (`buying` / `selling`) auto-starts a layer for everyone with that flag. `enabled` is the on/off switch. |
| `drip_steps` | The touches: `day` (day 1 = the day the campaign starts), `channel` (text, email, call, task, tag), copy, optional video slot, and for tag steps a `route_to` (a segment key, `done`, or `restart`). |
| `drip_contact_segments` | Which segment each contact is in now, plus the buying/selling flags. |
| `drip_enrollments` | A contact running through a campaign (`active`, `paused`, `completed`, `stopped`). |
| `drip_touches` | The materialised schedule for one enrollment: one row per step with a due date and a status. |
| `drip_videos` | The shared video script library. Paste a link once and every touch that names the video picks it up. |
| `drip_settings` | Engine settings (auto-enrol new leads, automatic tag moves, send window, calls as tasks, pause AI drafts for people on a campaign, newsletter tool). |

Schema: `elevate_cli/data/migrations_pg/0035_drip_campaigns.sql`. Store and
engine: `elevate_cli/drips_db.py`. Templates: `elevate_cli/drip_templates.py`.
Routes: `elevate_cli/web_routes/drips.py` (`/api/drips/*`). Page:
`web/src/pages/real-estate-hub/drips/`.

## The rules the engine applies

These come from the Elevation "How the campaigns layer" lesson and are what
`drips_db.set_contact_segment` does:

* **One nurture campaign at a time.** Moving the segment stops every live
  primary campaign that does not start from the new segment and starts the
  one that does, the same day. Day 1 of the new campaign is the day of the move.
* **A reply never stops a campaign.** Only a segment move does. Replies are
  answered by hand; the schedule keeps running.
* **Courses layer by flag, on days that never clash.** A contact flagged
  buying gets the Buyer Course (days 3, 5, 7, 11, 13, 16, 18, 22, 24); flagged
  selling gets the Seller Course (days 6, 8, 12, 17, 19, 23, 26). Each runs
  once per person. If a layer is started mid-campaign and a lesson would land
  on a day that already has a text or email, the lesson moves one day later.
* **Deferred layers.** A primary campaign with `defer_layers` (The First 14
  Days) holds the courses until its tag step routes the contact on.
* **Automatic routing.** A `tag` step fires on its day while the contact is
  still in the campaign's trigger segment: day 15 New → Lukewarm, day 92 Warm →
  Lukewarm, day 187 Lukewarm → Long-Term, day 101 Bad Number → Long-Term, day
  367 Long-Term → restart, day 25/27 course → done. Switch `autoTagMoves` off
  and those steps show up on the board as a decision instead.
* **Switched off means silent.** A disabled campaign is hidden from the board
  and skipped by the engine; nobody is removed. Switch it back on and the
  schedule resumes where it was.

## What runs when

* `drips_db.run_engine` is registered as the no-agent system cron job **Drip
  Campaign Engine** (`cron.jobs.ensure_drip_engine_job`, hourly, script
  `elevate_cli/drip_engine_job.py`). It applies due tag steps, closes finished
  runs, restarts yearly rhythms, puts due call/task touches on the Tasks board
  (`project = "drips"`), and auto-enrols new buyer/seller leads created after
  the setting was switched on. The board's "Run the engine now" button calls
  the same thing (`POST /api/drips/run`).
* Texts and emails are **not sent automatically** in this phase. The due board
  renders the copy with the contact's first name, the realtor's name and
  brokerage, the phone number and the recorded video link filled in, flags the
  placeholders still to swap by hand, and offers Copy / Mark sent / Skip.
  Wiring sends into the outreach send queue is the next phase.
* The outreach skill treats anyone with a live enrollment as `send_suppressed`
  while `pauseAiDraftsInCampaigns` is on (see
  `skills/real-estate-admin/outreach/SKILL.md`, Phase 2).

## Templates

`drip_templates.py` carries the approved Elevation set: The First 14 Days,
Warm / Lukewarm / Long-Term Nurture, the Bad Number Drip, the Buyer and Seller
Courses, the Hot Leads, Top 25 and Raving Fan Club playbooks, and the 22-script
Video Script Library (19 shared videos plus the three new-lead videos that live
inside The First 14 Days). They are seeded once per account database on the
first `drips_db.connect()`; after that they are ordinary rows. The Templates
tab can install a missing one, add a second copy (switched off, no automatic
start) or reset an installed one to the original.

Placeholders use the PDFs' square-bracket form (`[First Name]`, `[Your Name]`,
`[Brokerage]`, `[Area]`, `[Insert video: Name]`). `drips_db.render_text` fills
the ones the system knows and reports the rest.

## Tests

* `tests/elevate_cli/test_drips_db.py` — seeding, segment rules, layering and
  clash avoidance, run-once courses, on/off, board rendering, automatic
  routing, call tasks, step edits rescheduling live runs, templates, settings.
* `tests/elevate_cli/test_drips_routes.py` — the HTTP surface.
* `web/src/pages/real-estate-hub/drips/__tests__/drips-helpers.test.ts` —
  schedule wording, clash detection, due-date wording.
