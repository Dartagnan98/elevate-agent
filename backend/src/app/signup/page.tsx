"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth-shell";

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

  const loginHref = `/admin/login${next !== "/account" ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <AuthShell title="Create your account" subtitle="Start a personal workspace. Add teammates or buy packages later.">
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" placeholder="you@company.com" required autoFocus
          autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" placeholder="At least 8 characters" minLength={8} required
          autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="primary" type="submit" disabled={loading}>
          {loading ? "Creating account..." : "Create account"}
        </button>
        {err && <div className="status error">{err}</div>}
      </form>

      <div className="divider" />
      <div className="footer">
        Already have an account? <a href={loginHref}>Sign in</a>
      </div>
    </AuthShell>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupInner />
    </Suspense>
  );
}
