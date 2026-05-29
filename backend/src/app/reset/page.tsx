"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth-shell";

function ResetInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";
  // Reset started from inside the Elevate desktop app — send the user back to
  // the app afterward instead of into the HQ backend admin.
  const fromApp = params.get("app") === "1";
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
      // Backend admins continue to the HQ sign-in. App users are NOT pushed
      // into the backend — they go back to the Elevate app to sign in.
      if (!fromApp) setTimeout(() => router.push("/admin/login"), 2500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "reset failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Choose a new password" subtitle="All your other sessions will be signed out.">
      {done ? (
        fromApp ? (
          <div>
            <div className="notice">
              Password updated for <strong>{done}</strong>. Head back to the Elevate app
              and sign in with your new password.
            </div>
            <div style={{ marginTop: 16 }}>
              <a href="elevate://signin">
                <button type="button" className="primary">Open the Elevate app</button>
              </a>
            </div>
          </div>
        ) : (
          <div className="notice">
            Password updated for <strong>{done}</strong>. Redirecting to sign in.
          </div>
        )
      ) : (
        <form onSubmit={submit}>
          <label htmlFor="pw">New password</label>
          <input id="pw" type="password" placeholder="At least 8 characters" minLength={8} required autoFocus
            autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <label htmlFor="confirm">Confirm password</label>
          <input id="confirm" type="password" placeholder="Re-enter password" minLength={8} required
            autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Saving..." : "Set new password"}
          </button>
          {err && <div className="status error">{err}</div>}
        </form>
      )}

      <div className="divider" />
      <div className="footer">
        {fromApp ? (
          <span style={{ color: "var(--text-dim)" }}>Return to the Elevate app to sign in.</span>
        ) : (
          <a href="/admin/login">Back to sign in</a>
        )}
      </div>
    </AuthShell>
  );
}

export default function ResetPage() {
  return (
    <Suspense fallback={null}>
      <ResetInner />
    </Suspense>
  );
}
