"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  StatusDot,
} from "@/components/ui";

type Me = {
  id: string;
  email: string;
  role: "owner" | "admin" | "user";
  is_developer: boolean;
  account_type: "single_user" | "team_member" | "team_owner";
  tier: "pro" | "builder";
  entitlements: string[];
  personal_entitlements: string[];
  status: string;
  orgs: Array<{ id: string; slug: string; name: string; role: "owner" | "admin" | "member" }>;
  billing?: {
    has_customer: boolean;
    has_subscription: boolean;
    current_period_end: string | null;
    personal_tier: "pro" | "builder";
    personal_status: string;
  };
};

type LicenseRow = {
  id: string;
  device_label: string | null;
  created_at: string;
  last_used_at: string | null;
  is_current: boolean;
};

const TYPE_LABEL: Record<Me["account_type"], string> = {
  single_user: "Single User",
  team_member: "Team Member",
  team_owner: "Team Owner",
};

const TYPE_TONE: Record<Me["account_type"], "neutral" | "sage" | "accent"> = {
  single_user: "neutral",
  team_member: "sage",
  team_owner: "accent",
};

const ENT_LABELS: Record<string, string> = {
  real_estate_sales: "Sales",
  real_estate_marketing: "Marketing",
  real_estate_admin: "Admin",
  real_estate_cma: "CMA",
};

