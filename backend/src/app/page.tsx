"use client";

import { AUTH_STYLES } from "@/components/auth-shell";

export default function Page() {
  return (
    <div className="el-auth">
      <style dangerouslySetInnerHTML={{ __html: AUTH_STYLES }} />
      <div className="aurora" aria-hidden />
      <div
        style={{
          position: "relative",
          zIndex: 1,
          textAlign: "center",
          maxWidth: 420,
          animation: "el-rise 520ms cubic-bezier(0.22,1,0.36,1) both",
        }}
      >
        <img
          src="/elevateos-wordmark-dark.png"
          alt="Elevate"
          style={{ height: 34, width: "auto", objectFit: "contain", marginBottom: 22 }}
        />
        <p style={{ color: "#A0A0A0", margin: "0 0 28px", fontSize: 14, lineHeight: 1.5 }}>
          Control panel for users, organizations, and entitlements.
        </p>
        <div style={{ display: "inline-flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
          <a href="/admin/login" style={{
            display: "inline-flex", alignItems: "center", padding: "10px 18px",
            background: "#8A8A8A", color: "#0F0F0F", border: 0, borderRadius: 6,
            fontSize: 14, fontWeight: 600, textDecoration: "none",
          }}>
            Sign in
          </a>
        </div>
        <p style={{ color: "#6E6E6E", margin: "20px 0 0", fontSize: 12, lineHeight: 1.5 }}>
          Access is invite-only. If you have an invitation, use the link in your email.
        </p>
      </div>
    </div>
  );
}
