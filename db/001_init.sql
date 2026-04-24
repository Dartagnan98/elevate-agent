-- Elevate schema, v1
-- Apply: psql $SUPABASE_DB_URL -f db/001_init.sql

create extension if not exists "pgcrypto";

-- users: one row per paying customer
create table if not exists users (
  id              uuid primary key default gen_random_uuid(),
  email           text not null unique,
  stripe_customer text unique,
  display_name    text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- subscriptions: mirror of stripe subscription state
create table if not exists subscriptions (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references users(id) on delete cascade,
  stripe_sub_id     text unique not null,
  status            text not null,                          -- active|trialing|past_due|canceled|unpaid
  tier              text not null default 'pro',            -- pro|builder
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists subscriptions_user_idx on subscriptions(user_id);

-- licenses: machine-bound tokens. user can have multiple active licenses (one per device in future)
create table if not exists licenses (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id) on delete cascade,
  device_label    text,                        -- "dartagnan's macbook" etc.
  refresh_token_hash text not null unique,     -- SHA-256 of refresh token
  revoked         boolean not null default false,
  last_used_at    timestamptz,
  created_at      timestamptz not null default now()
);

create index if not exists licenses_user_idx on licenses(user_id);
create index if not exists licenses_refresh_idx on licenses(refresh_token_hash);

-- skills: our catalog of skills available to paying users
create table if not exists skills (
  id              uuid primary key default gen_random_uuid(),
  name            text not null unique,        -- e.g. "cma-generator"
  version         int not null default 1,
  tier_required   text not null default 'pro', -- pro|builder
  manifest        jsonb not null,              -- frontmatter metadata
  body            text not null,               -- markdown body (the actual skill prompt)
  enabled         boolean not null default true,
  updated_at      timestamptz not null default now(),
  created_at      timestamptz not null default now()
);

create index if not exists skills_name_idx on skills(name) where enabled = true;

-- skill_invocations: audit log. one row per skill fetch
create table if not exists skill_invocations (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id) on delete cascade,
  skill_name      text not null,
  args_hash       text,                        -- SHA-256 of input args (for abuse detection)
  ip_address      inet,
  user_agent      text,
  invoked_at      timestamptz not null default now()
);

create index if not exists invocations_user_time_idx on skill_invocations(user_id, invoked_at desc);

-- integrations: per-user stored integration credentials (encrypted at app layer)
create table if not exists integrations (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id) on delete cascade,
  kind            text not null,               -- ghl|gcal|gmail|skyslope|aoir
  label           text,                        -- user-friendly label
  encrypted_creds text not null,               -- AES-GCM ciphertext (base64)
  metadata        jsonb,                       -- non-sensitive: location_id, email address, etc.
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create unique index if not exists integrations_user_kind_idx on integrations(user_id, kind, label);

-- updated_at triggers
create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger users_updated before update on users for each row execute function set_updated_at();
create trigger subscriptions_updated before update on subscriptions for each row execute function set_updated_at();
create trigger skills_updated before update on skills for each row execute function set_updated_at();
create trigger integrations_updated before update on integrations for each row execute function set_updated_at();

-- helper view: is this user's subscription currently entitling them to Pro?
create or replace view active_users as
select
  u.id as user_id,
  u.email,
  s.tier,
  s.current_period_end,
  s.status
from users u
join subscriptions s on s.user_id = u.id
where s.status in ('active','trialing');
