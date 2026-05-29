"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth-shell";

type ForgotResponse = {
  ok: boolean;
  dev_only?: { reset_url: string; token: string; expires_at: string };
};

function ForgotInner() {
  const params = useSearchParams();
  // Started from inside the Elevate desktop app — the reset link should bounce
  // back to the app, and we shouldn't offer "back to the HQ sign-in" here.
  const fromApp = params.get("app") === "1";
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
        body: JSON.stringify({ email, app: fromApp }),
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
    <AuthShell
      title="Reset your password"
      subtitle={
        fromApp
          ? "Enter your email and we'll send you a reset link. Open it, set a new password, then return to the Elevate app to sign in."
          : "Enter your email and we'll send you a reset link."
      }
    >
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
            {fromApp && " Open the link, choose a new password, then head back to the Elevate app to sign in."}
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
        {fromApp ? (
          <span style={{ color: "var(--text-dim)" }}>Return to the Elevate app to sign in.</span>
        ) : (
          <a href="/admin/login">Back to sign in</a>
        )}
      </div>
    </AuthShell>
  );
}

export default function ForgotPage() {
  return (
    <Suspense fallback={null}>
      <ForgotInner />
    </Suspense>
  );
}
