"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, ErrorBanner, Input, Label } from "@/components/ui";

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
      if (data.dev_only?.reset_url) {
        setResetUrl(data.dev_only.reset_url);
      }
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
          maxWidth: 420,
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
              password reset
            </div>
          </div>
        </div>

        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>
          Reset your password
        </h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-dim)", fontSize: 13 }}>
          Enter your email and we'll send you a reset link.
        </p>

        {!sent ? (
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
            <Button variant="primary" type="submit" loading={loading} style={{ width: "100%", marginTop: 4 }}>
              {loading ? "Sending" : "Send reset link"}
            </Button>
            {err && <ErrorBanner>{err}</ErrorBanner>}
          </form>
        ) : (
          <div>
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
              If that email is registered, a reset link has been generated. Check your inbox.
            </div>

            {resetUrl && (
              <div
                style={{
                  marginTop: 14,
                  padding: "14px 16px",
                  background: "var(--bg-input-solid)",
                  border: "1px dashed var(--border)",
                  borderRadius: "var(--r-md)",
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-dim)",
                    fontFamily: "var(--font-mono)",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    marginBottom: 8,
                  }}
                >
                  dev link (email infra not wired yet)
                </div>
                <div
                  style={{
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text)",
                    wordBreak: "break-all",
                    marginBottom: 10,
                  }}
                >
                  {resetUrl}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <Button variant="ghost" size="sm" onClick={copyLink}>
                    {copied ? "Copied" : "Copy link"}
                  </Button>
                  <Link href={resetUrl}>
                    <Button variant="primary" size="sm">
                      Open
                    </Button>
                  </Link>
                </div>
              </div>
            )}
          </div>
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
