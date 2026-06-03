"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Avatar,
  Badge,
  Button,
  Card,
  ErrorBanner,
  Input,
  Label,
  LoadingRow,
  PageHeader,
  Select,
  StatusDot,
} from "@/components/ui";

type User = {
  id: string;
  email: string;
  tier: "pro" | "builder";
  status: string;
  role: "owner" | "admin" | "user";
  is_developer: boolean;
  first_name: string | null;
  last_name: string | null;
  entitlements: string[];
  blocked_entitlements: string[];
  stripe_customer: string | null;
  current_period_end: string | null;
  created_at: string;
};

type SessionRow = {
  id: string;
  device_label: string | null;
  created_at: string;
  last_used_at: string | null;
};

type MembershipRole = "owner" | "admin" | "member";

type Org = {
  id: string;
  slug: string;
  name: string;
  tier: string;
  status: string;
  entitlements: string[];
  seat_limit: number;
};

type OrgDetail = {
  org: Org;
  members: Array<{
    id: string;
    user_id: string;
    role: MembershipRole;
    created_at: string;
    email: string | null;
  }>;
};

const KNOWN_ENTITLEMENTS: Array<{ key: string; label: string }> = [
  { key: "real_estate_sales", label: "Sales" },
  { key: "real_estate_marketing", label: "Marketing" },
  { key: "real_estate_admin", label: "Admin" },
  { key: "real_estate_cma", label: "CMA" },
];

