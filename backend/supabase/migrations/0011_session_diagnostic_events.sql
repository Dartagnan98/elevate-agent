-- Privacy-safe session recorder ingest.
--
-- Stores only the sanitized event envelope produced by the local recorder.
-- Raw prompts, answers, browser snapshots, URLs, file paths, and stack traces
-- are rejected/dropped before insert by the API route and should never appear
-- in payload.
create table if not exists session_diagnostic_events (
  id                  uuid primary key default gen_random_uuid(),
  event_id            text not null unique,
  user_id             uuid not null references users(id) on delete cascade,
  license_id          uuid references licenses(id) on delete set null,
  session_id          text,
  parent_session_id   text,
  child_session_id    text,
  task_id             text,
  turn_id             text,
  event               text not null,
  severity            text not null default 'info',
  source              text not null default 'backend',
  component           text,
  payload             jsonb not null default '{}'::jsonb,
  redaction           jsonb not null default '{}'::jsonb,
  client_ts           timestamptz,
  client_seq          bigint,
  app_version         text,
  backend_build       text,
  created_at          timestamptz not null default now()
);

create index if not exists session_diagnostic_events_user_created_idx
  on session_diagnostic_events (user_id, created_at desc);

create index if not exists session_diagnostic_events_session_created_idx
  on session_diagnostic_events (session_id, created_at desc)
  where session_id is not null;

create index if not exists session_diagnostic_events_event_created_idx
  on session_diagnostic_events (event, created_at desc);

alter table session_diagnostic_events enable row level security;

-- no policies: anon/authenticated get nothing. service_role bypasses RLS.
