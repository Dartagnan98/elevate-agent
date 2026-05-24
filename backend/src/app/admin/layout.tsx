"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Avatar, Badge } from "@/components/ui";

type SearchResp = {
  users: Array<{ id: string; email: string; tier: string; role: string }>;
  orgs: Array<{ id: string; slug: string; name: string; tier: string }>;
  licenses: Array<{ id: string; device_label: string | null; user_email: string | null }>;
  audit: Array<{ id: string; action: string; created_at: string }>;
};

type Me = { email: string; role: string; is_developer: boolean } | null;

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResp | null>(null);
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState<Me>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLogin = pathname?.startsWith("/admin/login");

  function token() {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("elevate_access");
  }

  // Load identity once
  useEffect(() => {
    if (isLogin) return;
    const t = token();
    if (!t) return;
    fetch("/api/me", { headers: { authorization: `Bearer ${t}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setMe({ email: d.email, role: d.role, is_developer: !!d.is_developer }))
      .catch(() => {});
  }, [isLogin]);

  // Search (200ms debounce)
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!q.trim()) {
      setResults(null);
      return;
    }
    timer.current = setTimeout(async () => {
      const t = token();
      if (!t) return;
      try {
        const res = await fetch(`/api/admin/search?q=${encodeURIComponent(q)}&limit=8`, {
          headers: { authorization: `Bearer ${t}` },
        });
        if (!res.ok) return;
        setResults(await res.json());
        setOpen(true);
      } catch {
        // ignore
      }
    }, 200);
  }, [q]);

  function logout() {
    localStorage.removeItem("elevate_access");
    localStorage.removeItem("elevate_refresh");
    router.push("/admin/login");
  }

  if (isLogin) return <>{children}</>;

  const navItems = [
    { href: "/admin/users", label: "Users", section: "Manage" },
    { href: "/admin/orgs", label: "Organizations", section: "Manage" },
    { href: "/admin/audit", label: "Audit Log", section: "Observe" },
    { href: "/account", label: "My Account", section: "Observe" },
  ];
  const sections = Array.from(new Set(navItems.map((n) => n.section)));

  return (
    <div className="admin-shell">
      {/* sidebar */}
      <aside className="admin-sidebar">
        <Link
          href="/admin/users"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "20px 22px 16px",
            borderBottom: "1px solid var(--border)",
            color: "var(--text)",
            textDecoration: "none",
          }}
        >
          <BrandMark />
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.01em" }}>Elevate HQ</div>
            <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              control panel
            </div>
          </div>
        </Link>

        <nav style={{ flex: 1, paddingTop: 4 }}>
          {sections.map((section) => (
            <div key={section}>
              <div className="nav-section-label">{section}</div>
              {navItems
                .filter((n) => n.section === section)
                .map((item) => {
                  const active =
                    item.href === "/admin/users"
                      ? pathname === item.href
                      : pathname?.startsWith(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`nav-item ${active ? "active" : ""}`}
                    >
                      {item.label}
                    </Link>
                  );
                })}
            </div>
          ))}
        </nav>

        {/* identity footer */}
        {me && (
          <div
            style={{
              padding: 14,
              borderTop: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <Avatar email={me.email} size={32} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={me.email}
              >
                {me.email}
              </div>
              <div style={{ display: "flex", gap: 4, marginTop: 3 }}>
                <Badge tone="neutral" size="sm">{me.role}</Badge>
                {me.is_developer && <Badge tone="dev" size="sm">dev</Badge>}
              </div>
            </div>
            <button
              onClick={logout}
              title="Sign out"
              aria-label="Sign out"
              style={{
                background: "transparent",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                color: "var(--text-dim)",
                cursor: "pointer",
                padding: 6,
                lineHeight: 0,
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
            </button>
          </div>
        )}
      </aside>

      {/* main */}
      <div className="admin-main">
        <div className="admin-topbar">
          <div style={{ position: "relative", flex: 1, maxWidth: 520 }}>
            <SearchIcon />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={() => results && setOpen(true)}
              onBlur={() => setTimeout(() => setOpen(false), 200)}
              placeholder="Search users, organizations, licenses, audit…"
              aria-label="Search"
              style={{
                width: "100%",
                padding: "8px 12px 8px 36px",
                background: "var(--bg-input-solid)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                color: "var(--text)",
                fontSize: 13,
                outline: "none",
              }}
            />
            {open && results && (
              <div
                style={{
                  position: "absolute",
                  top: 42,
                  left: 0,
                  right: 0,
                  background: "var(--bg-elev)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--r-lg)",
                  maxHeight: 480,
                  overflowY: "auto",
                  zIndex: 50,
                  boxShadow: "var(--shadow-lg)",
                }}
              >
                {renderGroup("Users", results.users, (u) => ({
                  title: u.email,
                  subtitle: `${u.role} · ${u.tier}`,
                  href: `/admin/users`,
                }))}
                {renderGroup("Organizations", results.orgs, (o) => ({
                  title: o.name,
                  subtitle: `${o.slug} · ${o.tier}`,
                  href: `/admin/orgs/${o.id}`,
                }))}
                {renderGroup("Licenses", results.licenses, (l) => ({
                  title: l.device_label || "(no label)",
                  subtitle: l.user_email || "",
                  href: `/admin/users`,
                }))}
                {renderGroup("Audit", results.audit, (a) => ({
                  title: a.action,
                  subtitle: new Date(a.created_at).toLocaleString(),
                  href: `/admin/audit`,
                }))}
                {results.users.length + results.orgs.length + results.licenses.length + results.audit.length === 0 && (
                  <div style={{ padding: 14, color: "var(--text-dim)", fontSize: 13 }}>No matches</div>
                )}
              </div>
            )}
          </div>
        </div>
        <main className="admin-content fade-in">{children}</main>
      </div>
    </div>
  );
}

function renderGroup<T>(
  label: string,
  items: T[],
  toCard: (item: T) => { title: string; subtitle: string; href: string },
) {
  if (!items.length) return null;
  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <div
        style={{
          padding: "8px 14px 4px",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--text-dim)",
        }}
      >
        {label}
      </div>
      {items.map((item, i) => {
        const c = toCard(item);
        return (
          <Link key={i} href={c.href} className="search-result">
            <div style={{ fontSize: 13 }}>{c.title}</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 1 }}>{c.subtitle}</div>
          </Link>
        );
      })}
    </div>
  );
}

function BrandMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect width="28" height="28" rx="7" fill="var(--accent)" />
      <path
        d="M9 9h10v2.5h-7.5v3h6V17h-6v3H19V22.5H9V9z"
        fill="#fff"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      style={{
        position: "absolute",
        left: 12,
        top: "50%",
        transform: "translateY(-50%)",
        color: "var(--text-dim)",
        pointerEvents: "none",
      }}
    >
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.5-4.5" />
    </svg>
  );
}
