-- 0008_rate_limits.sql
-- App-layer rate limiting for auth endpoints (brute-force + email-bomb /
-- Mailjet-cost protection). Fixed-window counter keyed by an opaque string
-- like "login:ip:1.2.3.4" or "login-code-req:email:foo@bar.com".
--
-- check_rate_limit() does the read-reset-increment atomically in a single
-- statement (UPSERT with a conditional window reset) so concurrent requests
-- can't slip past the cap via a read-modify-write race.

create table if not exists public.rate_limits (
  key text primary key,
  count int not null default 0,
  window_start timestamptz not null default now()
);

create index if not exists idx_rate_limits_window on public.rate_limits(window_start);

create or replace function public.check_rate_limit(
  p_key text,
  p_max int,
  p_window_seconds int
) returns table(allowed boolean, remaining int, retry_after int)
language plpgsql
as $$
declare
  v_now timestamptz := now();
  v_count int;
  v_start timestamptz;
begin
  insert into public.rate_limits(key, count, window_start)
    values (p_key, 1, v_now)
  on conflict (key) do update
    set count = case
          when public.rate_limits.window_start < v_now - make_interval(secs => p_window_seconds)
            then 1
          else public.rate_limits.count + 1
        end,
        window_start = case
          when public.rate_limits.window_start < v_now - make_interval(secs => p_window_seconds)
            then v_now
          else public.rate_limits.window_start
        end
  returning public.rate_limits.count, public.rate_limits.window_start
  into v_count, v_start;

  if v_count <= p_max then
    return query select true, (p_max - v_count), 0;
  else
    return query select false, 0,
      ceil(extract(epoch from (v_start + make_interval(secs => p_window_seconds) - v_now)))::int;
  end if;
end;
$$;
