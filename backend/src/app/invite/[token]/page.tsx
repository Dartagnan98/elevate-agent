"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button, ErrorBanner, Input, Label } from "@/components/ui";

export default function InviteAccept() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const body: Record<string, unknown> = { token: params.token };
      if (password) body.password = password;
      const res = await fetch("/api/invitations/accept", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.status === 400 && data.needs_password) {
        setNeedsPassword(true);
        setEmail(data.email);
        setErr("Create a password to finish signing up");
        return;
      }
      if (!res.ok) throw new Error(data.error || "accept failed");
      localStorage.setItem("elevate_access", data.access_token);
      localStorage.setItem("elevate_refresh", data.refresh_token);
      setDone(true);
      setTimeout(() => router.push("/account"), 1200);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "accept failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 16,
        background:
          "radial-gradient(circle at 20% 0%, rgba(217, 119, 87, 0.06), transparent 50%), radial-gradient(circle at 80% 100%, rgba(122, 158, 135, 0.04), transparent 50%), var(--bg)",
      }}
    >
      <div
        className="fade-in"
        style={{
          width: "100%",
          maxWidth: 400,
          background: "var(--bg-elev)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-xl)",
          padding: "32px 28px",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
          <svg width="32" height="32" viewBox="0 0 28 28" fill="none" aria-hidden="true">
            <rect width="28" height="28" rx="7" fill="var(--accent)" />
            <path d="M9 9h10v2.5h-7.5v3h6V17h-6v3H19V22.5H9V9z" fill="#fff" />
          </svg>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em" }}>Elevate HQ</div>
            <div
              style={{
                fontSize: 10,
                color: "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              you&apos;ve been invited
            </div>
          </div>
        </div>

        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
          Accept invitation
        </h1>
        <p style={{ margin: "0 0 22px", color: "var(--text-dim)", fontSize: 13 }}>
          Join the organization and start using Elevate.
        </p>

        {done ? (
          <div
            style={{
              padding: "12px 14px",
              background: "var(--sage-bg)",
              border: "1px solid #3a5a44",
              borderLeft: "3px solid var(--sage)",
              borderRadius: "var(--r-md)",
              color: "var(--sage)",
              fontSize: 13,
            }}
          >
            Joined. Redirecting…
          </div>
        ) : (
          <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
            {email && (
              <div
                style={{
                  fontSize: 13,
                  color: "var(--text-muted)",
                  padding: "10px 12px",
                  background: "var(--bg-input-solid)",
                  borderRadius: "var(--r-md)",
                  border: "1px solid var(--border)",
                }}
              >
                Signing up <strong style={{ color: "var(--text)" }}>{email}</strong>
              </div>
            )}
            {needsPassword && (
              <div>
                <Label>Create password</Label>
                <Input
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={8}
                  required
                  autoFocus
                  autoComplete="new-password"
                />
              </div>
            )}
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%" }}>
              {loading ? "Joining" : needsPassword ? "Create account & join" : "Accept invitation"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
          </form>
        )}
      </div>
    </main>
  );
}
