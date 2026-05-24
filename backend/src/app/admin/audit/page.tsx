"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  LoadingRow,
  PageHeader,
  Select,
} from "@/components/ui";

type Entry = {
  id: string;
  created_at: string;
  action: string;
  actor_user_id: string | null;
  target_user_id: string | null;
  org_id: string | null;
  payload: Record<string, unknown> | null;
  actor: { email: string } | null;
  target: { email: string } | null;
  org: { name: string; slug: string } | null;
};

export default function AuditPage() {
  const router = useRouter();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");
  const [limit, setLimit] = useState(100);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      if (typeof window === "undefined") return;
      const t = localStorage.getItem("elevate_access");
      if (!t) {
        router.push("/admin/login");
        return;
      }
      const qs = new URLSearchParams();
      if (actionFilter) qs.set("action", actionFilter);
      qs.set("limit", String(limit));
      const res = await fetch(`/api/admin/audit?${qs.toString()}`, {
        headers: { authorization: `Bearer ${t}` },
      });
      if (res.status === 401 || res.status === 403) {
        router.push("/admin/login");
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "load failed");
      setEntries(data.entries || []);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, [actionFilter, limit, router]);

  useEffect(() => {
    load();
  }, [load]);

  function fmtDate(s: string) {
    const d = new Date(s);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  return (
    <div>
      <PageHeader
        title="Audit Log"
        subtitle={`${entries.length} ${entries.length === 1 ? "entry" : "entries"} loaded`}
      />

      <Card style={{ marginBottom: 16 }}>
        <div
          className="stack-mobile"
          style={{ display: "flex", gap: 8, alignItems: "center" }}
        >
          <Input
            placeholder="Filter by action (license, user_update, org…)"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{ flex: 1 }}
          />
          <Select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ width: "auto", padding: "8px 28px 8px 10px" }}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
          </Select>
          <Button variant="primary" onClick={load} loading={loading}>
            Refresh
          </Button>
        </div>
      </Card>

      {err && <ErrorBanner>{err}</ErrorBanner>}
      {loading && <LoadingRow />}

      <div style={{ display: "grid", gap: 4 }}>
        {entries.map((e) => {
          const open = expandedId === e.id;
          return (
            <div
              key={e.id}
              style={{
                background: "var(--bg-elev)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                overflow: "hidden",
              }}
            >
              <button
                onClick={() => setExpandedId(open ? null : e.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  width: "100%",
                  padding: "10px 14px",
                  background: "transparent",
                  border: "none",
                  color: "var(--text)",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--text-dim)",
                    fontFamily: "var(--font-mono)",
                    minWidth: 130,
                  }}
                >
                  {fmtDate(e.created_at)}
                </span>
                <Badge tone="amber" size="sm">{e.action}</Badge>
                <span
                  style={{
                    flex: 1,
                    color: "var(--text-muted)",
                    fontSize: 12,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  {e.actor?.email && (
                    <span>
                      by <strong style={{ color: "var(--text)" }}>{e.actor.email}</strong>
                    </span>
                  )}
                  {e.target?.email && (
                    <span>
                      → <strong style={{ color: "var(--text)" }}>{e.target.email}</strong>
                    </span>
                  )}
                  {e.org && (
                    <Link
                      href={`/admin/orgs/${e.org_id}`}
                      onClick={(ev) => ev.stopPropagation()}
                      style={{ textDecoration: "none" }}
                    >
                      <Badge tone="neutral" size="sm">{e.org.name}</Badge>
                    </Link>
                  )}
                </span>
                <span style={{ color: "var(--text-faint)", fontSize: 11 }}>
                  {open ? "▼" : "▶"}
                </span>
              </button>
              {open && (
                <div
                  style={{
                    background: "var(--bg-input-solid)",
                    borderTop: "1px solid var(--border)",
                    padding: 14,
                  }}
                >
                  <pre
                    style={{
                      margin: 0,
                      fontSize: 12,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-muted)",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-all",
                    }}
                  >
                    {JSON.stringify(e.payload || {}, null, 2)}
                  </pre>
                  <div
                    style={{
                      marginTop: 10,
                      paddingTop: 10,
                      borderTop: "1px solid var(--border)",
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-dim)",
                      display: "flex",
                      gap: 16,
                      flexWrap: "wrap",
                    }}
                  >
                    <span>
                      <span style={metaLabel}>id</span> {e.id}
                    </span>
                    {e.actor_user_id && (
                      <span>
                        <span style={metaLabel}>actor</span> {e.actor_user_id}
                      </span>
                    )}
                    {e.target_user_id && (
                      <span>
                        <span style={metaLabel}>target</span> {e.target_user_id}
                      </span>
                    )}
                    {e.org_id && (
                      <span>
                        <span style={metaLabel}>org</span> {e.org_id}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {!loading && entries.length === 0 && (
          <EmptyState
            title="No audit entries"
            subtitle="Adjust the filter or check back after some activity."
          />
        )}
      </div>
    </div>
  );
}

const metaLabel: React.CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--text-faint)",
  marginRight: 6,
};