export default function AccountPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [teamName, setTeamName] = useState("");
  const [creating, setCreating] = useState(false);

  // sessions
  const [licenses, setLicenses] = useState<LicenseRow[] | null>(null);
  const [currentLicenseId, setCurrentLicenseId] = useState<string | null>(null);
  const [sessionsErr, setSessionsErr] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [signingOutAll, setSigningOutAll] = useState(false);

  // profile - email
  const [showEmailForm, setShowEmailForm] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [emailPw, setEmailPw] = useState("");
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [emailOk, setEmailOk] = useState<string | null>(null);

  // profile - password
  const [showPwForm, setShowPwForm] = useState(false);
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwSignOutAll, setPwSignOutAll] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [pwOk, setPwOk] = useState<string | null>(null);

  // billing
  const [billingBusy, setBillingBusy] = useState<"checkout" | "portal" | null>(null);
  const [billingErr, setBillingErr] = useState<string | null>(null);

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
      const res = await authedFetch("/api/me");
      if (res.status === 401 || res.status === 403) {
        router.push("/admin/login");
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "load failed");
      setMe(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  async function createTeam(e: React.FormEvent) {
    e.preventDefault();
    if (!teamName.trim()) return;
    setCreating(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/orgs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: teamName.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "create failed");
      setShowCreate(false);
      setTeamName("");
      const canManage = me && (me.role === "owner" || me.role === "admin");
      if (canManage && data.org?.id) {
        router.push(`/admin/orgs/${data.org.id}`);
      } else {
        await load();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "create failed");
    } finally {
      setCreating(false);
    }
  }

  async function loadLicenses() {
    setSessionsErr(null);
    try {
      const res = await authedFetch("/api/me/licenses");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "load failed");
      setLicenses(data.licenses || []);
      setCurrentLicenseId(data.current_license_id || null);
    } catch (e: unknown) {
      setSessionsErr(e instanceof Error ? e.message : "load failed");
    }
  }

  async function revokeLicense(id: string) {
    if (id === currentLicenseId) {
      const ok = confirm(
        "That's this browser. Revoking it will sign you out here. Continue?",
      );
      if (!ok) return;
    }
    setRevokingId(id);
    try {
      const res = await authedFetch(`/api/me/licenses/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "revoke failed");
      }
      if (id === currentLicenseId) {
        logout();
        return;
      }
      await loadLicenses();
    } catch (e: unknown) {
      setSessionsErr(e instanceof Error ? e.message : "revoke failed");
    } finally {
      setRevokingId(null);
    }
  }

  async function signOutEverywhereElse() {
    if (!confirm("Sign out of every other device? This one stays signed in.")) return;
    setSigningOutAll(true);
    setSessionsErr(null);
    try {
      const res = await authedFetch("/api/me/sign-out-everywhere", { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "sign out failed");
      }
      await loadLicenses();
    } catch (e: unknown) {
      setSessionsErr(e instanceof Error ? e.message : "sign out failed");
    } finally {
      setSigningOutAll(false);
    }
  }

  async function saveEmail(e: React.FormEvent) {
    e.preventDefault();
    setEmailSaving(true);
    setEmailErr(null);
    setEmailOk(null);
    try {
      const res = await authedFetch("/api/me/email", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: newEmail.trim(), password: emailPw }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "update failed");
      setEmailOk(`Email updated to ${data.email}`);
      setShowEmailForm(false);
      setNewEmail("");
      setEmailPw("");
      await load();
    } catch (e: unknown) {
      setEmailErr(e instanceof Error ? e.message : "update failed");
    } finally {
      setEmailSaving(false);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwSaving(true);
    setPwErr(null);
    setPwOk(null);
    try {
      const res = await authedFetch("/api/me/password", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          current_password: curPw,
          new_password: newPw,
          sign_out_everywhere: pwSignOutAll,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "update failed");
      setPwOk(
        pwSignOutAll
          ? "Password changed. Other devices signed out."
          : "Password changed.",
      );
      setShowPwForm(false);
      setCurPw("");
      setNewPw("");
      setPwSignOutAll(false);
      if (pwSignOutAll) await loadLicenses();
    } catch (e: unknown) {
      setPwErr(e instanceof Error ? e.message : "update failed");
    } finally {
      setPwSaving(false);
    }
  }

  async function startCheckout(plan: "pro" | "builder") {
    setBillingErr(null);
    setBillingBusy("checkout");
    try {
      const res = await authedFetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ plan }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "checkout failed");
      window.location.href = data.url;
    } catch (e: unknown) {
      setBillingErr(e instanceof Error ? e.message : "checkout failed");
      setBillingBusy(null);
    }
  }

  async function openPortal() {
    setBillingErr(null);
    setBillingBusy("portal");
    try {
      const res = await authedFetch("/api/stripe/portal", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ return_path: "/account" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "portal failed");
      window.location.href = data.url;
    } catch (e: unknown) {
      setBillingErr(e instanceof Error ? e.message : "portal failed");
      setBillingBusy(null);
    }
  }

  useEffect(() => {
    load();
    loadLicenses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function logout() {
    if (typeof window === "undefined") return;
    localStorage.removeItem("elevate_access");
    localStorage.removeItem("elevate_refresh");
    router.push("/admin/login");
  }

  return (
    <div className="account-shell">
      {/* topbar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "12px 24px",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-elev)",
          flexWrap: "wrap",
        }}
      >
        <Link
          href="/account"
          style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--text)" }}
        >
          <svg width="26" height="26" viewBox="0 0 28 28" fill="none" aria-hidden="true">
            <rect width="28" height="28" rx="7" fill="var(--accent)" />
            <path d="M9 9h10v2.5h-7.5v3h6V17h-6v3H19V22.5H9V9z" fill="#fff" />
          </svg>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.01em" }}>Elevation Real Estate HQ</div>
            <div
              style={{
                fontSize: 10,
                color: "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              account
            </div>
          </div>
        </Link>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {me && (me.role === "owner" || me.role === "admin") && (
            <Link href="/admin/users">
              <Button variant="ghost" size="sm">
                Admin panel
              </Button>
            </Link>
          )}
          <Button variant="ghost" size="sm" onClick={logout}>
            Sign out
          </Button>
        </div>
      </header>

      <div className="account-content fade-in">
        {err && <ErrorBanner>{err}</ErrorBanner>}
        {loading && <LoadingRow />}

        {me && (
          <>
            {/* identity strip — one line, no symmetric block */}
            <Card>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  flexWrap: "wrap",
                }}
              >
                <Avatar email={me.email} size={44} />
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.005em" }}>
                    {me.email}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginTop: 6,
                      fontSize: 12,
                      color: "var(--text-muted)",
                      flexWrap: "wrap",
                    }}
                  >
                    <span>
                      <StatusDot status={me.status} />
                      {me.status}
                    </span>
                    <Separator />
                    <span>
                      Role <span style={{ color: "var(--text)" }}>{me.role}</span>
                    </span>
                    <Separator />
                    <span>
                      Tier <span style={{ color: "var(--text)" }}>{me.tier}</span>
                    </span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Badge tone={TYPE_TONE[me.account_type]}>{TYPE_LABEL[me.account_type]}</Badge>
                  {me.is_developer && <Badge tone="dev">Developer</Badge>}
                </div>
              </div>
            </Card>

            {/* packages */}
            <Card>
              <PackagesHeader count={me.entitlements.length} />
              {me.entitlements.length === 0 ? (
                <EmptyState
                  title="No packages yet"
                  subtitle="Contact your team owner or upgrade your plan to unlock skill packages."
                />
              ) : (
                <>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {me.entitlements.map((e) => {
                      const fromOrg = !me.personal_entitlements.includes(e);
                      const label = ENT_LABELS[e] || e.replace(/^real_estate_/, "");
                      const source = fromOrg
                        ? me.orgs.find((o) => true)?.name ?? "Team"
                        : "Personal";
                      return (
                        <span
                          key={e}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "6px 12px",
                            borderRadius: "var(--r-md)",
                            background: fromOrg ? "var(--sage-bg)" : "var(--bg-input-solid)",
                            border: `1px solid ${fromOrg ? "#3a5a44" : "var(--border)"}`,
                            color: fromOrg ? "var(--sage)" : "var(--text-muted)",
                            fontSize: 13,
                          }}
                          title={`${label} — from ${source}`}
                        >
                          <span
                            aria-hidden="true"
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              background: fromOrg ? "var(--sage)" : "var(--text-faint)",
                            }}
                          />
                          {label}
                        </span>
                      );
                    })}
                  </div>
                  <div
                    style={{
                      marginTop: 14,
                      paddingTop: 12,
                      borderTop: "1px solid var(--border)",
                      fontSize: 11,
                      color: "var(--text-dim)",
                      fontFamily: "var(--font-mono)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      display: "flex",
                      gap: 16,
                      flexWrap: "wrap",
                    }}
                  >
                    <span>
                      <span
                        style={{
                          display: "inline-block",
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background: "var(--sage)",
                          marginRight: 6,
                          verticalAlign: "middle",
                        }}
                      />
                      from a team
                    </span>
                    <span>
                      <span
                        style={{
                          display: "inline-block",
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background: "var(--text-faint)",
                          marginRight: 6,
                          verticalAlign: "middle",
                        }}
                      />
                      personal
                    </span>
                  </div>
                </>
              )}
            </Card>

            {/* billing */}
            <Card>
              <div style={{ marginBottom: 14 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div>
                    <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Billing</h2>
                    <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
                      {me.billing?.has_subscription
                        ? "Manage subscription, invoices, and payment methods."
                        : "No subscription yet. Upgrade to unlock skill packages."}
                    </div>
                  </div>
                  <Badge tone={me.tier === "builder" ? "accent" : "neutral"}>
                    {me.tier === "builder" ? "Builder" : "Pro"}
                  </Badge>
                </div>
              </div>

              {billingErr && <ErrorBanner>{billingErr}</ErrorBanner>}

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: 10,
                  marginBottom: 14,
                }}
              >
                <BillingStat
                  label="Personal tier"
                  value={me.billing?.personal_tier || me.tier}
                />
                <BillingStat
                  label="Status"
                  value={me.billing?.personal_status || me.status}
                />
                <BillingStat
                  label="Next bill"
                  value={
                    me.billing?.current_period_end
                      ? new Date(me.billing.current_period_end).toLocaleDateString()
                      : "—"
                  }
                />
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {me.billing?.has_subscription ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={openPortal}
                    loading={billingBusy === "portal"}
                  >
                    Manage subscription
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => startCheckout("pro")}
                      loading={billingBusy === "checkout"}
                    >
                      Upgrade to Pro
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => startCheckout("builder")}
                      loading={billingBusy === "checkout"}
                    >
                      Upgrade to Builder
                    </Button>
                  </>
                )}
              </div>
            </Card>

            {/* teams */}
            <Card>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: me.orgs.length > 0 || showCreate ? 16 : 0,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Your teams</h2>
                  <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
                    {me.orgs.length === 0
                      ? "You're not on any team yet."
                      : `Member of ${me.orgs.length} team${me.orgs.length === 1 ? "" : "s"}.`}
                  </div>
                </div>
                {me.orgs.length > 0 && (
                  <Button variant="primary" size="sm" onClick={() => setShowCreate((s) => !s)}>
                    {showCreate ? "Cancel" : "New team"}
                  </Button>
                )}
              </div>

              {showCreate && (
                <form
                  onSubmit={createTeam}
                  style={{
                    display: "flex",
                    gap: 8,
                    padding: 12,
                    background: "var(--bg-input-solid)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    marginBottom: me.orgs.length > 0 ? 16 : 0,
                    flexWrap: "wrap",
                  }}
                >
                  <Input
                    placeholder="Team name (Acme Real Estate)"
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    autoFocus
                    required
                    style={{ flex: 1, minWidth: 200 }}
                  />
                  <Button variant="primary" type="submit" loading={creating}>
                    {creating ? "Creating" : "Create team"}
                  </Button>
                </form>
              )}

              {me.orgs.length === 0 && !showCreate && (
                <EmptyState
                  title={
                    me.account_type === "single_user"
                      ? "Upgrade to a team"
                      : "No teams yet"
                  }
                  subtitle="Create a team to invite collaborators, share entitlements, and manage seats from one place."
                  action={
                    <Button variant="primary" onClick={() => setShowCreate(true)}>
                      Create your team
                    </Button>
                  }
                />
              )}

              {me.orgs.length > 0 && (
                <div style={{ display: "grid", gap: 8 }}>
                  {me.orgs.map((o) => {
                    const canManage = o.role === "owner" || o.role === "admin";
                    return (
                      <div
                        key={o.id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                          padding: "12px 14px",
                          background: "var(--bg-input-solid)",
                          border: "1px solid var(--border)",
                          borderRadius: "var(--r-md)",
                          flexWrap: "wrap",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                          <Avatar email={o.name} size={32} />
                          <div style={{ minWidth: 0 }}>
                            <div
                              style={{
                                fontSize: 14,
                                fontWeight: 600,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {o.name}
                            </div>
                            <div
                              style={{
                                fontSize: 11,
                                color: "var(--text-dim)",
                                fontFamily: "var(--font-mono)",
                                marginTop: 2,
                              }}
                            >
                              {o.slug}
                            </div>
                          </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <Badge tone={o.role === "owner" ? "accent" : "neutral"} size="sm">
                            {o.role}
                          </Badge>
                          {canManage && (
                            <Link href={`/admin/orgs/${o.id}`}>
                              <Button variant="ghost" size="sm">
                                Manage
                              </Button>
                            </Link>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>

            {/* sessions */}
            <Card>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: 14,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Sessions</h2>
                  <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
                    {licenses === null
                      ? "Loading"
                      : licenses.length === 0
                        ? "No active sessions."
                        : `${licenses.length} active device${licenses.length === 1 ? "" : "s"}.`}
                  </div>
                </div>
                {licenses && licenses.length > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={signOutEverywhereElse}
                    loading={signingOutAll}
                  >
                    Sign out everywhere else
                  </Button>
                )}
              </div>

              {sessionsErr && <ErrorBanner>{sessionsErr}</ErrorBanner>}

              {licenses && licenses.length > 0 && (
                <div style={{ display: "grid", gap: 8 }}>
                  {licenses.map((l) => (
                    <div
                      key={l.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 12,
                        padding: "12px 14px",
                        background: "var(--bg-input-solid)",
                        border: `1px solid ${l.is_current ? "var(--accent)" : "var(--border)"}`,
                        borderRadius: "var(--r-md)",
                        flexWrap: "wrap",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                        <Avatar email={l.device_label || l.id} size={32} />
                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: 14,
                              fontWeight: 600,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {l.device_label || "Unnamed device"}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--text-dim)",
                              fontFamily: "var(--font-mono)",
                              marginTop: 2,
                            }}
                          >
                            last seen {l.last_used_at ? new Date(l.last_used_at).toLocaleString() : "never"}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {l.is_current && (
                          <Badge tone="accent" size="sm">
                            this device
                          </Badge>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => revokeLicense(l.id)}
                          loading={revokingId === l.id}
                        >
                          Revoke
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* profile */}
            <Card>
              <div style={{ marginBottom: 14 }}>
                <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Profile</h2>
                <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
                  Update the email and password tied to this account.
                </div>
              </div>

              {/* email */}
              <div
                style={{
                  padding: "12px 14px",
                  background: "var(--bg-input-solid)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--r-md)",
                  marginBottom: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Email</div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--text-muted)",
                        fontFamily: "var(--font-mono)",
                        marginTop: 2,
                      }}
                    >
                      {me.email}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowEmailForm((s) => !s);
                      setEmailErr(null);
                      setEmailOk(null);
                    }}
                  >
                    {showEmailForm ? "Cancel" : "Change email"}
                  </Button>
                </div>

                {emailOk && (
                  <div
                    style={{
                      marginTop: 10,
                      fontSize: 12,
                      color: "var(--sage)",
                    }}
                  >
                    {emailOk}
                  </div>
                )}

                {showEmailForm && (
                  <form
                    onSubmit={saveEmail}
                    style={{ display: "grid", gap: 10, marginTop: 12 }}
                  >
                    {emailErr && <ErrorBanner>{emailErr}</ErrorBanner>}
                    <div>
                      <Label>New email</Label>
                      <Input
                        type="email"
                        value={newEmail}
                        onChange={(e) => setNewEmail(e.target.value)}
                        required
                        autoFocus
                      />
                    </div>
                    <div>
                      <Label>Current password</Label>
                      <Input
                        type="password"
                        value={emailPw}
                        onChange={(e) => setEmailPw(e.target.value)}
                        required
                      />
                    </div>
                    <div>
                      <Button variant="primary" type="submit" loading={emailSaving}>
                        {emailSaving ? "Saving" : "Save email"}
                      </Button>
                    </div>
                  </form>
                )}
              </div>

              {/* password */}
              <div
                style={{
                  padding: "12px 14px",
                  background: "var(--bg-input-solid)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--r-md)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Password</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                      At least 8 characters.
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowPwForm((s) => !s);
                      setPwErr(null);
                      setPwOk(null);
                    }}
                  >
                    {showPwForm ? "Cancel" : "Change password"}
                  </Button>
                </div>

                {pwOk && (
                  <div
                    style={{
                      marginTop: 10,
                      fontSize: 12,
                      color: "var(--sage)",
                    }}
                  >
                    {pwOk}
                  </div>
                )}

                {showPwForm && (
                  <form
                    onSubmit={savePassword}
                    style={{ display: "grid", gap: 10, marginTop: 12 }}
                  >
                    {pwErr && <ErrorBanner>{pwErr}</ErrorBanner>}
                    <div>
                      <Label>Current password</Label>
                      <Input
                        type="password"
                        value={curPw}
                        onChange={(e) => setCurPw(e.target.value)}
                        required
                        autoFocus
                      />
                    </div>
                    <div>
                      <Label>New password</Label>
                      <Input
                        type="password"
                        value={newPw}
                        onChange={(e) => setNewPw(e.target.value)}
                        minLength={8}
                        required
                      />
                    </div>
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 12,
                        color: "var(--text-muted)",
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={pwSignOutAll}
                        onChange={(e) => setPwSignOutAll(e.target.checked)}
                      />
                      Also sign me out of all other devices
                    </label>
                    <div>
                      <Button variant="primary" type="submit" loading={pwSaving}>
                        {pwSaving ? "Saving" : "Save password"}
                      </Button>
                    </div>
                  </form>
                )}
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function PackagesHeader({ count }: { count: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 14,
      }}
    >
      <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Active packages</h2>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-dim)",
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {count} {count === 1 ? "package" : "packages"}
      </div>
    </div>
  );
}

function Separator() {
  return <span style={{ color: "var(--text-faint)" }}>·</span>;
}

function BillingStat({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--bg-input-solid)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "var(--text-dim)",
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{value}</div>
    </div>
  );
}
