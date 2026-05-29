"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

// The real control panel. The /admin/* pages (users, orgs, audit) are the
// functional surfaces that call the live /api/admin/* endpoints; this layout
// just provides the shell + nav and renders the active page via {children}.
//
// (The old layout hardcoded a <AdminBoard /> design mockup and never rendered
// {children}, so every route showed the same fake "Top 25 sellers" demo board
// with seed data. That shell — admin.css / components/admin-board / the mock
// sidebar — is retired; it was a clone of the agent product, wrong context for
// the HQ backend.)

const NAV: { href: string; label: string; match: (p: string) => boolean }[] = [
  {
    href: "/admin/users",
    label: "Teams & Users",
    match: (p) => p === "/admin/users" || p.startsWith("/admin/orgs"),
  },
  {
    href: "/admin/audit",
    label: "Audit Log",
    match: (p) => p.startsWith("/admin/audit"),
  },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const router = useRouter();

  // The login page is its own full-screen auth shell — no admin chrome.
  if (pathname.startsWith("/admin/login")) return <>{children}</>;

  function signOut() {
    try {
      localStorage.removeItem("elevate_access");
      localStorage.removeItem("elevate_refresh");
    } catch {
      /* ignore */
    }
    router.push("/admin/login");
  }

  return (
    <div
      style={{
        display: "flex",
        minHeight: "100dvh",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <aside
        style={{
          width: 232,
          flexShrink: 0,
          height: "100dvh",
          position: "sticky",
          top: 0,
          borderRight: "1px solid var(--border)",
          background: "var(--bg-elev)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ padding: "20px 18px 16px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: "var(--accent)" }} />
            <span style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-0.01em" }}>
              Elevation Real Estate HQ
            </span>
          </div>
          <div
            style={{
              marginTop: 4,
              marginLeft: 18,
              fontSize: 10.5,
              color: "var(--text-dim)",
              fontFamily: "var(--font-mono)",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            Control panel
          </div>
        </div>

        <nav style={{ padding: 10, display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  padding: "8px 12px",
                  borderRadius: "var(--r-md, 6px)",
                  fontSize: 13,
                  textDecoration: "none",
                  color: active ? "var(--text)" : "var(--text-muted)",
                  background: active ? "var(--accent-bg)" : "transparent",
                  border: active ? "1px solid var(--border-strong)" : "1px solid transparent",
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div style={{ padding: 10, borderTop: "1px solid var(--border)" }}>
          <button
            onClick={signOut}
            style={{
              width: "100%",
              textAlign: "left",
              padding: "8px 12px",
              borderRadius: "var(--r-md, 6px)",
              fontSize: 13,
              color: "var(--text-muted)",
              background: "transparent",
              border: "1px solid transparent",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <main style={{ flex: 1, minWidth: 0, overflowX: "hidden" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "32px 32px 64px" }}>
          {children}
        </div>
      </main>
    </div>
  );
}
