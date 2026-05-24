-- Developer flag: bypass all entitlement gating, always builder tier
alter table public.users
  add column if not exists is_developer boolean not null default false;

create index if not exists idx_users_is_developer on public.users(is_developer) where is_developer = true;
