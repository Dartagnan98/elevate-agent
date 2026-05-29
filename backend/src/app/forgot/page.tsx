"use client";

import { useState } from "react";
import { AuthShell } from "@/components/auth-shell";

type ForgotResponse = {
  ok: boolean;
  dev_only?: { reset_url: string; token: string; expires_at: string };
};

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/forgot", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data: ForgotResponse = await res.json();
      if (!res.ok) throw new Error("request failed");
      setSent(true);
      if (data.dev_only?.reset_url) setResetUrl(data.dev_only.reset_url);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setLoading(false);
    }
  }

  async function copyLink() {
    if (!resetUrl) return;
    await navigator.clipboard.writeText(resetUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <AuthShell title="Reset your password" subtitle="Enter your email and we'll send you a reset link.">
      {!sent ? (
        <form onSubmit={submit}>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" placeholder="you@company.com" required autoFocus
            autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Sending..." : "Send reset link"}
          </button>
          {err && <div className="status error">{err}</div>}
        </form>
      ) : (
        <div>
          <div className="notice">
            If that email is registered, a reset link is on its way. Check your inbox.
          </div>
          {resetUrl && (
            <div className="devbox">
              <div className="lbl">dev link (email not configured)</div>
              <div className="url">{resetUrl}</div>
              <div className="actions">
                <button type="button" className="primary ghost sm" onClick={copyLink}>
                  {copied ? "Copied" : "Copy link"}
                </button>
                <a href={resetUrl}>
                  <button type="button" className="primary sm">Open</button>
                </a>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="divider" />
      <div className="footer">
        <a href="/admin/login">Back to sign in</a>
      </div>
    </AuthShell>
  );
}
