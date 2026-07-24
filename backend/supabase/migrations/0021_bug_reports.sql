-- Team-wide bug / feedback reports collected centrally on Elevation HQ.
--
-- Each Elevate desktop client POSTs a report (a note, an optional downscaled
-- screenshot as a data URL, and lightweight page/deal/version context) to
-- /api/bug-reports authenticated with the same desktop access token it already
-- holds. HQ stores it here so the whole team's bugs collect in one place for an
-- admin to review. The reporter identity (user_id / license_id / email /
-- app_version) is derived server-side from the verified access token — it is
-- never trusted from the request body. FKs use ON DELETE SET NULL so a report
-- survives the deletion of the account that filed it. No RLS policies → only
-- service_role (the API route) can read or write.
create table if not exists bug_reports (
  id             uuid primary key default gen_random_uuid(),
  created_at     timestamptz not null default now(),
  user_id        uuid references users(id) on delete set null,
  license_id     uuid references licenses(id) on delete set null,
  reporter_email text,
  app_version    text,
  note           text not null default '',
  context        jsonb not null default '{}'::jsonb,
  screenshot     text,
  status         text not null default 'open',
  resolved_at    timestamptz
);

create index if not exists bug_reports_created_idx
  on bug_reports (created_at desc);

create index if not exists bug_reports_status_created_idx
  on bug_reports (status, created_at desc);

alter table bug_reports enable row level security;

-- No policies: public / anon / authenticated clients get nothing. The backend
-- acts exclusively through service_role, so keep its exact operations
-- self-contained. UPDATE is granted so an admin review can flip status /
-- resolved_at; the service role never needs DELETE.
revoke all on table public.bug_reports
  from public, anon, authenticated, service_role;
grant select, insert, update on table public.bug_reports
  to service_role;
