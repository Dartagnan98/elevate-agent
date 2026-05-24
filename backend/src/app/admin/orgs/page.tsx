"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
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
  tier: string;
  status: string;
  entitlements: string[];
  seat_limit: number;
  current_period_end: string | null;
  stripe_customer: string | null;
  created_at: string;
};

export default function OrgsPage() {
  const router = useRouter();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [newTier, setNewTier] = useState<"pro" | "builder">("pro");
  const [newSeatLimit, setNewSeatLimit] = useState(5);
  const [creating, setCreating] = useState(false);

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
      const res = await authedFetch("/api/admin/orgs");
      if (res.status === 401 || res.status === 403) {
        router.push("/admin/login");
        return;
      }
      const data = await res.json();
      setOrgs(data.orgs || []);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setCreating(true);
    try {
      const res = await authedFetch("/api/admin/orgs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: newName,
          slug: newSlug,
          tier: newTier,
          seat_limit: newSeatLimit,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "create failed");
      setShowCreate(false);
      setNewName("");
      setNewSlug("");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "create failed");
    } finally {
      setCreating(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <PageHeader
        title="Organizations"
        subtitle={`${orgs.length} ${orgs.length === 1 ? "team" : "teams"} on Elevate`}
        actions={
          <Button variant="primary" onClick={() => setShowCreate((s) => !s)}>
            {showCreate ? "Cancel" : "+ New organization"}
          </Button>
        }
      />

      {showCreate && (
        <Card style={{ marginBottom: 20 }}>
          <form
            onSubmit={create}
            className="stack-mobile"
            style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
          >
            <div style={{ flex: "1 1 200px" }}>
              <Label>Name</Label>
              <Input
                placeholder="Forever Real Estate"
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value);
                  if (!newSlug)
                    setNewSlug(
                      e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
                    );
                }}
                required
              />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <Label>Slug</Label>
              <Input
                placeholder="forever-real-estate"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
                required
              />
            </div>
            <div style={{ flex: "0 0 120px" }}>
              <Label>Tier</Label>
              <Select value={newTier} onChange={(e) => setNewTier(e.target.value as "pro" | "builder")}>
                <option value="pro">pro</option>
                <option value="builder">builder</option>
              </Select>
            </div>
            <div style={{ flex: "0 0 90px" }}>
              <Label>Seats</Label>
              <Input
                type="number"
                min={1}
                value={newSeatLimit}
                onChange={(e) => setNewSeatLimit(Number(e.target.value))}
              />
            </div>
            <Button type="submit" variant="primary" loading={creating}>
              Create
            </Button>
          </form>
        </Card>
      )}

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {loading && <LoadingRow />}

      <div style={{ display: "grid", gap: 10 }}>
        {orgs.map((o) => (
          <Link
            key={o.id}
            href={`/admin/orgs/${o.id}`}
            style={{ textDecoration: "none", display: "block" }}
          >
            <Card
              style={{
                cursor: "pointer",
                transition: "border-color 120ms, background 120ms",
              }}
            >
              <div
                className="stack-mobile"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{o.name}</div>
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
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    fontSize: 12,
                    color: "var(--text-dim)",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center" }}>
                    <StatusDot status={o.status} />
                    {o.status}
                  </span>
                  <Badge tone={o.tier === "builder" ? "accent" : "neutral"} size="sm">
                    {o.tier}
                  </Badge>
                  <Badge tone="neutral" size="sm">
                    {o.seat_limit} seats
                  </Badge>
                  <Badge tone="neutral" size="sm">
                    {o.entitlements.length} entitlements
                  </Badge>
                </div>
              </div>
            </Card>
          </Link>
        ))}
        {!loading && orgs.length === 0 && (
          <EmptyState
            title="No organizations yet"
            subtitle="Create the first one to start onboarding members."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                + New organization
              </Button>
            }
          />
        )}
      </div>
    </div>
  );
}
