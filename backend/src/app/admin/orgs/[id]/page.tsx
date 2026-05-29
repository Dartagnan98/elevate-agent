"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  Label,
  LoadingRow,
  PageHeader,
  Select,
  StatusDot,
} from "@/components/ui";

type Org = {
  id: string;
  slug: string;
  name: string;
  tier: "pro" | "builder";
  status: string;
  entitlements: string[];
  seat_limit: number;
  current_period_end: string | null;
  stripe_customer: string | null;
};

type Member = { id: string; user_id: string; role: string; email: string | null; created_at: string };
type Invitation = { id: string; email: string; role: string; status: string; expires_at: string };

const KNOWN_ENTITLEMENTS: Array<{ key: string; label: string }> = [
  { key: "real_estate_sales", label: "Sales" },
  { key: "real_estate_marketing", label: "Marketing" },
  { key: "real_estate_admin", label: "Admin" },
  { key: "real_estate_cma", label: "CMA" },
];

export default function OrgDetail() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [org, setOrg] = useState<Org | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"owner" | "admin" | "member">("member");
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [inviteSentTo, setInviteSentTo] = useState<string | null>(null);
  const [inviteEmailed, setInviteEmailed] = useState(false);
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

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}`);
      if (res.status === 401 || res.status === 403) {
        router.push("/admin/login");
        return;
      }
      if (res.status === 404) {
        setErr("Organization not found");
        return;
      }
      const data = await res.json();
      setOrg(data.org);
      setMembers(data.members);
      setInvitations(data.invitations);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (orgId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  async function update(body: Record<string, unknown>) {
    setBusy(true);
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}`, {
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
      setBusy(false);
    }
  }

  function toggleEntitlement(ent: string) {
    if (!org) return;
    const next = org.entitlements.includes(ent)
      ? org.entitlements.filter((e) => e !== ent)
      : [...org.entitlements, ent];
    update({ entitlements: next });
  }

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setInviteLink(null);
    setInviteSentTo(null);
    setInviteEmailed(false);
    setCopied(false);
    const addr = inviteEmail.trim();
    try {
      const res = await authedFetch(`/api/admin/orgs/${orgId}/members`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: addr, role: inviteRole }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "invite failed");
      setInviteEmail("");
      // `added` => existing user joined directly (no email). Otherwise an
      // invitation was created and emailed; keep accept_url only as a backup
      // for the rare case the email send failed.
      if (!data.added) {
        setInviteSentTo(data.invitation?.email || addr);
        setInviteEmailed(data.emailed === true);
        if (data.accept_url) setInviteLink(data.accept_url);
      }
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "invite failed");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(userId: string, role: string) {
    await authedFetch(`/api/admin/orgs/${orgId}/members/${userId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ role }),
    });
    await load();
  }

  async function removeMember(userId: string) {
    if (!confirm("Remove this member from the org?")) return;
    await authedFetch(`/api/admin/orgs/${orgId}/members/${userId}`, { method: "DELETE" });
    await load();
  }

  if (loading) return <LoadingRow />;
  if (!org) return <ErrorBanner>{err || "not found"}</ErrorBanner>;

  const seatsUsed = members.length;
  const seatsLeft = Math.max(0, org.seat_limit - seatsUsed);

  return (
    <div>
      <Link
        href="/admin/orgs"
        style={{
          color: "var(--text-dim)",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          display: "inline-block",
          marginBottom: 12,
        }}
      >
        ← All organizations
      </Link>

      <PageHeader
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            {org.name}
            <Badge tone={org.tier === "builder" ? "accent" : "neutral"}>{org.tier}</Badge>
          </span>
        }
        subtitle={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: "var(--font-mono)" }}>{org.slug}</span>
            <span style={{ color: "var(--text-faint)" }}>·</span>
            <span style={{ display: "inline-flex", alignItems: "center" }}>
              <StatusDot status={org.status} />
              {org.status}
            </span>
            <span style={{ color: "var(--text-faint)" }}>·</span>
            <span>{seatsUsed} / {org.seat_limit} seats</span>
          </span>
        }
        actions={
          <div className="stack-mobile" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Select
              value={org.tier}
              onChange={(e) => update({ tier: e.target.value })}
              disabled={busy}
              style={{ width: "auto", padding: "6px 28px 6px 10px" }}
            >
              <option value="pro">pro</option>
              <option value="builder">builder</option>
            </Select>
            <Select
              value={org.status}
              onChange={(e) => update({ status: e.target.value })}
              disabled={busy}
              style={{ width: "auto", padding: "6px 28px 6px 10px" }}
            >
              <option value="active">active</option>
              <option value="trialing">trialing</option>
              <option value="past_due">past_due</option>
              <option value="canceled">canceled</option>
              <option value="inactive">inactive</option>
            </Select>
            <Input
              type="number"
              min={1}
              value={org.seat_limit}
              onChange={(e) => update({ seat_limit: Number(e.target.value) })}
              disabled={busy}
              title="seat limit"
              style={{ width: 80, padding: "6px 10px" }}
            />
          </div>
        }
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}

      <div style={{ display: "grid", gap: 16 }}>
        <Card>
          <Label>Entitlements · apply to every org member</Label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {KNOWN_ENTITLEMENTS.map(({ key, label }) => {
              const on = org.entitlements.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleEntitlement(key)}
                  disabled={busy}
                  style={{
                    padding: "5px 12px",
                    borderRadius: 999,
                    border: "1px solid",
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    cursor: busy ? "not-allowed" : "pointer",
                    transition: "background 120ms, color 120ms, border-color 120ms",
                    background: on ? "var(--sage-bg)" : "var(--bg-input-solid)",
                    color: on ? "var(--sage)" : "var(--text-dim)",
                    borderColor: on ? "#3a5a44" : "var(--border)",
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </Card>

        <Card>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 12,
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <Label>Members</Label>
            <span
              style={{
                fontSize: 11,
                color: "var(--text-dim)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {seatsLeft} {seatsLeft === 1 ? "seat" : "seats"} open
            </span>
          </div>

          <form
            onSubmit={invite}
            className="stack-mobile"
            style={{ display: "flex", gap: 8, marginBottom: 12 }}
          >
            <Input
              type="email"
              placeholder="invite by email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              required
              style={{ flex: 1 }}
            />
            <Select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
              style={{ width: "auto", padding: "8px 28px 8px 10px" }}
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
              <option value="owner">owner</option>
            </Select>
            <Button type="submit" variant="primary" disabled={seatsLeft <= 0} loading={busy}>
              Invite
            </Button>
          </form>

          {inviteSentTo && (
            <div
              style={{
                marginBottom: 12,
                padding: 12,
                background: "var(--bg-input-solid)",
                border: "1px solid var(--border)",
                borderLeft: `3px solid ${inviteEmailed ? "var(--sage)" : "var(--amber)"}`,
                borderRadius: "var(--r-md)",
              }}
            >
              {inviteEmailed ? (
                <>
                  <Label>Invitation emailed</Label>
                  <div style={{ fontSize: 13, color: "var(--text)" }}>
                    Sent to <strong>{inviteSentTo}</strong>. They&apos;ll get a link to accept and set a password.
                  </div>
                  {inviteLink && (
                    <div style={{ marginTop: 8 }}>
                      <Button
                        variant="ghost"
                        size="sm"
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(inviteLink);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        }}
                      >
                        {copied ? "Copied" : "Copy backup link"}
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <Label>Couldn&apos;t email the invite — share this link</Label>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <code
                      style={{
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text)",
                        wordBreak: "break-all",
                        flex: 1,
                        minWidth: 200,
                      }}
                    >
                      {inviteLink}
                    </code>
                    {inviteLink && (
                      <Button
                        variant="ghost"
                        size="sm"
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(inviteLink);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        }}
                      >
                        {copied ? "Copied" : "Copy"}
                      </Button>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {members.length === 0 ? (
            <EmptyState title="No members yet" subtitle="Send an invite above to add the first one." />
          ) : (
            <div style={{ display: "grid", gap: 6 }}>
              {members.map((m) => (
                <div
                  key={m.id}
                  className="stack-mobile"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "10px 12px",
                    background: "var(--bg-input-solid)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    gap: 12,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <Avatar email={m.email || "??"} size={28} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{m.email}</div>
                      <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                        joined {new Date(m.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                  <div className="stack-mobile" style={{ display: "flex", gap: 6 }}>
                    <Select
                      value={m.role}
                      onChange={(e) => changeRole(m.user_id, e.target.value)}
                      style={{ width: "auto", padding: "5px 28px 5px 10px" }}
                    >
                      <option value="member">member</option>
                      <option value="admin">admin</option>
                      <option value="owner">owner</option>
                    </Select>
                    <Button variant="danger" size="sm" onClick={() => removeMember(m.user_id)}>
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {invitations.length > 0 && (
          <Card>
            <Label>Pending invitations</Label>
            <div style={{ display: "grid", gap: 6 }}>
              {invitations.map((i) => (
                <div
                  key={i.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "10px 12px",
                    background: "var(--bg-input-solid)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    gap: 12,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{i.email}</div>
                    <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                      {i.role} · expires {new Date(i.expires_at).toLocaleDateString()}
                    </div>
                  </div>
                  <Badge tone={i.status === "pending" ? "amber" : "neutral"} size="sm">
                    {i.status}
                  </Badge>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
