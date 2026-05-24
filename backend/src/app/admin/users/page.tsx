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
  entitlements: string[];
  stripe_customer: string | null;
  current_period_end: string | null;
  created_at: string;
};

type Org = {
  id: string;
  slug: string;
  name: string;
  tier: string;
  status: string;
  entitlements: string[];
  seat_limit: number;
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
  const [membershipsByUser, setMembershipsByUser] = useState<
    Record<string, Array<{ org_id: string; role: string }>>
  >({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

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
      const detailResponses = await Promise.all(
        allOrgs.map((o) => authedFetch(`/api/admin/orgs/${o.id}`).then((r) => r.json())),
      );
      const map: Record<string, Array<{ org_id: string; role: string }>> = {};
      detailResponses.forEach((detail) => {
        if (!detail?.members) return;
        for (const m of detail.members) {
          if (!map[m.user_id]) map[m.user_id] = [];
          map[m.user_id].push({ org_id: detail.org.id, role: m.role });
        }
      });
      setMembershipsByUser(map);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
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

  function toggleEntitlement(u: User, ent: string) {
    const next = u.entitlements.includes(ent)
      ? u.entitlements.filter((e) => e !== ent)
      : [...u.entitlements, ent];
    update(u.id, { entitlements: next });
  }

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle={`${users.length} ${users.length === 1 ? "account" : "accounts"} across all organizations`}
      />

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {loading && <LoadingRow />}

      <div style={{ display: "grid", gap: 12 }}>
        {users.map((u) => {
          const memberships = membershipsByUser[u.id] || [];
          const isSaving = savingId === u.id;
          return (
            <Card key={u.id}>
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
                  <Avatar email={u.email} size={40} />
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        flexWrap: "wrap",
                      }}
                    >
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{u.email}</div>
                      {u.is_developer && <Badge tone="dev" size="sm">dev</Badge>}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        marginTop: 4,
                        fontSize: 12,
                        color: "var(--text-dim)",
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ display: "inline-flex", alignItems: "center" }}>
                        <StatusDot status={u.status} />
                        {u.status}
                      </span>
                      <span style={{ color: "var(--text-faint)" }}>·</span>
                      <span>{u.role}</span>
                      <span style={{ color: "var(--text-faint)" }}>·</span>
                      <span>tier {u.tier}</span>
                    </div>
                    {memberships.length > 0 && (
                      <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                        {memberships.map((m) => {
                          const o = orgs.find((x) => x.id === m.org_id);
                          if (!o) return null;
                          return (
                            <Link
                              key={m.org_id}
                              href={`/admin/orgs/${m.org_id}`}
                              style={{ textDecoration: "none" }}
                              title={`${m.role} of ${o.name}`}
                            >
                              <Badge tone="neutral" size="sm">
                                {o.name} · {m.role}
                              </Badge>
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
                <div
                  className="stack-mobile"
                  style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}
                >
                  <Select
                    value={u.tier}
                    onChange={(e) => update(u.id, { tier: e.target.value })}
                    disabled={isSaving}
                    style={{ width: "auto", padding: "6px 28px 6px 10px" }}
                  >
                    <option value="pro">pro</option>
                    <option value="builder">builder</option>
                  </Select>
                  <Select
                    value={u.status}
                    onChange={(e) => update(u.id, { status: e.target.value })}
                    disabled={isSaving}
                    style={{ width: "auto", padding: "6px 28px 6px 10px" }}
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
                    onClick={() => update(u.id, { is_developer: !u.is_developer })}
                    disabled={isSaving}
                    title="developer flag: bypasses entitlement gating, always builder tier"
                  >
                    {u.is_developer ? "dev on" : "make dev"}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      if (confirm(`Revoke all licenses for ${u.email}?`)) {
                        update(u.id, { revoke_licenses: true });
                      }
                    }}
                    disabled={isSaving}
                  >
                    revoke licenses
                  </Button>
                </div>
              </div>

              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <Label>Personal entitlements · override</Label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {KNOWN_ENTITLEMENTS.map(({ key, label }) => {
                    const on = u.entitlements.includes(key);
                    return (
                      <button
                        key={key}
                        onClick={() => toggleEntitlement(u, key)}
                        disabled={isSaving}
                        style={{
                          padding: "4px 10px",
                          borderRadius: 999,
                          border: "1px solid",
                          fontSize: 11,
                          fontFamily: "var(--font-mono)",
                          textTransform: "uppercase",
                          letterSpacing: "0.06em",
                          cursor: isSaving ? "not-allowed" : "pointer",
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
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
