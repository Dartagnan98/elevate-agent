// Supabase-backed store. Public function signatures mirror the old
// file-backed store, but every call is now async. Routes have been
// updated to await them.

import { supabase } from "./supabase";

export type StoreUser = {
  id: string;
  email: string;
  password_hash: string;
  stripe_customer: string | null;
  tier: "pro" | "builder";
  status: "active" | "trialing" | "inactive" | "canceled" | "past_due";
  current_period_end: string | null;
  entitlements: string[];
  blocked_entitlements: string[];
  role: "owner" | "admin" | "user";
  is_developer: boolean;
  created_at: string;
  updated_at: string;
};

// Canonical full entitlement set — used when is_developer = true to grant
// universal access without manual per-user toggling.
export const ALL_ENTITLEMENTS = [
  "real_estate_sales",
  "real_estate_marketing",
  "real_estate_admin",
  "real_estate_cma",
] as const;

export type StoreLicense = {
  id: string;
  user_id: string;
  device_label: string | null;
  refresh_token_hash: string;
  revoked: boolean;
  last_used_at: string | null;
  created_at: string;
};

export type StoreSkill = {
  name: string;
  version: number;
  tier_required: "pro" | "builder";
  manifest: Record<string, unknown>;
  body: string;
  enabled: boolean;
  updated_at: string;
  created_at: string;
};

type SkillInvocation = {
  user_id: string;
  skill_name: string;
  args_hash: string | null;
  ip_address: string | null;
  user_agent: string | null;
};

const ACTIVE_STATUSES = ["active", "trialing"];

// ---------------------------------------------------------------------------
// users
// ---------------------------------------------------------------------------
export async function findUserByEmail(email: string): Promise<StoreUser | null> {
  const { data, error } = await supabase()
    .from("users")
    .select("*")
    .eq("email", email.toLowerCase())
    .maybeSingle();
  if (error) throw error;
  return (data as StoreUser) ?? null;
}

export async function findActiveUser(userId: string): Promise<StoreUser | null> {
  const { data, error } = await supabase()
    .from("users")
    .select("*")
    .eq("id", userId)
    .in("status", ACTIVE_STATUSES)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreUser) ?? null;
}

export async function findUserByStripeCustomer(
  stripeCustomer: string,
): Promise<StoreUser | null> {
  const { data, error } = await supabase()
    .from("users")
    .select("*")
    .eq("stripe_customer", stripeCustomer)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreUser) ?? null;
}

