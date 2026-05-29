"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth-shell";

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
  const [status, setStatus] = useState<{ text: string; kind: "error" | "info" } | null>(null);
  const [loading, setLoading] = useState(false);

  function finishLogin(data: { access_token: string; refresh_token: string }) {
    localStorage.setItem("elevate_access", data.access_token);
    localStorage.setItem("elevate_refresh", data.refresh_token);
    const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/admin/users";
    router.push(safeNext);
  }

  function switchMode(m: Mode) {
    setMode(m);
    setStatus(null);
    setCode("");
    setCodeSent(false);
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setStatus({ text: "Signing in...", kind: "info" });
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, device_label: "web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not sign in.");
      setStatus({ text: "Welcome back. Loading...", kind: "info" });
      finishLogin(data);
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Could not sign in.", kind: "error" });
      setLoading(false);
    }
  }

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setStatus({ text: "Sending code...", kind: "info" });
    try {
      const res = await fetch("/api/auth/login-code/request", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not send code.");
      setCodeSent(true);
      setStatus({ text: "If that email has an account, a 6-digit code is on its way (expires in 10 min).", kind: "info" });
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Could not send code.", kind: "error" });
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setStatus({ text: "Verifying...", kind: "info" });
    try {
      const res = await fetch("/api/auth/login-code/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, code, device_label: "web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Invalid code.");
      setStatus({ text: "Welcome back. Loading...", kind: "info" });
      finishLogin(data);
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Invalid code.", kind: "error" });
      setLoading(false);
    }
  }

  const subtitle =
    mode === "password"
      ? "Use your Elevation Real Estate HQ account."
      : codeSent
        ? "Enter the 6-digit code we emailed you."
        : "We'll email you a one-time sign-in code.";

  return (
    <AuthShell title="Sign in" subtitle={subtitle}>
      {mode === "password" && (
        <form onSubmit={submitPassword}>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" autoFocus required
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <label htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
          {status && <div className={`status ${status.kind}`}>{status.text}</div>}
        </form>
      )}

      {mode === "code" && !codeSent && (
        <form onSubmit={requestCode}>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" autoFocus required
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Sending code..." : "Email me a code"}
          </button>
          {status && <div className={`status ${status.kind}`}>{status.text}</div>}
        </form>
      )}

      {mode === "code" && codeSent && (
        <form onSubmit={verifyCode}>
          <label htmlFor="code">6-digit code</label>
          <input id="code" type="text" inputMode="numeric" autoComplete="one-time-code"
            className="code" maxLength={6} placeholder="123456" autoFocus required
            value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Verify & sign in"}
          </button>
          {status && <div className={`status ${status.kind}`}>{status.text}</div>}
          <div className="alt-action" style={{ marginTop: 10 }}>
            <button type="button" className="linkbtn" onClick={() => { setCodeSent(false); setCode(""); setStatus(null); }}>
              Use a different email or resend
            </button>
          </div>
        </form>
      )}

      {mode === "password" && (
        <div className="row-links">
          <a href="/forgot">Forgot password?</a>
        </div>
      )}

      <div className="divider" />
      <div className="alt-action">
        <button type="button" className="linkbtn" onClick={() => switchMode(mode === "password" ? "code" : "password")}>
          {mode === "password" ? "Sign in with a code instead" : "Use password instead"}
        </button>
      </div>
    </AuthShell>
  );
}

export default function AdminLogin() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
