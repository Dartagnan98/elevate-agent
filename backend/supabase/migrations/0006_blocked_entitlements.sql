-- 0006: per-user entitlement block list
--
-- Today effectiveAccess(user) = union(user.entitlements, org.entitlements).
-- That means an admin can never "subtract" a pack from a user whose org grants
-- it. Add a blocked_entitlements column so the admin UI can mask a pack off
-- for a specific user even when their org grants it.
--
-- Final effectiveAccess becomes:
--   (union(user.entitlements, org.entitlements)) - user.blocked_entitlements
--
-- is_developer (ALL_ENTITLEMENTS) still wins. Block list does not apply to dev
-- accounts.

alter table users
  add column if not exists blocked_entitlements text[] not null default '{}';

comment on column users.blocked_entitlements is
  'Per-user entitlement mask. Subtracted from union(user, org) in effectiveAccess. Lets an admin revoke a pack from a single user without touching org grants.';