export async function updateUserSubscription(
  userId: string,
  values: Partial<
    Pick<StoreUser, "status" | "tier" | "current_period_end" | "stripe_customer">
  >,
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update(values)
    .eq("id", userId);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// licenses
// ---------------------------------------------------------------------------
export async function createLicense(
  userId: string,
  refreshTokenHash: string,
  deviceLabel?: string | null,
): Promise<StoreLicense> {
  const { data, error } = await supabase()
    .from("licenses")
    .insert({
      user_id: userId,
      refresh_token_hash: refreshTokenHash,
      device_label: deviceLabel ?? null,
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as StoreLicense;
}

export async function findLicenseByRefreshHash(
  hash: string,
): Promise<StoreLicense | null> {
  const { data, error } = await supabase()
    .from("licenses")
    .select("*")
    .eq("refresh_token_hash", hash)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreLicense) ?? null;
}

export async function findLicenseById(
  licenseId: string,
): Promise<StoreLicense | null> {
  const { data, error } = await supabase()
    .from("licenses")
    .select("*")
    .eq("id", licenseId)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreLicense) ?? null;
}

export async function rotateLicenseRefreshToken(
  licenseId: string,
  nextHash: string,
): Promise<void> {
  const { error } = await supabase()
    .from("licenses")
    .update({
      refresh_token_hash: nextHash,
      last_used_at: new Date().toISOString(),
    })
    .eq("id", licenseId);
  if (error) throw error;
}

export async function touchLicense(licenseId: string): Promise<void> {
  const { error } = await supabase()
    .from("licenses")
    .update({ last_used_at: new Date().toISOString() })
    .eq("id", licenseId);
  if (error) throw error;
}

export async function revokeLicense(licenseId: string): Promise<void> {
  const { error } = await supabase()
    .from("licenses")
    .update({ revoked: true })
    .eq("id", licenseId);
  if (error) throw error;
}

export async function revokeLicensesForUser(userId: string): Promise<void> {
  const { error } = await supabase()
    .from("licenses")
    .update({ revoked: true })
    .eq("user_id", userId);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// skills
// ---------------------------------------------------------------------------
export async function listEnabledSkills(): Promise<StoreSkill[]> {
  const { data, error } = await supabase()
    .from("skills")
    .select("*")
    .eq("enabled", true)
    .order("name", { ascending: true });
  if (error) throw error;
  return (data ?? []) as StoreSkill[];
}

export async function getEnabledSkill(name: string): Promise<StoreSkill | null> {
  const { data, error } = await supabase()
    .from("skills")
    .select("*")
    .eq("name", name)
    .eq("enabled", true)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreSkill) ?? null;
}

// ---------------------------------------------------------------------------
// audit
// ---------------------------------------------------------------------------
export async function logSkillInvocation(
  input: SkillInvocation,
): Promise<void> {
  const { error } = await supabase().from("skill_invocations").insert(input);
  if (error) throw error;
}

export async function logAdminAction(input: {
  actor_user_id: string | null;
  target_user_id: string | null;
  action: string;
  org_id?: string | null;
  payload?: Record<string, unknown>;
}): Promise<void> {
  const { error } = await supabase().from("audit_log").insert({
    actor_user_id: input.actor_user_id,
    target_user_id: input.target_user_id,
    org_id: input.org_id ?? null,
    action: input.action,
    payload: input.payload ?? {},
  });
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// admin (entitlement control)
// ---------------------------------------------------------------------------
export async function listAllUsers(): Promise<StoreUser[]> {
  const { data, error } = await supabase()
    .from("users")
    .select("*")
    .order("created_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as StoreUser[];
}

export async function updateUserEntitlements(
  userId: string,
  entitlements: string[],
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ entitlements })
    .eq("id", userId);
  if (error) throw error;
}

export async function updateUserBlockedEntitlements(
  userId: string,
  blocked_entitlements: string[],
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ blocked_entitlements })
    .eq("id", userId);
  if (error) throw error;
}

export async function updateUserTier(
  userId: string,
  tier: "pro" | "builder",
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ tier })
    .eq("id", userId);
  if (error) throw error;
}

export async function updateUserStatus(
  userId: string,
  status: StoreUser["status"],
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ status })
    .eq("id", userId);
  if (error) throw error;
}

export async function setUserDeveloperFlag(
  userId: string,
  is_developer: boolean,
): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ is_developer })
    .eq("id", userId);
  if (error) throw error;
}

export async function findUserById(userId: string): Promise<StoreUser | null> {
  const { data, error } = await supabase()
    .from("users")
    .select("*")
    .eq("id", userId)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreUser) ?? null;
}

