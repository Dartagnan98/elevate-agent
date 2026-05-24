"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, ErrorBanner, Input, Label } from "@/components/ui";

function ResetInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (password !== confirm) {
      setErr("Passwords don't match.");
      return;
    }
    if (!token) {
      setErr("Missing reset token. Use the link from your email.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/auth/reset", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "reset failed");
      setDone(data.email);
      setTimeout(() => router.push("/admin/login"), 2500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "reset failed");
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
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
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
              new password
            </div>
          </div>
        </div>

        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
          Choose a new password
        </h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-dim)", fontSize: 13 }}>
          All your other sessions will be signed out.
        </p>

        {done ? (
          <div
            style={{
              padding: "14px 16px",
              background: "var(--sage-bg)",
              border: "1px solid #3a5a44",
              borderRadius: "var(--r-md)",
              color: "var(--sage)",
              fontSize: 13,
            }}
          >
            Password updated for <strong>{done}</strong>. Redirecting to sign in.
          </div>
        ) : (
          <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
            <div>
              <Label>New password</Label>
              <Input
                type="password"
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                required
                autoFocus
                autoComplete="new-password"
              />
            </div>
            <div>
              <Label>Confirm password</Label>
              <Input
                type="password"
                placeholder="Re-enter password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                minLength={8}
                required
                autoComplete="new-password"
              />
            </div>
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
              {loading ? "Saving" : "Set new password"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
          </form>
        )}

        <div
          style={{
            marginTop: 20,
            paddingTop: 18,
            borderTop: "1px solid var(--border)",
            fontSize: 13,
            color: "var(--text-dim)",
            textAlign: "center",
          }}
        >
          <Link
            href="/admin/login"
            style={{ color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}
          >
            Back to sign in
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function ResetPage() {
  return (
    <Suspense fallback={null}>
      <ResetInner />
    </Suspense>
  );
}
