-- Lock public Supabase access to the server-side service role.
--
-- The HQ backend is the only database client: browser/CLI users authenticate
-- with the Next.js API, and the API talks to Supabase with the service-role
-- key. Keep anon/authenticated unable to read/write tables or execute RPCs
-- even if a key is accidentally exposed in a client context.

revoke create on schema public from public;
revoke usage on schema public from anon, authenticated;
grant usage on schema public to service_role;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

alter default privileges in schema public
  revoke all on tables from anon, authenticated;
alter default privileges in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges in schema public
  revoke execute on functions from public, anon, authenticated;

-- Existing rate-limit RPC is called only by the backend service-role client.
grant execute on function public.check_rate_limit(text, integer, integer) to service_role;

-- Avoid search_path hijacking warnings for app-owned plpgsql functions.
alter function public.check_rate_limit(text, integer, integer)
  set search_path = public, pg_temp;

alter function public.lower_email()
  set search_path = public, pg_temp;

alter function public.touch_updated_at()
  set search_path = public, pg_temp;
