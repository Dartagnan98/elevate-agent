-- 0005_password_resets.sql
-- Tokenized password-reset flow. Token is sha256-hashed at rest;
-- the plaintext lives only in the URL emailed/sent to the user.

create table if not exists public.password_reset_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  token_hash text not null unique,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  ip_addr text,
  user_agent text
);

create index if not exists idx_password_reset_tokens_user on public.password_reset_tokens(user_id);
create index if not exists idx_password_reset_tokens_expires on public.password_reset_tokens(expires_at);
