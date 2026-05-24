"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, ErrorBanner, Input, Label, LoadingRow } from "@/components/ui";

type GrantInfo = {
  user_code: string;
  device_label: string | null;
  status: "pending" | "approved" | "denied" | "expired" | "claimed";
  expires_at: string;
  created_at: string;
  ip_addr: string | null;
  user_agent: string | null;
};

function LinkInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [code, setCode] = useState((params.get("code") || "").toUpperCase());
  const [info, setInfo] = useState<GrantInfo | null>(null);
  const [me, setMe] = useState<{ email: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<"approved" | "denied" | null>(null);

  function token() {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("elevate_access");
  }

  useEffect(() => {
    const t = token();
    if (!t) {
      const back = encodeURIComponent(`/link${code ? `?code=${code}` : ""}`);
      router.push(`/admin/login?next=${back}`);
      return;
    }
    fetch("/api/me", { headers: { authorization: `Bearer ${t}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setMe({ email: d.email }))
      .catch(() => {});
  }, [code, router]);

  async function lookup(c: string) {
    const clean = c.trim().toUpperCase();
    if (clean.length < 4) {
      setInfo(null);
      return;
    }
    setLoading(true);
    setErr(null);
    setInfo(null);
    try {
      const t = token();
      const res = await fetch(`/api/device/lookup?code=${encodeURIComponent(clean)}`, {
        headers: { authorization: `Bearer ${t}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "lookup failed");
      setInfo(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "lookup failed");
    } finally {
      setLoading(false);
    }
  }

  // Auto-lookup when code is in URL
  useEffect(() => {
    if (code && code.length >= 8) lookup(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(action: "approve" | "deny") {
    if (!info) return;
    setLoading(true);
    setErr(null);
    try {
      const t = token();
      const res = await fetch(`/api/device/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${t}` },
        body: JSON.stringify({ user_code: info.user_code }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `${action} failed`);
      setDone(action === "approve" ? "approved" : "denied");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setLoading(false);
    }
  }

  function formatCode(raw: string) {
    const clean = raw.replace(/[^A-Z0-9]/gi, "").toUpperCase().slice(0, 8);
    return clean.length > 4 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
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
          maxWidth: 460,
          background: "var(--bg-elev)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-xl)",
          padding: "32px 28px",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
          <svg width="32" height="32" viewBox="0 0 28 28" fill="none" aria-hidden="true">
            <rect width="28" height="28" rx="7" fill="var(--accent)" />
            <path d="M9 9h10v2.5h-7.5v3h6V17h-6v3H19V22.5H9V9z" fill="#fff" />
          </svg>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>Link a device</div>
            <div
              style={{
                fontSize: 10,
                color: "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              authorize new sign-in
            </div>
          </div>
        </div>

        {me && (
          <div
            style={{
              padding: "8px 12px",
              background: "var(--bg-input-solid)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-md)",
              fontSize: 12,
              color: "var(--text-dim)",
              marginBottom: 18,
            }}
          >
            Signed in as <strong style={{ color: "var(--text)" }}>{me.email}</strong>
          </div>
        )}

        {done === "approved" ? (
          <div
            style={{
              padding: "16px 14px",
              background: "var(--sage-bg)",
              border: "1px solid #3a5a44",
              borderLeft: "3px solid var(--sage)",
              borderRadius: "var(--r-md)",
              color: "var(--sage)",
              fontSize: 13,
            }}
          >
            Device linked. You can close this tab — your CLI / app will pick up the
            session within a few seconds.
          </div>
        ) : done === "denied" ? (
          <div
            style={{
              padding: "16px 14px",
              background: "var(--red-bg)",
              border: "1px solid #5a2a2a",
              borderLeft: "3px solid var(--red)",
              borderRadius: "var(--r-md)",
              color: "var(--red)",
              fontSize: 13,
            }}
          >
            Request denied. The device will not get access.
          </div>
        ) : info ? (
          <div style={{ display: "grid", gap: 14 }}>
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-dim)" }}>
              A device is asking to sign in with your account. Approve only if you
              started this from your own machine.
            </p>
            <div
              style={{
                padding: 14,
                background: "var(--bg-input-solid)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                display: "grid",
                gap: 8,
                fontSize: 12,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-dim)" }}>Code</span>
                <code style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>
                  {info.user_code}
                </code>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-dim)" }}>Device label</span>
                <span style={{ color: "var(--text)" }}>{info.device_label || "—"}</span>
              </div>
              {info.ip_addr && (
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-dim)" }}>IP</span>
                  <code style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>
                    {info.ip_addr.split(",")[0]}
                  </code>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-dim)" }}>Status</span>
                <Badge
                  size="sm"
                  tone={
                    info.status === "pending"
                      ? "amber"
                      : info.status === "approved" || info.status === "claimed"
                        ? "sage"
                        : "red"
                  }
                >
                  {info.status}
                </Badge>
              </div>
            </div>

            {info.status !== "pending" && (
              <ErrorBanner>
                This request is {info.status}. Start a new one from the device.
              </ErrorBanner>
            )}

            {err && <ErrorBanner>{err}</ErrorBanner>}

            <div style={{ display: "flex", gap: 8 }}>
              <Button
                variant="ghost"
                onClick={() => act("deny")}
                disabled={loading || info.status !== "pending"}
                style={{ flex: 1 }}
              >
                Deny
              </Button>
              <Button
                variant="primary"
                onClick={() => act("approve")}
                loading={loading}
                disabled={info.status !== "pending"}
                style={{ flex: 1 }}
              >
                Approve
              </Button>
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              lookup(code);
            }}
            style={{ display: "grid", gap: 14 }}
          >
            <div>
              <Label>Enter the code shown on your device</Label>
              <Input
                value={code}
                onChange={(e) => setCode(formatCode(e.target.value))}
                placeholder="ABCD-EFGH"
                autoFocus
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 18,
                  letterSpacing: "0.1em",
                  textAlign: "center",
                  padding: "12px",
                }}
                maxLength={9}
              />
            </div>
            {err && <ErrorBanner>{err}</ErrorBanner>}
            <Button
              variant="primary"
              type="submit"
              loading={loading}
              disabled={code.replace(/[^A-Z0-9]/gi, "").length < 8}
              style={{ width: "100%" }}
            >
              Continue
            </Button>
          </form>
        )}

        <div
          style={{
            marginTop: 22,
            paddingTop: 16,
            borderTop: "1px solid var(--border)",
            fontSize: 12,
            color: "var(--text-dim)",
            textAlign: "center",
          }}
        >
          Not trying to link a device?{" "}
          <Link href="/account" style={{ color: "var(--accent)" }}>
            Go to your account
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function LinkPage() {
  return (
    <Suspense fallback={<LoadingRow />}>
      <LinkInner />
    </Suspense>
  );
}
