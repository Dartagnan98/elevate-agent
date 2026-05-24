-- Elevate HQ: orgs, memberships, invitations, search support
-- Multi-tenant. Users belong to N orgs via memberships with per-org roles.
-- Entitlements + billing move to org level. Personal user.entitlements remains
-- as override/godmode (mainly for platform owner).

-- enable trigram search early (used by indexes below)
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------------
-- enums
-- ---------------------------------------------------------------------------
create type org_role as enum ('owner', 'admin', 'member');
create type invite_status as enum ('pending', 'accepted', 'revoked', 'expired');

-- ---------------------------------------------------------------------------
-- organizations
-- ---------------------------------------------------------------------------
create table organizations (
  id                    uuid primary key default gen_random_uuid(),
  slug                  text unique not null,
  name                  text not null,
  stripe_customer       text unique,
  tier                  user_tier not null default 'pro',
  status                user_status not null default 'active',
  current_period_end    timestamptz,
  entitlements          text[] not null default '{}',
  seat_limit            integer not null default 1,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index orgs_slug_idx on organizations (slug);
create index orgs_stripe_customer_idx on organizations (stripe_customer) where stripe_customer is not null;
create index orgs_name_trgm_idx on organizations using gin (name gin_trgm_ops);

create trigger orgs_touch_updated_at
  before update on organizations
  for each row execute function touch_updated_at();

-- ---------------------------------------------------------------------------
-- memberships
-- ---------------------------------------------------------------------------
create table memberships (
  id                    uuid primary key default gen_random_uuid(),
  org_id                uuid not null references organizations(id) on delete cascade,
  user_id               uuid not null references users(id) on delete cascade,
  role                  org_role not null default 'member',
  created_at            timestamptz not null default now(),
  unique (org_id, user_id)
);

create index memberships_user_idx on memberships (user_id);
create index memberships_org_idx on memberships (org_id);

-- ---------------------------------------------------------------------------
-- invitations
-- one row per pending invite. token is sha256-hashed before storage.
-- ---------------------------------------------------------------------------
create table invitations (
  id                    uuid primary key default gen_random_uuid(),
  org_id                uuid not null references organizations(id) on delete cascade,
  email                 text not null,
  role                  org_role not null default 'member',
  token_hash            text unique not null,
  status                invite_status not null default 'pending',
  invited_by            uuid references users(id) on delete set null,
  expires_at            timestamptz not null default (now() + interval '14 days'),
  accepted_at           timestamptz,
  accepted_user_id      uuid references users(id) on delete set null,
  created_at            timestamptz not null default now()
);

create index invitations_org_idx on invitations (org_id);
create index invitations_email_idx on invitations (lower(email));
create index invitations_status_idx on invitations (status);

-- normalize email
create function lower_invite_email() returns trigger as $$
begin
  new.email := lower(new.email);
  return new;
end;
$$ language plpgsql;

create trigger invitations_lower_email_trg
  before insert or update on invitations
  for each row execute function lower_invite_email();

-- ---------------------------------------------------------------------------
-- add org_id to licenses, skill_invocations, audit_log
-- ---------------------------------------------------------------------------
alter table licenses        add column org_id uuid references organizations(id) on delete set null;
alter table skill_invocations add column org_id uuid references organizations(id) on delete set null;
alter table audit_log       add column org_id uuid references organizations(id) on delete set null;

create index licenses_org_idx on licenses (org_id) where org_id is not null;
create index skill_invocations_org_idx on skill_invocations (org_id, invoked_at desc) where org_id is not null;
create index audit_log_org_idx on audit_log (org_id, created_at desc) where org_id is not null;

-- ---------------------------------------------------------------------------
-- search support: trigram indexes on user email
-- ---------------------------------------------------------------------------
create index users_email_trgm_idx on users using gin (email gin_trgm_ops);
create index audit_log_action_idx on audit_log (action, created_at desc);

-- ---------------------------------------------------------------------------
-- rls (deny by default for anon/auth; service_role bypasses)
-- ---------------------------------------------------------------------------
alter table organizations enable row level security;
alter table memberships enable row level security;
alter table invitations enable row level security;
