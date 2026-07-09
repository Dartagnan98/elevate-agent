-- Opt-in Electron main-process crash reports (B4).
--
-- Stores only the sanitized crash envelope: app version/arch/kind + a redacted
-- message + stack + startup timeline. Raw prompts, answers, URLs, file paths,
-- emails, and secrets are redacted twice (desktop client before POST, API route
-- again) and must never appear here. No RLS policies → only service_role (the
-- API route) can read or write.
create table if not exists app_crash_reports (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  license_id    uuid references licenses(id) on delete set null,
  app_version   text,
  platform      text,
  arch          text,
  kind          text not null default 'uncaughtException',
  message       text not null default '',
  stack         text not null default '',
  timeline      jsonb not null default '[]'::jsonb,
  client_ts     timestamptz,
  created_at    timestamptz not null default now()
);

create index if not exists app_crash_reports_user_created_idx
  on app_crash_reports (user_id, created_at desc);

create index if not exists app_crash_reports_version_created_idx
  on app_crash_reports (app_version, created_at desc);

create index if not exists app_crash_reports_kind_created_idx
  on app_crash_reports (kind, created_at desc);

alter table app_crash_reports enable row level security;

-- no policies: anon/authenticated get nothing. service_role bypasses RLS.