export async function createUser(input: {
  email: string;
  password_hash: string;
  tier?: StoreUser["tier"];
  status?: StoreUser["status"];
  role?: StoreUser["role"];
  entitlements?: string[];
}): Promise<StoreUser> {
  const { data, error } = await supabase()
    .from("users")
    .insert({
      email: input.email.toLowerCase(),
      password_hash: input.password_hash,
      tier: input.tier ?? "pro",
      status: input.status ?? "active",
      role: input.role ?? "user",
      entitlements: input.entitlements ?? [],
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as StoreUser;
}

// ---------------------------------------------------------------------------
// organizations
// ---------------------------------------------------------------------------
export type StoreOrg = {
  id: string;
  slug: string;
  name: string;
  stripe_customer: string | null;
  tier: "pro" | "builder";
  status: StoreUser["status"];
  current_period_end: string | null;
  entitlements: string[];
  seat_limit: number;
  created_at: string;
  updated_at: string;
};

export type StoreMembership = {
  id: string;
  org_id: string;
  user_id: string;
  role: "owner" | "admin" | "member";
  created_at: string;
};

export type StoreInvitation = {
  id: string;
  org_id: string;
  email: string;
  role: "owner" | "admin" | "member";
  token_hash: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  invited_by: string | null;
  expires_at: string;
  accepted_at: string | null;
  accepted_user_id: string | null;
  created_at: string;
};

export async function listOrgs(): Promise<StoreOrg[]> {
  const { data, error } = await supabase()
    .from("organizations")
    .select("*")
    .order("created_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as StoreOrg[];
}

export async function findOrgById(id: string): Promise<StoreOrg | null> {
  const { data, error } = await supabase()
    .from("organizations")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreOrg) ?? null;
}

export async function findOrgBySlug(slug: string): Promise<StoreOrg | null> {
  const { data, error } = await supabase()
    .from("organizations")
    .select("*")
    .eq("slug", slug)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreOrg) ?? null;
}

export async function createOrg(input: {
  slug: string;
  name: string;
  tier?: StoreOrg["tier"];
  status?: StoreOrg["status"];
  entitlements?: string[];
  seat_limit?: number;
}): Promise<StoreOrg> {
  const { data, error } = await supabase()
    .from("organizations")
    .insert({
      slug: input.slug,
      name: input.name,
      tier: input.tier ?? "pro",
      status: input.status ?? "active",
      entitlements: input.entitlements ?? [],
      seat_limit: input.seat_limit ?? 1,
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as StoreOrg;
}

export async function updateOrg(
  id: string,
  values: Partial<
    Pick<
      StoreOrg,
      "name" | "slug" | "tier" | "status" | "entitlements" | "seat_limit" | "current_period_end" | "stripe_customer"
    >
  >,
): Promise<void> {
  const { error } = await supabase()
    .from("organizations")
    .update(values)
    .eq("id", id);
  if (error) throw error;
}

export async function deleteOrg(id: string): Promise<void> {
  const { error } = await supabase().from("organizations").delete().eq("id", id);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// memberships
// ---------------------------------------------------------------------------
export async function listMembershipsForUser(
  userId: string,
): Promise<Array<StoreMembership & { organization: StoreOrg }>> {
  const { data, error } = await supabase()
    .from("memberships")
    .select("*, organization:organizations(*)")
    .eq("user_id", userId);
  if (error) throw error;
  return (data ?? []) as Array<StoreMembership & { organization: StoreOrg }>;
}

export async function listMembershipsForOrg(
  orgId: string,
): Promise<Array<StoreMembership & { user: StoreUser }>> {
  const { data, error } = await supabase()
    .from("memberships")
    .select("*, user:users(*)")
    .eq("org_id", orgId)
    .order("created_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as Array<StoreMembership & { user: StoreUser }>;
}

export async function getMembership(
  orgId: string,
  userId: string,
): Promise<StoreMembership | null> {
  const { data, error } = await supabase()
    .from("memberships")
    .select("*")
    .eq("org_id", orgId)
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreMembership) ?? null;
}

export async function addMembership(input: {
  org_id: string;
  user_id: string;
  role?: StoreMembership["role"];
}): Promise<StoreMembership> {
  const { data, error } = await supabase()
    .from("memberships")
    .insert({
      org_id: input.org_id,
      user_id: input.user_id,
      role: input.role ?? "member",
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as StoreMembership;
}

export async function updateMembershipRole(
  orgId: string,
  userId: string,
  role: StoreMembership["role"],
): Promise<void> {
  const { error } = await supabase()
    .from("memberships")
    .update({ role })
    .eq("org_id", orgId)
    .eq("user_id", userId);
  if (error) throw error;
}

export async function removeMembership(orgId: string, userId: string): Promise<void> {
  const { error } = await supabase()
    .from("memberships")
    .delete()
    .eq("org_id", orgId)
    .eq("user_id", userId);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// invitations
// ---------------------------------------------------------------------------
export async function createInvitation(input: {
  org_id: string;
  email: string;
  role: StoreInvitation["role"];
  token_hash: string;
  invited_by: string | null;
}): Promise<StoreInvitation> {
  const { data, error } = await supabase()
    .from("invitations")
    .insert(input)
    .select("*")
    .single();
  if (error) throw error;
  return data as StoreInvitation;
}

export async function findInvitationByTokenHash(
  hash: string,
): Promise<StoreInvitation | null> {
  const { data, error } = await supabase()
    .from("invitations")
    .select("*")
    .eq("token_hash", hash)
    .maybeSingle();
  if (error) throw error;
  return (data as StoreInvitation) ?? null;
}

export async function listPendingInvitationsForOrg(
  orgId: string,
): Promise<StoreInvitation[]> {
  const { data, error } = await supabase()
    .from("invitations")
    .select("*")
    .eq("org_id", orgId)
    .eq("status", "pending")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as StoreInvitation[];
}

export async function acceptInvitation(
  invitationId: string,
  acceptedUserId: string,
): Promise<void> {
  const { error } = await supabase()
    .from("invitations")
    .update({
      status: "accepted",
      accepted_at: new Date().toISOString(),
      accepted_user_id: acceptedUserId,
    })
    .eq("id", invitationId);
  if (error) throw error;
}

export async function revokeInvitation(invitationId: string): Promise<void> {
  const { error } = await supabase()
    .from("invitations")
    .update({ status: "revoked" })
    .eq("id", invitationId);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// search
// ---------------------------------------------------------------------------
export type SearchResult = {
  users: Array<Pick<StoreUser, "id" | "email" | "tier" | "role" | "status">>;
  orgs: Array<Pick<StoreOrg, "id" | "slug" | "name" | "tier" | "status">>;
  licenses: Array<{
    id: string;
    user_id: string;
    org_id: string | null;
    device_label: string | null;
    revoked: boolean;
    last_used_at: string | null;
    user_email: string | null;
  }>;
  audit: Array<{
    id: string;
    action: string;
    created_at: string;
    actor_user_id: string | null;
    target_user_id: string | null;
    org_id: string | null;
    payload: Record<string, unknown>;
  }>;
};

export async function searchAll(query: string, limit = 10): Promise<SearchResult> {
  const q = query.trim();
  if (!q) {
    return { users: [], orgs: [], licenses: [], audit: [] };
  }
  const sb = supabase();
  const pattern = `%${q.toLowerCase()}%`;

  const [usersRes, orgsRes, licensesRes, auditRes] = await Promise.all([
    sb
      .from("users")
      .select("id, email, tier, role, status")
      .ilike("email", pattern)
      .limit(limit),
    sb
      .from("organizations")
      .select("id, slug, name, tier, status")
      .or(`name.ilike.${pattern},slug.ilike.${pattern}`)
      .limit(limit),
    sb
      .from("licenses")
      .select("id, user_id, org_id, device_label, revoked, last_used_at, user:users(email)")
      .ilike("device_label", pattern)
      .limit(limit),
    sb
      .from("audit_log")
      .select("id, action, created_at, actor_user_id, target_user_id, org_id, payload")
      .ilike("action", pattern)
      .order("created_at", { ascending: false })
      .limit(limit),
  ]);

  if (usersRes.error) throw usersRes.error;
  if (orgsRes.error) throw orgsRes.error;
  if (licensesRes.error) throw licensesRes.error;
  if (auditRes.error) throw auditRes.error;

  return {
    users: (usersRes.data ?? []) as SearchResult["users"],
    orgs: (orgsRes.data ?? []) as SearchResult["orgs"],
    licenses: (licensesRes.data ?? []).map((row: Record<string, unknown>) => ({
      id: row.id as string,
      user_id: row.user_id as string,
      org_id: (row.org_id as string | null) ?? null,
      device_label: (row.device_label as string | null) ?? null,
      revoked: row.revoked as boolean,
      last_used_at: (row.last_used_at as string | null) ?? null,
      user_email:
        (row.user as { email?: string } | null)?.email ?? null,
    })),
    audit: (auditRes.data ?? []) as SearchResult["audit"],
  };
}

// ---------------------------------------------------------------------------
// effective entitlements / tier
// union(user.entitlements, all active-org.entitlements). tier is max rank.
// ---------------------------------------------------------------------------
const TIER_RANK: Record<string, number> = { pro: 1, builder: 2 };

export async function effectiveAccess(userId: string): Promise<{
  tier: "pro" | "builder";
  entitlements: string[];
  orgs: Array<{ id: string; slug: string; name: string; role: StoreMembership["role"] }>;
}> {
  const user = await findUserById(userId);
  if (!user) return { tier: "pro", entitlements: [], orgs: [] };

  const memberships = await listMembershipsForUser(userId);
  const activeOrgs = memberships.filter(
    (m) => m.organization && ["active", "trialing"].includes(m.organization.status),
  );

  // Developer accounts bypass entitlement gating entirely. Always builder tier,
  // full entitlement set + union of any explicit org entitlements (for testing).
  if (user.is_developer) {
    const ents = new Set<string>(ALL_ENTITLEMENTS);
    for (const e of user.entitlements || []) ents.add(e);
    for (const m of activeOrgs) for (const e of m.organization.entitlements || []) ents.add(e);
    return {
      tier: "builder",
      entitlements: Array.from(ents),
      orgs: activeOrgs.map((m) => ({
        id: m.organization.id,
        slug: m.organization.slug,
        name: m.organization.name,
        role: m.role,
      })),
    };
  }

  let tier: "pro" | "builder" = user.tier;
  let tierRank = TIER_RANK[tier] ?? 1;
  const entitlements = new Set<string>(user.entitlements || []);

  for (const m of activeOrgs) {
    const orgRank = TIER_RANK[m.organization.tier] ?? 1;
    if (orgRank > tierRank) {
      tier = m.organization.tier;
      tierRank = orgRank;
    }
    for (const e of m.organization.entitlements || []) entitlements.add(e);
  }

  // Subtract per-user blocks. Lets an admin revoke a pack from a single user
  // even when their org grants it. Block list does NOT apply to is_developer
  // accounts above (those bypass everything).
  for (const blocked of user.blocked_entitlements || []) {
    entitlements.delete(blocked);
  }

  return {
    tier,
    entitlements: Array.from(entitlements),
    orgs: activeOrgs.map((m) => ({
      id: m.organization.id,
      slug: m.organization.slug,
      name: m.organization.name,
      role: m.role,
    })),
  };
}

// ============================================================================
// Device grants (RFC 8628 device-authorization flow)
// ============================================================================
export type DeviceGrantStatus = "pending" | "approved" | "denied" | "expired" | "claimed";

export type DeviceGrant = {
  id: string;
  user_code: string;
  device_code_hash: string;
  user_id: string | null;
  license_id: string | null;
  status: DeviceGrantStatus;
  device_label: string | null;
  ip_addr: string | null;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  approved_at: string | null;
  claimed_at: string | null;
  last_polled_at: string | null;
};

export async function createDeviceGrant(input: {
  user_code: string;
  device_code_hash: string;
  device_label: string | null;
  ip_addr: string | null;
  user_agent: string | null;
  expires_at: Date;
}): Promise<DeviceGrant> {
  const { data, error } = await supabase()
    .from("device_grants")
    .insert({
      user_code: input.user_code,
      device_code_hash: input.device_code_hash,
      device_label: input.device_label,
      ip_addr: input.ip_addr,
      user_agent: input.user_agent,
      expires_at: input.expires_at.toISOString(),
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as DeviceGrant;
}

export async function findDeviceGrantByUserCode(code: string): Promise<DeviceGrant | null> {
  const { data, error } = await supabase()
    .from("device_grants")
    .select("*")
    .eq("user_code", code.toUpperCase())
    .maybeSingle();
  if (error) throw error;
  return (data as DeviceGrant) ?? null;
}

export async function findDeviceGrantByDeviceCodeHash(hash: string): Promise<DeviceGrant | null> {
  const { data, error } = await supabase()
    .from("device_grants")
    .select("*")
    .eq("device_code_hash", hash)
    .maybeSingle();
  if (error) throw error;
  return (data as DeviceGrant) ?? null;
}

export async function touchDeviceGrantPoll(id: string): Promise<void> {
  await supabase()
    .from("device_grants")
    .update({ last_polled_at: new Date().toISOString() })
    .eq("id", id);
}

export async function approveDeviceGrant(
  id: string,
  userId: string,
  licenseId: string,
): Promise<void> {
  const { error } = await supabase()
    .from("device_grants")
    .update({
      status: "approved",
      user_id: userId,
      license_id: licenseId,
      approved_at: new Date().toISOString(),
    })
    .eq("id", id);
  if (error) throw error;
}

export async function denyDeviceGrant(id: string, userId: string): Promise<void> {
  const { error } = await supabase()
    .from("device_grants")
    .update({ status: "denied", user_id: userId })
    .eq("id", id);
  if (error) throw error;
}

export async function markDeviceGrantClaimed(id: string): Promise<void> {
  const { error } = await supabase()
    .from("device_grants")
    .update({ status: "claimed", claimed_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw error;
}

export async function expireStaleDeviceGrants(): Promise<void> {
  await supabase()
    .from("device_grants")
    .update({ status: "expired" })
    .lt("expires_at", new Date().toISOString())
    .in("status", ["pending", "approved"]);
}

// ============================================================================
// User-facing license + profile helpers (for /api/me/* self-service routes)
// ============================================================================
export async function listLicensesForUser(userId: string): Promise<StoreLicense[]> {
  const { data, error } = await supabase()
    .from("licenses")
    .select("*")
    .eq("user_id", userId)
    .eq("revoked", false)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data || []) as StoreLicense[];
}

export async function revokeLicenseForUser(licenseId: string, userId: string): Promise<boolean> {
  // Tenant-safe: only revoke if it belongs to the caller.
  const { data, error } = await supabase()
    .from("licenses")
    .update({ revoked: true })
    .eq("id", licenseId)
    .eq("user_id", userId)
    .select("id");
  if (error) throw error;
  return (data?.length ?? 0) > 0;
}

export async function revokeAllLicensesExcept(userId: string, keepLicenseId: string): Promise<void> {
  const { error } = await supabase()
    .from("licenses")
    .update({ revoked: true })
    .eq("user_id", userId)
    .neq("id", keepLicenseId);
  if (error) throw error;
}

export async function updateUserEmail(userId: string, email: string): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ email: email.toLowerCase().trim() })
    .eq("id", userId);
  if (error) throw error;
}

export async function updateUserPasswordHash(userId: string, hash: string): Promise<void> {
  const { error } = await supabase()
    .from("users")
    .update({ password_hash: hash })
    .eq("id", userId);
  if (error) throw error;
}

// ---------------------------------------------------------------------------
// password reset tokens
// ---------------------------------------------------------------------------
export type PasswordResetToken = {
  id: string;
  user_id: string;
  token_hash: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  ip_addr: string | null;
  user_agent: string | null;
};

export async function createPasswordResetToken(input: {
  user_id: string;
  token_hash: string;
  expires_at: string;
  ip_addr?: string | null;
  user_agent?: string | null;
}): Promise<PasswordResetToken> {
  const { data, error } = await supabase()
    .from("password_reset_tokens")
    .insert({
      user_id: input.user_id,
      token_hash: input.token_hash,
      expires_at: input.expires_at,
      ip_addr: input.ip_addr ?? null,
      user_agent: input.user_agent ?? null,
    })
    .select("*")
    .single();
  if (error) throw error;
  return data as PasswordResetToken;
}

export async function findPasswordResetByHash(
  hash: string,
): Promise<PasswordResetToken | null> {
  const { data, error } = await supabase()
    .from("password_reset_tokens")
    .select("*")
    .eq("token_hash", hash)
    .maybeSingle();
  if (error) throw error;
  return (data as PasswordResetToken) ?? null;
}

export async function consumePasswordReset(id: string): Promise<void> {
  const { error } = await supabase()
    .from("password_reset_tokens")
    .update({ consumed_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw error;
}
