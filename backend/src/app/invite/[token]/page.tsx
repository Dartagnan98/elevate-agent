"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AuthShell } from "@/components/auth-shell";

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
        setErr("Create a password to finish signing up.");
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
    <AuthShell title="Accept invitation" subtitle="Join the organization and start using Elevation Real Estate HQ.">
      {done ? (
        <div className="notice">Joined. Redirecting…</div>
      ) : (
        <form onSubmit={submit}>
          {email && (
            <div className="notice" style={{ marginBottom: 2 }}>
              Signing up <strong>{email}</strong>
            </div>
          )}
          {needsPassword && (
            <>
              <label htmlFor="pw">Create password</label>
              <input id="pw" type="password" placeholder="At least 8 characters" minLength={8} required autoFocus
                autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </>
          )}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Joining..." : needsPassword ? "Create account & join" : "Accept invitation"}
          </button>
          {err && <div className="status error">{err}</div>}
        </form>
      )}

      <div className="divider" />
      <div className="footer">
        <a href="/admin/login">Back to sign in</a>
      </div>
    </AuthShell>
  );
}
