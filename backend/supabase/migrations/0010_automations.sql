-- Premium lead/admin automation kit, distributed from the backend like skills.
--
-- The CLI previously hardcoded the surface heartbeat + automation specs in
-- cli/cron/jobs.py and seeded them per account whenever the gateway ran. That
-- made them ungated (any account got them) and impossible to change without an
-- app release. This table makes the kit a backend-driven, entitlement-gated
-- download: the client fetches GET /api/automations/list (filtered by tier +
-- entitlements exactly like skills) and seeds each row PAUSED per account.
--
-- `kind` distinguishes the two seed paths in the CLI:
--   heartbeat  -> SURFACE_HEARTBEAT_DEFAULTS-shaped (goal + experiment in spec)
--   automation -> SURFACE_AUTOMATION_DEFAULTS-shaped (prompt + skill)
create table if not exists automations (
  name                  text primary key,
  surface               text not null default '',          -- leads | admin | ''
  kind                  text not null default 'automation', -- heartbeat | automation
  schedule              text not null default '',           -- cron expr
  skill                 text not null default '',
  prompt                text not null default '',
  deliver               text not null default 'local',
  spec                  jsonb not null default '{}'::jsonb,  -- goal/experiment/extras
  tier_required         user_tier not null default 'pro',
  manifest              jsonb not null default '{}'::jsonb,  -- entitlement gating
  version               integer not null default 1,
  enabled               boolean not null default true,       -- row active in catalog
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists automations_enabled_idx on automations (enabled);
create index if not exists automations_surface_idx on automations (surface);

-- touch_updated_at() is defined in 0001_init.sql
drop trigger if exists automations_touch_updated_at on automations;
create trigger automations_touch_updated_at
  before update on automations
  for each row execute function touch_updated_at();

-- RLS on, no policies: anon/authenticated get nothing, service_role bypasses.
alter table automations enable row level security;