export default function AdminUsers() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgDetails, setOrgDetails] = useState<Record<string, OrgDetail>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [sessionsByUser, setSessionsByUser] = useState<Record<string, SessionRow[]>>({});
  const [sessionsLoading, setSessionsLoading] = useState<Record<string, boolean>>({});
  const [expandedSessions, setExpandedSessions] = useState<Record<string, boolean>>({});
  // Invite / provision a member into an org. Wires POST /members, which creates
  // an account-by-invitation (invite-only model) and returns a shareable accept
  // link. An already-existing email is added to the team directly.
  const [inviteOrgId, setInviteOrgId] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<MembershipRole>("member");
  const [inviting, setInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState<
    { orgId: string; email: string; url?: string; emailed?: boolean; added?: boolean } | null
  >(null);
  const [copied, setCopied] = useState(false);

  function token() {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("elevate_access");
  }

  async function authedFetch(path: string, init?: RequestInit) {
    const t = token();
    if (!t) {
      router.push("/admin/login");
      throw new Error("no token");
    }
    return fetch(path, {
      ...init,
      headers: { ...(init?.headers || {}), authorization: `Bearer ${t}` },
    });
  }

  async function load(silent = false) {
    if (!silent) setLoading(true);
    setErr(null);
    try {
      const [usersRes, orgsRes] = await Promise.all([
        authedFetch("/api/admin/users"),
        authedFetch("/api/admin/orgs"),
      ]);
      if (usersRes.status === 401 || usersRes.status === 403) {
        router.push("/admin/login");
        return;
      }
      const usersData = await usersRes.json();
      const orgsData = await orgsRes.json();
      setUsers(usersData.users);
      setOrgs(orgsData.orgs || []);

      const allOrgs: Org[] = orgsData.orgs || [];
      const detailMap: Record<string, OrgDetail> = {};
      const details = await Promise.all(
        allOrgs.map((o) => authedFetch(`/api/admin/orgs/${o.id}`).then((r) => r.json())),
      );
      for (const d of details) {
        if (d?.org?.id) detailMap[d.org.id] = d as OrgDetail;
      }
      setOrgDetails(detailMap);
    } catch (e: unknown) {
      if (!silent) setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Surface new sign-ups in near-real-time: poll in the background + refetch
    // on focus, so an account created in the app appears here without a manual
    // reload. Silent so it doesn't flash the loading state every few seconds.
    const interval = window.setInterval(() => {
      void load(true);
    }, 5000);
    const onFocus = () => void load(true);
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function update(id: string, body: Record<string, unknown>) {
    setSavingId(id);
    try {
      const res = await authedFetch(`/api/admin/users/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "update failed");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "update failed");
    } finally {
      setSavingId(null);
    }
  }

  async function updateMemberRole(orgId: string, userId: string, role: MembershipRole) {
    setSavingId(userId);
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}/members/${userId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ role }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "role update failed");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "role update failed");
    } finally {
      setSavingId(null);
    }
  }

  async function removeMember(orgId: string, userId: string, email: string | null) {
    if (!confirm(`Remove ${email || "user"} from this team?`)) return;
    setSavingId(userId);
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}/members/${userId}`, {
        method: "DELETE",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "remove failed");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "remove failed");
    } finally {
      setSavingId(null);
    }
  }

  async function inviteMember(orgId: string, e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setInviting(true);
    setInviteResult(null);
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}/members`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: inviteEmail.trim().toLowerCase(), role: inviteRole }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "invite failed");
      setInviteResult({
        orgId,
        email: inviteEmail.trim().toLowerCase(),
        url: data.accept_url,
        emailed: data.emailed,
        added: data.added,
      });
      setInviteEmail("");
      setCopied(false);
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "invite failed");
    } finally {
      setInviting(false);
    }
  }

  async function loadSessions(userId: string) {
    setSessionsLoading((m) => ({ ...m, [userId]: true }));
    try {
      const res = await authedFetch(`/api/admin/users/${userId}/licenses`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "sessions failed");
      setSessionsByUser((m) => ({ ...m, [userId]: data.licenses || [] }));
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "sessions failed");
    } finally {
      setSessionsLoading((m) => ({ ...m, [userId]: false }));
    }
  }

  async function toggleSessions(userId: string) {
    const open = !expandedSessions[userId];
    setExpandedSessions((m) => ({ ...m, [userId]: open }));
    if (open && !sessionsByUser[userId]) {
      await loadSessions(userId);
    }
  }

  async function revokeSession(userId: string, licenseId: string, label: string | null) {
    if (!confirm(`Revoke session "${label || "unlabelled device"}"?`)) return;
    try {
      const res = await authedFetch(
        `/api/admin/users/${userId}/licenses/${licenseId}`,
        { method: "DELETE" },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "revoke failed");
      await loadSessions(userId);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "revoke failed");
    }
  }

  // Which orgs grant a given entitlement to this user via membership.
  function orgGrantsFor(userId: string): Set<string> {
    const grants = new Set<string>();
    for (const o of orgs) {
      const det = orgDetails[o.id];
      if (!det) continue;
      if (!det.members.some((m) => m.user_id === userId)) continue;
      for (const e of o.entitlements || []) grants.add(e);
    }
    return grants;
  }

  function toggleEntitlement(u: User, ent: string) {
    const personal = new Set(u.entitlements || []);
    const blocked = new Set(u.blocked_entitlements || []);
    const orgGrants = orgGrantsFor(u.id);
    const effectiveOn = (personal.has(ent) || orgGrants.has(ent)) && !blocked.has(ent);

    const body: Record<string, unknown> = {};
    if (effectiveOn) {
      if (personal.has(ent)) {
        personal.delete(ent);
        body.entitlements = Array.from(personal);
      }
      if (orgGrants.has(ent)) {
        blocked.add(ent);
        body.blocked_entitlements = Array.from(blocked);
      }
    } else {
      if (blocked.has(ent)) {
        blocked.delete(ent);
        body.blocked_entitlements = Array.from(blocked);
      }
      if (!orgGrants.has(ent) && !personal.has(ent)) {
        personal.add(ent);
        body.entitlements = Array.from(personal);
      }
    }
    if (Object.keys(body).length === 0) return;
    update(u.id, body);
  }

  // Group users by org: every active org becomes a section, with its members
  // listed under the org owner. Users with no membership land in "Unaffiliated".
  const ownedOrgs = orgs;
  const orgMemberIds = new Set<string>();
  for (const o of ownedOrgs) {
    const det = orgDetails[o.id];
    if (!det) continue;
    for (const m of det.members) orgMemberIds.add(m.user_id);
  }
  const unaffiliated = users.filter((u) => !orgMemberIds.has(u.id));

  return (
    <div>
      <PageHeader
        title="Teams"
        subtitle={`${orgs.length} ${orgs.length === 1 ? "team" : "teams"} · ${users.length} ${users.length === 1 ? "user" : "users"}`}
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {loading && <LoadingRow />}

      {/* TEAMS */}
      <div style={{ display: "grid", gap: 20 }}>
        {ownedOrgs.map((o) => {
          const det = orgDetails[o.id];
          if (!det) return null;
          // Sort members: owners first, then admins, then members.
          const rank: Record<MembershipRole, number> = { owner: 0, admin: 1, member: 2 };
          const sortedMembers = [...det.members].sort(
            (a, b) => rank[a.role] - rank[b.role] || (a.email || "").localeCompare(b.email || ""),
          );
          const ownerMember = sortedMembers.find((m) => m.role === "owner");
          const ownerUser = users.find((u) => u.id === ownerMember?.user_id);

          return (
            <Card key={o.id}>
              {/* Org header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 16,
                  marginBottom: 14,
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{o.name}</div>
                    <Badge tone="neutral" size="sm">{o.tier}</Badge>
                    <span style={{ display: "inline-flex", alignItems: "center", fontSize: 12, color: "var(--text-dim)" }}>
                      <StatusDot status={o.status} />{o.status}
                    </span>
                    <Link
                      href={`/admin/orgs/${o.id}`}
                      style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        color: "var(--text-dim)",
                        textDecoration: "none",
                      }}
                    >
                      org settings →
                    </Link>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 12, color: "var(--text-dim)" }}>
                    Owner: <strong>{ownerUser?.email || ownerMember?.email || "—"}</strong>
                    {" · "}
                    {sortedMembers.length} {sortedMembers.length === 1 ? "seat" : "seats"} of {o.seat_limit}
                  </div>
                  {(o.entitlements || []).length > 0 && (
                    <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
                      <span style={{
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        textTransform: "uppercase",
                        letterSpacing: "0.08em",
                        color: "var(--text-faint)",
                        marginRight: 4,
                      }}>
                        team grants:
                      </span>
                      {(o.entitlements || []).map((e) => {
                        const lbl = KNOWN_ENTITLEMENTS.find((k) => k.key === e)?.label || e;
                        return (
                          <span
                            key={e}
                            style={{
                              padding: "2px 8px",
                              borderRadius: 999,
                              border: "1px solid var(--border)",
                              fontSize: 10,
                              fontFamily: "var(--font-mono)",
                              textTransform: "uppercase",
                              letterSpacing: "0.06em",
                              color: "var(--text-dim)",
                            }}
                          >
                            {lbl}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>

              {/* Invite / provision a member */}
              <div style={{ marginBottom: 14 }}>
                {inviteOrgId === o.id ? (
                  <form
                    onSubmit={(e) => inviteMember(o.id, e)}
                    className="stack-mobile"
                    style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}
                  >
                    <div style={{ flex: "1 1 220px" }}>
                      <Label>Invite by email</Label>
                      <Input
                        type="email"
                        placeholder="realtor@brokerage.com"
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        required
                      />
                    </div>
                    <div style={{ flex: "0 0 120px" }}>
                      <Label>Role</Label>
                      <Select
                        value={inviteRole}
                        onChange={(e) => setInviteRole(e.target.value as MembershipRole)}
                      >
                        <option value="member">member</option>
                        <option value="admin">admin</option>
                        <option value="owner">owner</option>
                      </Select>
                    </div>
                    <Button type="submit" variant="primary" size="sm" loading={inviting}>
                      Send invite
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setInviteOrgId(null);
                        setInviteResult(null);
                      }}
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setInviteOrgId(o.id);
                      setInviteResult(null);
                      setInviteEmail("");
                    }}
                  >
                    + Invite member
                  </Button>
                )}

                {inviteResult?.orgId === o.id && (
                  <div
                    style={{
                      marginTop: 10,
                      padding: "10px 12px",
                      borderRadius: 8,
                      border: "1px solid #3a5a44",
                      background: "var(--sage-bg, rgba(60,120,80,0.08))",
                      fontSize: 12,
                    }}
                  >
                    {inviteResult.added ? (
                      <span>
                        ✓ <strong>{inviteResult.email}</strong> already had an account — added to
                        this team.
                      </span>
                    ) : (
                      <div style={{ display: "grid", gap: 6 }}>
                        <span>
                          ✓ Invited <strong>{inviteResult.email}</strong>.{" "}
                          {inviteResult.emailed
                            ? "Invite emailed."
                            : "Email is off — copy the link below and send it."}
                        </span>
                        {inviteResult.url && (
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <Input
                              readOnly
                              value={inviteResult.url}
                              onFocus={(e) => e.currentTarget.select()}
                              style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
                            />
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                navigator.clipboard?.writeText(inviteResult.url!);
                                setCopied(true);
                              }}
                            >
                              {copied ? "Copied" : "Copy"}
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Members */}
              <div style={{ display: "grid", gap: 10 }}>
                {sortedMembers.map((m) => {
                  const u = users.find((x) => x.id === m.user_id);
                  if (!u) return null;
                  return (
                    <MemberRow
                      key={m.user_id}
                      u={u}
                      membershipRole={m.role}
                      orgId={o.id}
                      isSaving={savingId === u.id}
                      orgGrants={orgGrantsFor(u.id)}
                      sessions={sessionsByUser[u.id]}
                      sessionsLoading={!!sessionsLoading[u.id]}
                      sessionsOpen={!!expandedSessions[u.id]}
                      onUpdate={update}
                      onToggleEnt={toggleEntitlement}
                      onChangeRole={(role) => updateMemberRole(o.id, u.id, role)}
                      onRemove={() => removeMember(o.id, u.id, u.email)}
                      onToggleSessions={() => toggleSessions(u.id)}
                      onRevokeSession={(lid, lbl) => revokeSession(u.id, lid, lbl)}
                    />
                  );
                })}
              </div>
            </Card>
          );
        })}
      </div>

      {/* UNAFFILIATED */}
      {unaffiliated.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "var(--text-faint)",
            marginBottom: 10,
          }}>
            Unaffiliated · {unaffiliated.length}
          </div>
          <Card>
            <div style={{ display: "grid", gap: 10 }}>
              {unaffiliated.map((u) => (
                <MemberRow
                  key={u.id}
                  u={u}
                  membershipRole={null}
                  orgId={null}
                  isSaving={savingId === u.id}
                  orgGrants={new Set()}
                  sessions={sessionsByUser[u.id]}
                  sessionsLoading={!!sessionsLoading[u.id]}
                  sessionsOpen={!!expandedSessions[u.id]}
                  onUpdate={update}
                  onToggleEnt={toggleEntitlement}
                  onChangeRole={() => {}}
                  onRemove={() => {}}
                  onToggleSessions={() => toggleSessions(u.id)}
                  onRevokeSession={(lid, lbl) => revokeSession(u.id, lid, lbl)}
                />
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// MemberRow
// ============================================================================
function MemberRow(props: {
  u: User;
  membershipRole: MembershipRole | null;
  orgId: string | null;
  isSaving: boolean;
  orgGrants: Set<string>;
  sessions?: SessionRow[];
  sessionsLoading: boolean;
  sessionsOpen: boolean;
  onUpdate: (id: string, body: Record<string, unknown>) => void;
  onToggleEnt: (u: User, ent: string) => void;
  onChangeRole: (role: MembershipRole) => void;
  onRemove: () => void;
  onToggleSessions: () => void;
  onRevokeSession: (licenseId: string, label: string | null) => void;
}) {
  const {
    u, membershipRole, orgId, isSaving, orgGrants,
    sessions, sessionsLoading, sessionsOpen,
    onUpdate, onToggleEnt, onChangeRole, onRemove,
    onToggleSessions, onRevokeSession,
  } = props;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 14,
        background: "var(--bg-input-solid)",
      }}
    >
      {/* Top row: identity + role + actions */}
      <div
        className="stack-mobile"
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", gap: 12, minWidth: 0, flex: 1 }}>
          <Avatar email={u.email} size={36} />
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {[u.first_name, u.last_name].filter(Boolean).join(" ") || u.email}
              </div>
              {u.is_developer && <Badge tone="dev" size="sm">dev</Badge>}
              {membershipRole && (
                <Badge tone={membershipRole === "owner" ? "amber" : "neutral"} size="sm">
                  {membershipRole}
                </Badge>
              )}
            </div>
            <div style={{
              display: "flex", alignItems: "center", gap: 10, marginTop: 4,
              fontSize: 11, color: "var(--text-dim)", flexWrap: "wrap",
            }}>
              {(u.first_name || u.last_name) && (
                <>
                  <span>{u.email}</span>
                  <span style={{ color: "var(--text-faint)" }}>·</span>
                </>
              )}
              <span style={{ display: "inline-flex", alignItems: "center" }}>
                <StatusDot status={u.status} />{u.status}
              </span>
              <span style={{ color: "var(--text-faint)" }}>·</span>
              <span>tier {u.tier}</span>
            </div>
          </div>
        </div>
        <div
          className="stack-mobile"
          style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}
        >
          {orgId && membershipRole && (
            <Select
              value={membershipRole}
              onChange={(e) => onChangeRole(e.target.value as MembershipRole)}
              disabled={isSaving}
              style={{ width: "auto", padding: "5px 26px 5px 10px", fontSize: 12 }}
              title="Team role: owner, admin, or member"
            >
              <option value="owner">owner</option>
              <option value="admin">admin</option>
              <option value="member">member</option>
            </Select>
          )}
          <Select
            value={u.status}
            onChange={(e) => onUpdate(u.id, { status: e.target.value })}
            disabled={isSaving}
            style={{ width: "auto", padding: "5px 26px 5px 10px", fontSize: 12 }}
          >
            <option value="active">active</option>
            <option value="trialing">trialing</option>
            <option value="past_due">past_due</option>
            <option value="canceled">canceled</option>
            <option value="inactive">inactive</option>
          </Select>
          <Button
            variant={u.is_developer ? "dev" : "ghost"}
            size="sm"
            onClick={() => onUpdate(u.id, { is_developer: !u.is_developer })}
            disabled={isSaving}
            title="developer flag: bypasses entitlement gating, always builder tier"
          >
            {u.is_developer ? "dev on" : "make dev"}
          </Button>
          {orgId && membershipRole !== "owner" && (
            <Button
              variant="danger"
              size="sm"
              onClick={onRemove}
              disabled={isSaving}
              title="Remove from team"
            >
              remove
            </Button>
          )}
        </div>
      </div>

      {/* Entitlements */}
      <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
        <Label>Privileges</Label>
        {u.is_developer && (
          <div
            style={{
              marginBottom: 8,
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid var(--amber-border, #8a6420)",
              background: "var(--amber-bg, rgba(217,160,64,0.08))",
              color: "var(--amber, #d9a040)",
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              lineHeight: 1.5,
            }}
          >
            DEV BYPASS — this user has all packs regardless of toggles. Turn off dev to enforce per-pack.
          </div>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {KNOWN_ENTITLEMENTS.map(({ key, label }) => {
            const personal = u.entitlements.includes(key);
            const blocked = (u.blocked_entitlements || []).includes(key);
            const orgGrant = orgGrants.has(key);
            const devBypass = u.is_developer;
            const effectiveOn = devBypass || ((personal || orgGrant) && !blocked);

            let suffix = "";
            if (blocked) suffix = " · blocked";
            else if (orgGrant && !personal) suffix = " · team";

            const title = devBypass
              ? "Disabled: dev flag grants all packs."
              : blocked
                ? `${label} comes from team but is blocked for this user. Click to restore.`
                : orgGrant && !personal
                  ? `${label} comes from team. Click to block for this user only.`
                  : personal
                    ? `${label} is a personal grant. Click to revoke.`
                    : `Click to grant ${label}.`;

            return (
              <button
                key={key}
                onClick={() => onToggleEnt(u, key)}
                disabled={isSaving || devBypass}
                title={title}
                style={{
                  padding: "4px 10px",
                  borderRadius: 999,
                  border: "1px solid",
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  cursor: isSaving || devBypass ? "not-allowed" : "pointer",
                  opacity: devBypass ? 0.55 : 1,
                  transition: "background 120ms, color 120ms, border-color 120ms",
                  textDecoration: blocked ? "line-through" : "none",
                  background: blocked
                    ? "rgba(180,60,60,0.08)"
                    : effectiveOn
                      ? "var(--sage-bg)"
                      : "var(--bg-input-solid)",
                  color: blocked
                    ? "#c25555"
                    : effectiveOn
                      ? "var(--sage)"
                      : "var(--text-dim)",
                  borderColor: blocked
                    ? "#7a3a3a"
                    : effectiveOn
                      ? "#3a5a44"
                      : "var(--border)",
                }}
              >
                {label}{suffix}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sessions */}
      <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
        <button
          type="button"
          onClick={onToggleSessions}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-dim)",
          }}
        >
          <span style={{
            display: "inline-block",
            width: 10,
            transition: "transform 120ms",
            transform: sessionsOpen ? "rotate(90deg)" : "rotate(0deg)",
          }}>▸</span>
          Sessions
          {sessions && (
            <span style={{ color: "var(--text-faint)" }}>· {sessions.length} active</span>
          )}
        </button>

        {sessionsOpen && (
          <div style={{ marginTop: 10 }}>
            {sessionsLoading && <LoadingRow />}
            {!sessionsLoading && sessions?.length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-dim)" }}>No active sessions.</div>
            )}
            {!sessionsLoading && (sessions?.length ?? 0) > 0 && (
              <div style={{ display: "grid", gap: 6 }}>
                {sessions!.map((s) => (
                  <div
                    key={s.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      padding: "8px 10px",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      background: "var(--card-bg, var(--bg-elevated))",
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>
                        {s.device_label || "unlabelled device"}
                      </div>
                      <div style={{
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-dim)",
                        marginTop: 2,
                      }}>
                        last seen {s.last_used_at
                          ? new Date(s.last_used_at).toLocaleString()
                          : "never"}
                      </div>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onRevokeSession(s.id, s.device_label)}
                    >
                      revoke
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
