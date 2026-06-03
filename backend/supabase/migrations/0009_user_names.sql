-- The realtor's name, collected at Create account (open self-serve signup).
-- Nullable: pre-existing accounts have no name; new sign-ups populate both.
alter table public.users add column if not exists first_name text;
alter table public.users add column if not exists last_name text;
