-- Device-grant flow for linking the web session to local CLI / desktop app.
-- Mirrors OAuth 2.0 device-authorization grant (RFC 8628).

do $$ begin
  create type device_grant_status as enum ('pending', 'approved', 'denied', 'expired', 'claimed');
exception when duplicate_object then null;
end $$;

create table if not exists public.device_grants (
  id uuid primary key default gen_random_uuid(),
  user_code text not null unique,
  device_code_hash text not null unique,
  user_id uuid references public.users(id) on delete cascade,
  license_id uuid references public.licenses(id) on delete set null,
  status device_grant_status not null default 'pending',
  device_label text,
  ip_addr text,
  user_agent text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  approved_at timestamptz,
  claimed_at timestamptz,
  last_polled_at timestamptz,
  refresh_token_plain text
);

create index if not exists idx_device_grants_user_code on public.device_grants(user_code);
create index if not exists idx_device_grants_status on public.device_grants(status) where status = 'pending';
create index if not exists idx_device_grants_expires on public.device_grants(expires_at) where status in ('pending', 'approved');
