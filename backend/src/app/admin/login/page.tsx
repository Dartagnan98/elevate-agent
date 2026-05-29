"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, ErrorBanner, Input, Label } from "@/components/ui";

type Mode = "password" | "code";

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/admin/users";

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Shared: store tokens and redirect (same for password + code login).
  function finishLogin(data: { access_token: string; refresh_token: string }) {
    localStorage.setItem("elevate_access", data.access_token);
    localStorage.setItem("elevate_refresh", data.refresh_token);
    const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/admin/users";
    router.push(safeNext);
  }

  function switchMode(m: Mode) {
    setMode(m);
    setErr(null);
    setInfo(null);
    setCode("");
    setCodeSent(false);
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, device_label: "admin-web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "login failed");
      finishLogin(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "login failed");
    } finally {
      setLoading(false);
    }
  }

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setInfo(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login-code/request", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "could not send code");
      // Always-OK response (no enumeration). Move to the verify step regardless.
      setCodeSent(true);
      setInfo("If that email has an account, a 6-digit code is on its way. It expires in 10 minutes.");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "could not send code");
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login-code/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, code, device_label: "admin-web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "invalid code");
      finishLogin(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "invalid code");
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
              control panel
            </div>
          </div>
        </div>

        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
          Sign in
        </h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-dim)", fontSize: 13 }}>
          {mode === "password"
            ? "Manage users, organizations, and entitlements."
            : codeSent
              ? "Enter the 6-digit code we emailed you."
              : "We'll email you a one-time sign-in code."}
        </p>

        {mode === "password" && (
          <form onSubmit={submitPassword} style={{ display: "grid", gap: 14 }}>
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
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
              {loading ? "Signing in" : "Sign in"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
          </form>
        )}

        {mode === "code" && !codeSent && (
          <form onSubmit={requestCode} style={{ display: "grid", gap: 14 }}>
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
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
              {loading ? "Sending code" : "Email me a code"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
          </form>
        )}

        {mode === "code" && codeSent && (
          <form onSubmit={verifyCode} style={{ display: "grid", gap: 14 }}>
            {info && (
              <div
                style={{
                  fontSize: 12.5,
                  color: "var(--text-muted)",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--r-md)",
                  padding: "10px 12px",
                  lineHeight: 1.45,
                }}
              >
                {info}
              </div>
            )}
            <div>
              <Label>6-digit code</Label>
              <Input
                type="text"
                inputMode="numeric"
                pattern="\d{6}"
                maxLength={6}
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                required
                autoFocus
                autoComplete="one-time-code"
                style={{ letterSpacing: "0.3em", fontFamily: "var(--font-mono)", fontSize: 18 }}
              />
            </div>
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
              {loading ? "Verifying" : "Verify & sign in"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
            <button
              type="button"
              onClick={() => {
                setCodeSent(false);
                setCode("");
                setErr(null);
                setInfo(null);
              }}
              style={{
                background: "none",
                border: "none",
                color: "var(--text-muted)",
                fontSize: 12.5,
                cursor: "pointer",
                padding: 0,
                justifySelf: "center",
              }}
            >
              Use a different email or resend
            </button>
          </form>
        )}

        <div
          style={{
            marginTop: 20,
            paddingTop: 18,
            borderTop: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            fontSize: 13,
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            onClick={() => switchMode(mode === "password" ? "code" : "password")}
            style={{
              background: "none",
              border: "none",
              color: "var(--accent)",
              textDecoration: "none",
              fontWeight: 500,
              fontSize: 13,
              cursor: "pointer",
              padding: 0,
            }}
          >
            {mode === "password" ? "Sign in with an email code" : "Use password instead"}
          </button>
          <span style={{ color: "var(--text-dim)" }}>
            New here?{" "}
            <Link
              href={`/signup${next !== "/admin/users" ? `?next=${encodeURIComponent(next)}` : ""}`}
              style={{ color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}
            >
              Create an account
            </Link>
          </span>
        </div>

        {mode === "password" && (
          <div style={{ marginTop: 12, fontSize: 13 }}>
            <Link href="/forgot" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
              Forgot password?
            </Link>
          </div>
        )}
      </div>
    </main>
  );
}

export default function AdminLogin() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
