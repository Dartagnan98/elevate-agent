-- Elevate HQ initial schema
-- Mirrors src/lib/store.ts types so the file-store -> Supabase migration is 1:1.

-- ---------------------------------------------------------------------------
-- enums
-- ---------------------------------------------------------------------------
create type user_tier as enum ('pro', 'builder');
create type user_status as enum ('active', 'trialing', 'inactive', 'canceled', 'past_due');
create type user_role as enum ('owner', 'admin', 'user');

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table users (
  id                    uuid primary key default gen_random_uuid(),
  email                 text unique not null,
  password_hash         text not null,
  stripe_customer       text unique,
  tier                  user_tier not null default 'pro',
  status                user_status not null default 'active',
  current_period_end    timestamptz,
  entitlements          text[] not null default '{}',
  role                  user_role not null default 'user',
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index users_email_idx on users (lower(email));
create index users_stripe_customer_idx on users (stripe_customer) where stripe_customer is not null;

-- normalize emails on insert/update so lookups always hit the index
create function lower_email() returns trigger as $$
begin
  new.email := lower(new.email);
  new.updated_at := now();
  return new;
end;
$$ language plpgsql;

create trigger users_lower_email_trg
  before insert or update on users
  for each row execute function lower_email();

-- ---------------------------------------------------------------------------
-- licenses (one per device per user)
-- ---------------------------------------------------------------------------
create table licenses (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references users(id) on delete cascade,
  device_label          text,
  refresh_token_hash    text unique not null,
  revoked               boolean not null default false,
  last_used_at          timestamptz,
  created_at            timestamptz not null default now()
);

create index licenses_user_id_idx on licenses (user_id);
create index licenses_active_idx on licenses (user_id) where revoked = false;

-- ---------------------------------------------------------------------------
-- skills (catalog)
-- ---------------------------------------------------------------------------
create table skills (
  name                  text primary key,
  version               integer not null default 1,
  tier_required         user_tier not null default 'pro',
  manifest              jsonb not null default '{}'::jsonb,
  body                  text not null default '',
  enabled               boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index skills_enabled_idx on skills (enabled);

create function touch_updated_at() returns trigger as $$
begin
  new.updated_at := now();
  return new;
end;
$$ language plpgsql;

create trigger skills_touch_updated_at
  before update on skills
  for each row execute function touch_updated_at();

-- ---------------------------------------------------------------------------
-- skill_invocations (audit log)
-- ---------------------------------------------------------------------------
create table skill_invocations (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  skill_name    text not null references skills(name) on delete cascade,
  args_hash     text,
  ip_address    text,
  user_agent    text,
  invoked_at    timestamptz not null default now()
);

create index skill_invocations_user_id_idx on skill_invocations (user_id, invoked_at desc);
create index skill_invocations_skill_idx on skill_invocations (skill_name, invoked_at desc);

-- ---------------------------------------------------------------------------
-- audit_log (admin actions for safety: who revoked what for whom)
-- ---------------------------------------------------------------------------
create table audit_log (
  id            uuid primary key default gen_random_uuid(),
  actor_user_id uuid references users(id) on delete set null,
  target_user_id uuid references users(id) on delete set null,
  action        text not null,
  payload       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

create index audit_log_actor_idx on audit_log (actor_user_id, created_at desc);
create index audit_log_target_idx on audit_log (target_user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- row-level security
-- service_role bypasses RLS; the Next.js API uses service_role.
-- We still enable RLS so accidental anon-key access from clients is denied.
-- ---------------------------------------------------------------------------
alter table users enable row level security;
alter table licenses enable row level security;
alter table skills enable row level security;
alter table skill_invocations enable row level security;
alter table audit_log enable row level security;

-- no policies: anon and authenticated roles get nothing. service_role bypasses RLS.
