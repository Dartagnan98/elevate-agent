"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, ErrorBanner, Input, Label } from "@/components/ui";

function SignupInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/account";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, device_label: "signup-web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "signup failed");
      localStorage.setItem("elevate_access", data.access_token);
      localStorage.setItem("elevate_refresh", data.refresh_token);
      const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/account";
      router.push(safeNext);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "signup failed");
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
          maxWidth: 380,
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
              create account
            </div>
          </div>
        </div>

        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
          Create your account
        </h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-dim)", fontSize: 13 }}>
          Start a personal workspace. Add teammates or buy packages later.
        </p>

        <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
          <div>
            <Label>Email</Label>
            <Input
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="email"
            />
          </div>
          <div>
            <Label>Password</Label>
            <Input
              type="password"
              placeholder="At least 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
              autoComplete="new-password"
            />
          </div>
          <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
            {loading ? "Creating account" : "Create account"}
          </Button>
          {err && <ErrorBanner>{err}</ErrorBanner>}
        </form>

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
          Already have an account?{" "}
          <Link
            href="/admin/login"
            style={{ color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}
          >
            Sign in
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupInner />
    </Suspense>
  );
}
