-- 0007_login_codes.sql
-- Passwordless email login: one-time 6-digit codes. The code is sha256-hashed
-- at rest; the plaintext lives only in the email sent to the user. `attempts`
-- caps brute-force guessing per issued code.

create table if not exists public.login_codes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  code_hash text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  attempts int not null default 0,
  ip_addr text,
  user_agent text
);

create index if not exists idx_login_codes_user on public.login_codes(user_id);
create index if not exists idx_login_codes_expires on public.login_codes(expires_at);
